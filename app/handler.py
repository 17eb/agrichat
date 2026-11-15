"""Keyword message handling using stored profiles and precomputed indicators."""

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.db import EventSource, connect_db, expire_event_phones, hash_phone, record_event
from app.parser import CROP_ALIASES, CROP_NAMES, Command, normalize, parse
from app.sms import SmsGateway
from app.templates import Reply, render, validate_sms
from engine.crops import load_crops
from engine.reason_codes import REASON_CODES
from engine.rotation import Indicator, Profile, Result, recommend


class IntentExtractor(Protocol):
    def extract(self, text: str) -> Command | None: ...


def today_in_manila() -> date:
    return datetime.now(ZoneInfo("Asia/Manila")).date()


class MessageHandler:
    def __init__(
        self,
        settings: Settings,
        gateway: SmsGateway,
        extractor: IntentExtractor | None = None,
        today: Callable[[], date] = today_in_manila,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.extractor = extractor
        self.today = today
        self.crops = load_crops()

    def handle(self, sender: str, text: str) -> Reply:
        phone = hash_phone(sender, self.settings)
        command = parse(text)
        source: EventSource = "keyword"
        model_failed = False
        if command is None and self.settings.llm_enabled:
            source = "model"
            try:
                if self.extractor is None:
                    raise RuntimeError("Intent extraction is unavailable")
                command = self.extractor.extract(text)
            except (httpx.HTTPError, ValueError, RuntimeError):
                model_failed = True
        with connect_db(self.settings.db_path) as connection:
            if model_failed:
                record_event(connection, "model_call_failed", source="model")
            context: dict[str, str] = {}
            if command is None:
                source = "fallback"
                refer = any(
                    word in normalize(text).split()
                    for word in (
                        "PATABA",
                        "GAMOT",
                        "PESTE",
                        "FERTILIZER",
                        "CHEMICAL",
                        "CHEMICALS",
                        "PEST",
                        "PESTS",
                    )
                )
                reply = render("T_REFER" if refer else "T_FALLBACK")
                event = "refusal" if refer else "fallback_used"
            else:
                reply, event = self._command(connection, phone, command, context)
        intent = command.intent if command else "OTHER"
        if reply.template_id == "T_FALLBACK":
            event = "fallback_used"
        if not validate_sms(reply.text):
            reply = render("T_FALLBACK")
            event = "fallback_used"
        sent = True
        try:
            self.gateway.send(sender, reply.text)
        except (httpx.HTTPError, ValueError):
            sent = False
        with connect_db(self.settings.db_path) as connection:
            if event != "recommendation_sent" or sent:
                record_event(
                    connection, event, intent=intent, template_id=reply.template_id, source=source
                )
            if not sent:
                record_event(
                    connection, "send_failed", intent=intent, template_id=reply.template_id
                )
            if intent != "STOP":
                connection.execute(
                    "INSERT INTO messages (phone_hash, direction, text, intent) "
                    "VALUES (?, 'in', ?, ?)",
                    (phone, text, intent),
                )
                if sent:
                    connection.execute(
                        """INSERT INTO messages
                        (phone_hash, direction, text, intent, template_id, context)
                        VALUES (?, 'out', ?, ?, ?, ?)""",
                        (
                            phone,
                            reply.text,
                            intent,
                            reply.template_id,
                            context.get("recommendation"),
                        ),
                    )
        return reply

    def _command(
        self,
        connection: sqlite3.Connection,
        phone: str,
        command: Command,
        context: dict[str, str],
    ) -> tuple[Reply, str]:
        intent, argument = command.intent, command.argument
        if intent == "STOP":
            expire_event_phones(connection)
            connection.execute("DELETE FROM farmers WHERE phone_hash = ?", (phone,))
            connection.execute("DELETE FROM messages WHERE phone_hash = ?", (phone,))
            connection.execute(
                "UPDATE processed_events SET phone_hash = NULL WHERE phone_hash = ?", (phone,)
            )
            return render("T_STOP_OK"), "stop_received"
        if intent == "HELP":
            return render("T_HELP"), "command_handled"
        if intent == "REG":
            parts = argument.rsplit(maxsplit=1)
            if len(parts) == 2 and parts[1] in {"ULAN", "PATUBIG", "BOMBA"}:
                for barangay in connection.execute("SELECT * FROM barangays"):
                    names = [
                        barangay["name"],
                        barangay["barangay_code"],
                        *barangay["aliases"].split("|"),
                    ]
                    if parts[0] not in {normalize(name) for name in names}:
                        continue
                    connection.execute(
                        """INSERT INTO farmers (phone_hash, barangay_code, water_source)
                        VALUES (?, ?, ?) ON CONFLICT(phone_hash) DO UPDATE SET
                        barangay_code=excluded.barangay_code, water_source=excluded.water_source""",
                        (phone, barangay["barangay_code"], parts[1]),
                    )
                    return render("T_REG_OK", brgy=barangay["name"], tubig=parts[1]), "registered"
            return render("T_FALLBACK"), "fallback_used"
        profile = connection.execute(
            "SELECT * FROM farmers WHERE phone_hash = ?", (phone,)
        ).fetchone()
        if profile is None:
            return render("T_HELP"), "fallback_used"
        if intent == "LAST" and argument in CROP_ALIASES:
            crop = CROP_ALIASES[argument]
            connection.execute(
                "UPDATE farmers SET last_crop = ? WHERE phone_hash = ?", (crop, phone)
            )
            return render("T_LAST_OK", crop=CROP_NAMES[crop]), "command_handled"
        if intent == "PRIO" and argument in {"TUBIG", "KITA"}:
            connection.execute(
                "UPDATE farmers SET priority = ? WHERE phone_hash = ?", (argument, phone)
            )
            return render("T_PRIO_OK", priority=argument), "command_handled"
        if intent == "PLANT":
            if profile["water_source"] != "ULAN":
                row = connection.execute(
                    """SELECT rain30_pct, soilwet_pct FROM indicators
                    WHERE barangay_code = ? ORDER BY updated_at DESC, crop LIMIT 1""",
                    (profile["barangay_code"],),
                ).fetchone()
                if row and row["rain30_pct"] is not None and row["soilwet_pct"] is not None:
                    return render(
                        "T_IRRIGATED",
                        rain=f"{row['rain30_pct']:.0f}",
                        soil=f"{row['soilwet_pct']:.0f}",
                    ), "refusal"
                return render("T_IRRIGATED_NO_DATA"), "refusal"
            result = self._recommend(connection, profile)
            barangay = connection.execute(
                "SELECT name FROM barangays WHERE barangay_code = ?", (profile["barangay_code"],)
            ).fetchone()
            if not result.crops:
                return render(
                    "T_NO_DATA", brgy=barangay[0] if barangay else profile["barangay_code"]
                ), "refusal"
            best = result.crops[0]
            second = result.crops[1] if len(result.crops) > 1 else best
            source = connection.execute(
                "SELECT source FROM crops WHERE crop = ?", (best.name,)
            ).fetchone()
            tag = re.match(r"^(FAO-56)\b", source[0]) if source else None
            if tag is None:
                return render("T_REFER"), "refusal"
            context["recommendation"] = json.dumps(
                {"reasons": best.reason_codes[:2], "source": tag.group(1)}
            )
            return render(
                result.template,
                crop1=CROP_NAMES[best.name],
                crop2=CROP_NAMES[second.name],
                a=best.n_adequate,
                b=second.n_adequate,
                n=best.n_years,
            ), "recommendation_sent"
        if intent == "WHY":
            row = connection.execute(
                """SELECT context FROM messages WHERE phone_hash = ? AND direction = 'out'
                AND template_id IN ('T_PLANT', 'T_PLANT_BORDER') ORDER BY id DESC LIMIT 1""",
                (phone,),
            ).fetchone()
            if row and row[0]:
                context = json.loads(row[0])
                reasons = list(dict.fromkeys(REASON_CODES[code] for code in context["reasons"]))[:2]
                return render(
                    "T_WHY",
                    reason1=reasons[0],
                    reason2=reasons[1] if len(reasons) > 1 else "",
                    sources=context["source"],
                ), "command_handled"
        return render("T_FALLBACK"), "fallback_used"

    def _recommend(self, connection: sqlite3.Connection, profile: sqlite3.Row) -> Result:
        indicators = {
            row["crop"]: Indicator(**{key: row[key] for key in Indicator.__dataclass_fields__})
            for row in connection.execute(
                "SELECT * FROM indicators WHERE barangay_code = ?", (profile["barangay_code"],)
            )
        }
        return recommend(
            Profile(
                profile["barangay_code"],
                profile["last_crop"],
                profile["water_source"],
                profile["priority"],
                self.today(),
            ),
            indicators,
            self.crops,
            self.settings.season_el_nino,
        )
