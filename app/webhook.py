"""Authenticated httpSMS ingestion with durable, atomic admission guards."""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.db import connect_db, expire_event_phones, hash_phone, record_event

router = APIRouter()


def verify_token(authorization: str, secret: str) -> bool:
    if not secret or not authorization.startswith("Bearer "):
        return False
    try:
        header, payload, signature = authorization[7:].split(".")

        def decode(value: str) -> bytes:
            return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)

        algorithm = json.loads(decode(header))
        claims = json.loads(decode(payload))
        if algorithm.get("alg") != "HS256" or not isinstance(claims, dict):
            return False
        expected = hmac.new(
            secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, decode(signature)):
            return False
        now = time.time()
        return ("exp" not in claims or float(claims["exp"]) > now) and (
            "nbf" not in claims or float(claims["nbf"]) <= now
        )
    except (ValueError, TypeError, AttributeError, binascii.Error, UnicodeDecodeError):
        return False


def canonical_mobile(sender: str) -> str | None:
    if re.fullmatch(r"\+639\d{9}", sender, flags=re.ASCII):
        return sender
    if re.fullmatch(r"09\d{9}", sender, flags=re.ASCII):
        return "+63" + sender[1:]
    if re.fullmatch(r"639\d{9}", sender, flags=re.ASCII):
        return "+" + sender
    return None


class IncomingMessage(BaseModel):
    contact: str = Field(min_length=1, max_length=128)
    content: str = Field(max_length=10000)
    message_id: str = Field(min_length=1, max_length=256)


class GatewayEvent(BaseModel):
    type: str
    data: dict[str, Any]


@router.post("/webhook/httpsms")
async def receive(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    settings = request.app.state.settings
    if not verify_token(request.headers.get("authorization", ""), settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook authentication")
    try:
        event = GatewayEvent.model_validate(await request.json())
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid gateway event") from exc
    if event.type != "message.phone.received":
        return {"ok": True}
    try:
        message = IncomingMessage.model_validate(event.data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid incoming message") from exc
    sender = canonical_mobile(message.contact)
    if await run_in_threadpool(admit_message, settings, message.message_id, sender):
        background_tasks.add_task(request.app.state.message_handler.handle, sender, message.content)
    return {"ok": True}


def admit_message(settings: Settings, message_id: str, sender: str | None) -> bool:
    """Perform atomic SQLite admission away from the request event loop."""
    phone = hash_phone(sender, settings) if sender else None
    with connect_db(settings.db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        expire_event_phones(connection)
        inserted = connection.execute(
            "INSERT OR IGNORE INTO processed_events (event_id, phone_hash) VALUES (?, ?)",
            (message_id, phone),
        ).rowcount
        if not inserted:
            record_event(connection, "duplicate_dropped")
            return False
        if sender is None:
            record_event(connection, "non_mobile_ignored")
            return False
        count = connection.execute(
            """SELECT count(*) FROM processed_events WHERE phone_hash = ?
            AND received_at > datetime('now', '-1 hour')""",
            (phone,),
        ).fetchone()[0]
        if count > 10:
            record_event(connection, "rate_limit_hit")
            return False
    return True
