"""Small outbound gateway interface, with bounded HTTP requests."""

from typing import Protocol

import httpx

from app.config import Settings
from app.templates import TEMPLATES, clean_sms, validate_sms


class SmsGateway(Protocol):
    def send(self, recipient: str, text: str) -> None: ...


class HttpSmsGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, recipient: str, text: str) -> None:
        text = clean_sms(text)
        if not validate_sms(text):
            text = TEMPLATES["T_FALLBACK"]
        response = httpx.post(
            "https://api.httpsms.com/v1/messages/send",
            headers={"x-api-key": self.settings.require("httpsms_api_key")},
            json={"from": self.settings.require("httpsms_from"), "to": recipient, "content": text},
            timeout=10.0,
        )
        response.raise_for_status()
