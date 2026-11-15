"""Deterministic SMS normalization and command matching."""

import unicodedata
from dataclasses import dataclass

ALIASES = {
    "REG": "REG",
    "REHISTRO": "REG",
    "LAST": "LAST",
    "HULI": "LAST",
    "PRIO": "PRIO",
    "UNA": "PRIO",
    "PLANT": "PLANT",
    "TANIM": "PLANT",
    "WHY": "WHY",
    "BAKIT": "WHY",
    "HELP": "HELP",
    "TULONG": "HELP",
    "STOP": "STOP",
    "HINTO": "STOP",
}
CROP_ALIASES = {
    "PALAY": "rice",
    "RICE": "rice",
    "MUNGGO": "mungbean",
    "MONGGO": "mungbean",
    "MUNGBEAN": "mungbean",
    "MAIS": "corn",
    "CORN": "corn",
    "SOYBEAN": "soybean",
    "SOYA": "soybean",
}
CROP_NAMES = {"rice": "palay", "mungbean": "munggo", "corn": "mais", "soybean": "soybean"}


@dataclass(frozen=True)
class Command:
    intent: str
    argument: str = ""


def normalize(text: str) -> str:
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char for char in text.upper()
    )
    return " ".join(text.split())


def parse(text: str) -> Command | None:
    words = normalize(text).split(maxsplit=1)
    if not words or words[0] not in ALIASES:
        return None
    return Command(ALIASES[words[0]], words[1] if len(words) == 2 else "")
