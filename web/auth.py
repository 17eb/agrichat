"""Admin sign-in: Argon2 check, signed session cookie, CSRF token and the session guard."""

import hmac
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

LOGIN_URL = "/admin/login"
COOKIE_NAME = "agrichat_session"
SESSION_SECONDS = 8 * 60 * 60
LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_PASSWORD_LENGTH = 1024
NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}

_hasher = PasswordHasher()


@dataclass(frozen=True)
class Session:
    csrf_token: str
    issued_at: float

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.issued_at + SESSION_SECONDS - time.time()))


def verify_password(password: str, password_hash: str) -> bool:
    """True only when the Argon2 hash matches; an unset or malformed hash never matches."""
    if not password_hash or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="agrichat-admin-session")


def new_session_cookie(secret: str) -> str:
    return _serializer(secret).dumps({"csrf": secrets.token_urlsafe(32)})


def read_session(cookie: str | None, secret: str) -> Session | None:
    """Decode a session cookie; None when missing, forged or older than 8 hours."""
    if not cookie or not secret:
        return None
    try:
        payload, issued = _serializer(secret).loads(
            cookie, max_age=SESSION_SECONDS, return_timestamp=True
        )
    except BadSignature:
        return None
    token = payload.get("csrf") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return None
    return Session(csrf_token=token, issued_at=issued.timestamp())


def require_session(request: Request) -> Session:
    """The one guard for every admin route: no valid session redirects to the login page."""
    session = read_session(
        request.cookies.get(COOKIE_NAME), request.app.state.settings.session_secret
    )
    if session is None:
        raise HTTPException(status_code=303, headers={"Location": LOGIN_URL, **NO_STORE})
    return session


def csrf_valid(session: Session, submitted: str) -> bool:
    return bool(submitted) and hmac.compare_digest(session.csrf_token.encode(), submitted.encode())
