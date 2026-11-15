"""Constrained command extraction and optional template slot ordering."""

import json
import logging
import re
from collections.abc import Callable
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.parser import CROP_ALIASES, Command, normalize
from app.templates import Reply, validate_sms

logger = logging.getLogger(__name__)
RESTRICTED = re.compile(
    r"\b(pataba|gamot|peste|pests?|fertili[sz]ers?|chemicals?|pesticides?|"
    r"insecticides?|herbicides?|fungicides?|doses?|dosage|dilution|concentration|"
    r"kemikal|abono|lason|spray|dosis|pestisidyo|insekto|pamatay)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:ml|mg|ppm|cc)\b|"
    r"\b(?:dilut\w*|mix\w*|halo\w*|timpla\w*)\b[^.!?]{0,40}\d+\s*:\s*\d+|"
    r"\d+\s*:\s*\d+[^.!?]{0,40}\b(?:dilut\w*|mix\w*|halo\w*|timpla\w*)\b",
    re.IGNORECASE,
)


def restricted(text: str) -> bool:
    return bool(RESTRICTED.search(text))


def redact(text: str) -> str:
    return re.sub(r"\+?\d[\d ()-]{8,}\d", "[redacted]", text)


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["REG", "LAST", "PRIO", "PLANT", "WHY", "HELP", "STOP", "OTHER"]
    barangay: str | None
    water: Literal["ULAN", "PATUBIG", "BOMBA"] | None
    crop: str | None
    priority: Literal["TUBIG", "KITA"] | None
    confidence: float = Field(ge=0, le=1)


class ModelClient(Protocol):
    def complete(self, system: str, user: str, schema: dict[str, object]) -> str: ...


class ChatClient:
    def __init__(self, settings: Settings) -> None:
        self.endpoint = settings.require("llm_endpoint")
        self.model = settings.require("llm_model")
        self.key = settings.require("llm_key")

    def complete(self, system: str, user: str, schema: dict[str, object]) -> str:
        for attempt in range(2):
            try:
                response = httpx.post(
                    self.endpoint,
                    headers={"api-key": self.key},
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {"name": "reply", "strict": True, "schema": schema},
                        },
                    },
                    timeout=8,
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                if attempt:
                    if isinstance(error, httpx.HTTPError):
                        raise
                    raise ValueError("Model request failed") from error
        raise RuntimeError("Unreachable retry state")


class LanguageModel:
    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def _call(self, system: str, user: str, schema: dict[str, object], template: str) -> str:
        user = redact(user)
        logger.info("model_prompt template_id=%s system=%s input=%s", template, system, user)
        output = self.client.complete(system, user, schema)
        logger.info("model_output template_id=%s output=%s", template, redact(output))
        return output

    def extract(self, text: str) -> Command | None:
        if restricted(text):
            return None
        try:
            result = Intent.model_validate_json(
                self._call(
                    "Convert the SMS to a command. Return only the required JSON. "
                    "Do not answer or give farming advice. Use OTHER if uncertain.",
                    text,
                    Intent.model_json_schema(),
                    "T_FALLBACK",
                )
            )
        except ValidationError:
            return None
        if result.confidence < 0.7 or result.intent == "OTHER":
            return None
        argument = ""
        if result.intent == "REG":
            if not result.barangay or not result.water:
                return None
            argument = normalize(result.barangay) + " " + result.water
        elif result.intent == "LAST":
            argument = normalize(result.crop or "")
            if argument not in CROP_ALIASES:
                return None
        elif result.intent == "PRIO":
            if not result.priority:
                return None
            argument = result.priority
        return Command(result.intent, argument)

    def word(self, reply: Reply, slots: list[str]) -> Reply:
        if " ".join(slots) != reply.text or not all(slots):
            return reply
        schema = {
            "type": "object",
            "properties": {"order": {"type": "array", "items": {"type": "integer"}}},
            "required": ["order"],
            "additionalProperties": False,
        }
        try:
            result = json.loads(
                self._call(
                    "Only reorder the supplied template slots. Return their indices as order.",
                    json.dumps(slots),
                    schema,
                    reply.template_id,
                )
            )
            order = result["order"]
            if (
                set(result) != {"order"}
                or not isinstance(order, list)
                or any(type(index) is not int for index in order)
                or sorted(order) != list(range(len(slots)))
            ):
                return reply
            text = " ".join(slots[index] for index in order)
            return Reply(reply.template_id, text) if validate_sms(text) else reply
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            return reply


def create_model(
    settings: Settings, factory: Callable[[Settings], ModelClient] = ChatClient
) -> LanguageModel | None:
    return LanguageModel(factory(settings)) if settings.llm_enabled else None
