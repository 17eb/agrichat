"""English glosses for the fixed Filipino SMS templates, for the public simulator."""

import re

from app.templates import (
    PLAIN_TEMPLATES,
    TEMPLATES,
    WEAK_RETRIEVAL_TEMPLATE,
    WHY_SINGLE_TEMPLATE,
    clean_sms,
)
from engine.reason_codes import REASON_CODES

ENGLISH = {
    "T_REG_OK": (
        "You are registered in Brgy {brgy}, {tubig}. Text LAST and your last crop. Ex: LAST PALAY"
    ),
    "T_LAST_OK": "Saved: {crop} is your last crop. Text PLANT for advice on the next crop.",
    "T_PLANT": (
        "Advice: {crop1}. Water was enough for {a} of the last {n} dry seasons here; "
        "{crop2}, {b} of {n}. Text WHY for the reason."
    ),
    "T_PLANT_BORDER": (
        "Borderline: {crop1} and {crop2} are almost equal on water here. "
        "Consult the municipal agriculture office before planting."
    ),
    "T_WHY": "Reason: {reason1}; {reason2}. Basis: {sources}. Not covered: prices, pests.",
    "T_NO_DATA": (
        "We have no data yet for Brgy {brgy}. First consult the municipal agriculture office."
    ),
    "T_REFER": (
        "We cannot answer that. For fertilizer, chemicals or pests, "
        "consult the municipal agriculture office."
    ),
    "T_HELP": "AgriChat: REG brgy ULAN, LAST PALAY, PLANT, WHY, STOP. Ex: REG SAN JOSE ULAN",
    "T_FALLBACK": "I did not understand. Text HELP for the list of commands.",
    "T_PRIO_OK": "Priority saved: {priority}. Text PLANT for advice.",
    "T_IRRIGATED": (
        "Rain in 30 days: {rain} of 100 (50 is typical); soil wetness: {soil} of 100. "
        "Consult the municipal agriculture office."
    ),
    "T_IRRIGATED_NO_DATA": (
        "There is not yet enough 30-day rain or soil wetness data here. "
        "Consult the municipal agriculture office."
    ),
    "T_STOP_OK": "Your registration and messages were deleted. Text HELP to start again.",
}
ENGLISH_WEAK_RETRIEVAL = (
    "Our references are not enough to answer. Consult the technician at the municipal "
    "agriculture office."
)
ENGLISH_WHY_SINGLE = "Reason: {reason1}. Basis: {sources}. Not covered: prices, pests."
ENGLISH_PLAIN = {
    "T_REG_OK": "Registered: {brgy}, {tubig}. Text LAST and your last crop.",
    "T_PLANT": (
        "Advice: {crop1}. Water was enough for {a} of the last {n} dry seasons. "
        "Text WHY for the reason."
    ),
    "T_WHY": "Reason: {reason1}; {reason2}. Basis: {sources}.",
}
ENGLISH_REASONS = {
    "R_WATER_OK": "water was enough in most past dry seasons",
    "R_WATER_SHORT": "water is often short for this crop",
    "R_LESS_WATER": "it needs less water",
    "R_LEGUME": "it helps the soil after rice",
    "R_SAME_CROP": "the same crop again and again",
    "R_HEAT": "risk of extreme heat at flowering",
    "R_HARVEST_RAIN": "risk of heavy rain at harvest",
}
ENGLISH_WORDS = {
    "palay": "rice",
    "munggo": "mungbean",
    "mais": "corn",
    "ulan": "rain-fed",
    "patubig": "irrigated",
    "bomba": "pump",
}
ENGLISH_WORDS.update({REASON_CODES[code]: text for code, text in ENGLISH_REASONS.items()})

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _pattern(template: str) -> re.Pattern[str]:
    parts = _PLACEHOLDER.split(clean_sms(template))
    seen: set[str] = set()
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            pieces.append(re.escape(part))
        elif part in seen:
            pieces.append(f"(?P={part})")
        else:
            seen.add(part)
            pieces.append(f"(?P<{part}>.+?)")
    return re.compile("^" + "".join(pieces) + "$", re.DOTALL)


def _variants() -> list[tuple[str, re.Pattern[str], str]]:
    pairs: list[tuple[str, str, str]] = [
        (template_id, text, ENGLISH[template_id]) for template_id, text in TEMPLATES.items()
    ]
    pairs.append(("T_REFER", WEAK_RETRIEVAL_TEMPLATE, ENGLISH_WEAK_RETRIEVAL))
    pairs.append(("T_WHY", WHY_SINGLE_TEMPLATE, ENGLISH_WHY_SINGLE))
    pairs.extend(
        (template_id, text, ENGLISH_PLAIN[template_id])
        for template_id, text in PLAIN_TEMPLATES.items()
    )
    return [(template_id, _pattern(text), english) for template_id, text, english in pairs]


_VARIANTS = _variants()


def english_gloss(template_id: str, text: str) -> str | None:
    """Translate a filled template back to English, or None if no template matches."""
    for candidate_id, pattern, english in _VARIANTS:
        if candidate_id != template_id:
            continue
        match = pattern.match(text)
        if match:
            values = {
                key: ENGLISH_WORDS.get(value.lower(), value)
                for key, value in match.groupdict().items()
            }
            return english.format(**values)
    return None
