"""Environment configuration, loaded without requiring unused integrations."""

import os
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_DB_PATH = "data/agrichat.db"

SecretName = Literal[
    "httpsms_api_key",
    "httpsms_from",
    "webhook_secret",
    "phone_hash_secret",
    "llm_endpoint",
    "llm_key",
    "llm_model",
    "admin_password_hash",
    "session_secret",
]


def _boolean(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ValueError(f"{name} must be a boolean")
    return value in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    httpsms_api_key: str = field(default="", repr=False)
    httpsms_from: str = field(default="", repr=False)
    webhook_secret: str = field(default="", repr=False)
    phone_hash_secret: str = field(default="", repr=False)
    llm_endpoint: str = ""
    llm_key: str = field(default="", repr=False)
    llm_model: str = ""
    embedding_model: str = ""
    llm_enabled: bool = False
    db_path: str = DEFAULT_DB_PATH
    season_el_nino: bool = False
    admin_password_hash: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            httpsms_api_key=os.getenv("HTTPSMS_API_KEY", ""),
            httpsms_from=os.getenv("HTTPSMS_FROM", ""),
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            phone_hash_secret=os.getenv("PHONE_HASH_SECRET", ""),
            llm_endpoint=os.getenv("LLM_ENDPOINT", ""),
            llm_key=os.getenv("LLM_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            llm_enabled=_boolean("LLM_ENABLED"),
            db_path=os.getenv("DB_PATH", DEFAULT_DB_PATH),
            season_el_nino=_boolean("SEASON_EL_NINO"),
            admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
            session_secret=os.getenv("SESSION_SECRET", ""),
        )

    def require(self, name: SecretName) -> str:
        value: str = getattr(self, name)
        if not value.strip():
            raise ValueError(f"{name.upper()} is required for this feature")
        return value
