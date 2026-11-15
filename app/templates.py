"""Traceable Filipino SMS templates and single-message validation."""

import unicodedata
from dataclasses import dataclass

TEMPLATES = {
    "T_REG_OK": (
        "Rehistrado ka sa Brgy {brgy}, {tubig}. I-text ang LAST at huling tanim mo. Hal: LAST PALAY"
    ),
    "T_LAST_OK": (
        "Naitala: {crop} ang huling tanim. I-text ang PLANT para sa payo sa susunod na tanim."
    ),
    "T_PLANT": (
        "Payo: {crop1}. Sapat ang tubig sa {a} sa {n} nakaraang tag-araw dito; "
        "{crop2}, {b} sa {n}. I-text ang WHY para sa dahilan."
    ),
    "T_PLANT_BORDER": (
        "Alanganin: halos pantay ang {crop1} at {crop2} sa tubig dito. "
        "Kumonsulta sa agri office ng munisipyo bago magtanim."
    ),
    "T_WHY": "Dahilan: {reason1}; {reason2}. Batayan: {sources}. Di sakop: presyo, peste.",
    "T_NO_DATA": (
        "Wala pa kaming datos para sa Brgy {brgy}. Kumonsulta muna sa agri office ng munisipyo."
    ),
    "T_REFER": (
        "Hindi namin masasagot iyan. Para sa pataba, gamot o peste, kumonsulta "
        "sa agri office ng munisipyo."
    ),
    "T_HELP": "AgriChat: REG brgy ULAN, LAST PALAY, PLANT, WHY, STOP. Hal: REG SAN JOSE ULAN",
    "T_FALLBACK": "Di ko naintindihan. I-text ang HELP para sa listahan ng utos.",
    "T_PRIO_OK": "Naitala ang prayoridad: {priority}. I-text ang PLANT para sa payo.",
    "T_IRRIGATED": (
        "Ulan sa 30 araw: {rain} sa 100 (50 ang karaniwan); basa ng lupa: {soil} sa 100. "
        "Kumonsulta sa agri office ng munisipyo."
    ),
    "T_IRRIGATED_NO_DATA": (
        "Kulang pa ang datos ng ulan sa 30 araw o basa ng lupa dito. "
        "Kumonsulta sa agri office ng munisipyo."
    ),
    "T_STOP_OK": (
        "Binura na ang iyong rehistro at mga mensahe. I-text ang HELP para magsimula muli."
    ),
}
WEAK_RETRIEVAL_TEMPLATE = (
    "Kulang ang batayan sa aming sanggunian. Kumonsulta sa technician sa agri office ng munisipyo."
)
WHY_SINGLE_TEMPLATE = "Dahilan: {reason1}. Batayan: {sources}. Di sakop: presyo, peste."
PLAIN_TEMPLATES = {
    "T_REG_OK": "Rehistrado: {brgy}, {tubig}. I-text ang LAST at huling tanim.",
    "T_PLANT": (
        "Payo: {crop1}. Sapat ang tubig sa {a} sa {n} nakaraang tag-araw. "
        "I-text ang WHY para sa dahilan."
    ),
    "T_WHY": "Dahilan: {reason1}; {reason2}. Batayan: {sources}.",
}
GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./"
    "0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXTENDED = set("\f^{}\\[~]|€")
SMS_LIMIT = 150


@dataclass(frozen=True)
class Reply:
    template_id: str
    text: str


def clean_sms(text: str) -> str:
    text = text.replace("₱", "P")
    stripped = "\u2018\u2019\u201c\u201d\u2013\u2014*_`#~"
    return "".join(
        char
        for char in text
        if char not in stripped
        and not (unicodedata.category(char) in {"So", "Sk"} and char not in GSM_BASIC)
        and char not in {"\ufe0f", "\u200d"}
    )


def sms_length(text: str) -> int:
    """Length in GSM-7 septets; extended characters count twice."""
    return sum(2 if char in GSM_EXTENDED else 1 for char in text)


def validate_sms(text: str) -> bool:
    return (
        bool(text)
        and sms_length(text) <= SMS_LIMIT
        and all(char in GSM_BASIC or char in GSM_EXTENDED for char in text)
    )


def render(template_id: str, **values: object) -> Reply:
    template = TEMPLATES[template_id]
    if template_id == "T_WHY" and not values.get("reason2"):
        template = WHY_SINGLE_TEMPLATE
    if template_id == "T_REFER" and values.get("weak_retrieval"):
        template = WEAK_RETRIEVAL_TEMPLATE
    text = clean_sms(template.format(**values))
    if validate_sms(text):
        return Reply(template_id, text)
    plain = clean_sms(PLAIN_TEMPLATES.get(template_id, TEMPLATES["T_FALLBACK"]).format(**values))
    if validate_sms(plain):
        return Reply(template_id if template_id in PLAIN_TEMPLATES else "T_FALLBACK", plain)
    return Reply("T_FALLBACK", TEMPLATES["T_FALLBACK"])
