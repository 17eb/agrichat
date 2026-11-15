import base64
import csv
import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import DATA, connect_db, hash_phone, init_db, seed_sms_data
from app.handler import MessageHandler
from app.main import create_app
from app.parser import ALIASES, Command, normalize, parse
from app.sms import HttpSmsGateway
from app.templates import TEMPLATES, clean_sms, render, validate_sms
from app.webhook import canonical_mobile, verify_token
from engine.reason_codes import REASON_CODES
from kb.retrieve import Hit


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient: str, text: str) -> None:
        assert validate_sms(text)
        self.sent.append((recipient, text))


SmsEnvironment = tuple[TestClient, MessageHandler, FakeGateway, Settings]


def mobile(index: int = 0) -> str:
    return "+63" + "9" + str(index).zfill(9)


def token(secret: str, claims: dict[str, object] | None = None, algorithm: str = "HS256") -> str:
    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    header = encode({"alg": algorithm})
    payload = encode(claims if claims is not None else {"exp": time.time() + 60})
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return (
        "Bearer "
        + header
        + "."
        + payload
        + "."
        + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    )


@pytest.fixture
def environment(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, MessageHandler, FakeGateway, Settings]]:
    settings = Settings(
        db_path=str(tmp_path / "sms.sqlite3"),
        webhook_secret=hashlib.sha256(b"webhook-fixture-material").hexdigest(),
        phone_hash_secret=hashlib.sha256(b"hash-fixture-material").hexdigest(),
    )
    gateway = FakeGateway()

    class Retrieval:
        def search(self, question: str, crop: str) -> list[Hit]:
            return [Hit("approved", "PinoyRice", crop, "water", "Approved passage", 0.9)]

    application = create_app(settings, gateway, retriever=Retrieval())
    with TestClient(application) as client:
        handler = application.state.message_handler
        handler.today = lambda: date(2026, 11, 15)
        yield client, handler, gateway, settings


def event(message_id: str, sender: str | None = None, content: str = "HELP") -> dict[str, object]:
    return {
        "id": "delivery-" + message_id,
        "type": "message.phone.received",
        "data": {"contact": sender or mobile(), "content": content, "message_id": message_id},
    }


@pytest.mark.parametrize("alias,intent", ALIASES.items())
def test_parser_commands_aliases(alias: str, intent: str) -> None:
    assert parse(f"  {alias.lower()}!  ") == Command(intent)


def test_parser_normalization_and_first_word() -> None:
    assert normalize(" \t Rehistro:  quiling\nNORTE, ulan!! ") == "REHISTRO QUILING NORTE ULAN"
    assert parse(" LAST, palay! ") == Command("LAST", "PALAY")
    assert parse("LAST,PALAY") == Command("LAST", "PALAY")
    assert parse("REG BATAC,ULAN") == Command("REG", "BATAC ULAN")
    assert parse("please HELP") is None
    assert parse("planting") is None
    assert parse("  ") is None


@pytest.mark.parametrize("command", ["REG BATAC ULAN", "REHISTRO QUILING NORTE ULAN"])
def test_registration_and_update(environment: SmsEnvironment, command: str) -> None:
    _, handler, gateway, settings = environment
    assert handler.handle(mobile(), command).template_id == "T_REG_OK"
    assert handler.handle(mobile(), "REG BAAY BOMBA").template_id == "T_REG_OK"
    with connect_db(settings.db_path) as connection:
        profile = connection.execute("SELECT * FROM farmers").fetchone()
        assert profile["phone_hash"] == hash_phone(mobile(), settings)
        assert profile["barangay_code"] == "BATAC"
        assert profile["water_source"] == "BOMBA"
        assert connection.execute("SELECT count(*) FROM farmers").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM events WHERE type = 'registered'").fetchone()[
                0
            ]
            == 2
        )
    assert len(gateway.sent) == 2


@pytest.mark.parametrize(
    "command", ["LAST PALAY", "HULI RICE", "LAST MUNGGO", "LAST SOYA", "LAST MAIS"]
)
def test_last_crop(environment: SmsEnvironment, command: str) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    assert handler.handle(mobile(), command).template_id == "T_LAST_OK"
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT last_crop FROM farmers").fetchone()[0] in {
            "rice",
            "mungbean",
            "soybean",
            "corn",
        }


@pytest.mark.parametrize("command,priority", [("PRIO TUBIG", "TUBIG"), ("UNA KITA", "KITA")])
def test_priority(environment: SmsEnvironment, command: str, priority: str) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    assert handler.handle(mobile(), command).template_id == "T_PRIO_OK"
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT priority FROM farmers").fetchone()[0] == priority


def test_plant_why_and_session_memory(environment: SmsEnvironment) -> None:
    _, handler, gateway, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    handler.handle(mobile(), "LAST PALAY")
    plant = handler.handle(mobile(), "TANIM")
    assert plant.template_id in {"T_PLANT", "T_PLANT_BORDER"}
    assert "munggo" in plant.text
    why = handler.handle(mobile(), "BAKIT")
    assert why.template_id == "T_WHY"
    assert "sapat ang tubig sa karamihan ng nakaraang tag-araw" in why.text
    assert "tumutulong ito sa lupa pagkatapos ng palay" in why.text
    assert "PinoyRice" in why.text
    with connect_db(settings.db_path) as connection:
        rows = connection.execute("SELECT * FROM messages").fetchall()
        assert len(rows) == 3
        assert [row["intent"] for row in rows] == ["PLANT", "WHY", "WHY"]
        assert all(row["phone_hash"] == hash_phone(mobile(), settings) for row in rows)
        assert (
            connection.execute(
                "SELECT count(*) FROM events WHERE type = 'recommendation_sent'"
            ).fetchone()[0]
            == 1
        )
    assert all(validate_sms(text) for _, text in gateway.sent)
    handler.handle(mobile(), "HELP")
    assert handler.handle(mobile(), "WHY").template_id == "T_FALLBACK"


@pytest.mark.parametrize("water", ["BOMBA", "PATUBIG"])
def test_irrigated_referral(environment: SmsEnvironment, water: str) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC " + water)
    with connect_db(settings.db_path) as connection:
        connection.execute("UPDATE indicators SET rain30_pct = 48.9, soilwet_pct = 17.8")
    reply = handler.handle(mobile(), "PLANT")
    assert reply.template_id == "T_IRRIGATED"
    assert "Ulan sa 30 araw: 49 sa 100 (50 ang karaniwan)" in reply.text
    assert "basa ng lupa: 18 sa 100" in reply.text
    assert reply.text.endswith("Kumonsulta sa agri office ng munisipyo.")
    assert "pataba" not in reply.text
    assert validate_sms(reply.text)


def test_missing_indicators_no_guess(environment: SmsEnvironment) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    with connect_db(settings.db_path) as connection:
        connection.execute("DELETE FROM indicators")
    assert handler.handle(mobile(), "PLANT").template_id == "T_NO_DATA"


@pytest.mark.parametrize("command", ["HELP", "TULONG"])
def test_help(environment: SmsEnvironment, command: str) -> None:
    assert environment[1].handle(mobile(), command).text == TEMPLATES["T_HELP"]


@pytest.mark.parametrize("command", ["STOP", "HINTO"])
def test_stop_deletes_all_history(environment: SmsEnvironment, command: str) -> None:
    _, handler, _, settings = environment
    with connect_db(settings.db_path) as connection:
        connection.execute(
            "INSERT INTO processed_events (event_id, phone_hash) VALUES (?, ?)",
            ("stop-linked-message", hash_phone(mobile(), settings)),
        )
    for text in ("REG BATAC ULAN", "LAST PALAY", "PLANT", command):
        handler.handle(mobile(), text)
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM farmers").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        row = connection.execute(
            "SELECT phone_hash FROM processed_events WHERE event_id = ?", ("stop-linked-message",)
        ).fetchone()
        assert row is not None and row[0] is None
        assert (
            connection.execute("SELECT type FROM events ORDER BY id DESC").fetchone()[0]
            == "stop_received"
        )
    handler.handle(mobile(), "nonsense")
    handler.handle(mobile(), command)
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["nonsense", "REG", "REG NOT A BARANGAY ULAN"])
def test_disabled_unknown_and_invalid_commands(environment: SmsEnvironment, text: str) -> None:
    _, handler, _, settings = environment
    assert not settings.llm_enabled
    assert handler.handle(mobile(), text).template_id == "T_FALLBACK"
    with connect_db(settings.db_path) as connection:
        assert (
            connection.execute("SELECT type FROM events ORDER BY id DESC").fetchone()[0]
            == "fallback_used"
        )


@pytest.mark.parametrize("command", ["LAST PALAY", "PRIO TUBIG", "PLANT", "WHY"])
def test_unregistered_guidance(environment: SmsEnvironment, command: str) -> None:
    assert environment[1].handle(mobile(), command).template_id == "T_HELP"


def test_refusal_and_model_failure_events(environment: SmsEnvironment) -> None:
    _, handler, gateway, settings = environment
    assert handler.handle(mobile(), "anong gamot sa peste").template_id == "T_REFER"
    enabled = Settings(
        db_path=settings.db_path, phone_hash_secret=settings.phone_hash_secret, llm_enabled=True
    )
    unavailable = MessageHandler(enabled, gateway)
    assert unavailable.handle(mobile(), "unrecognized question").template_id == "T_FALLBACK"
    with connect_db(settings.db_path) as connection:
        types = {row[0] for row in connection.execute("SELECT type FROM events")}
        assert {"refusal", "model_call_failed", "fallback_used"} <= types


def test_extractor_only_runs_after_keyword_failure(environment: SmsEnvironment) -> None:
    _, _, gateway, settings = environment

    class Extractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, text: str) -> Command:
            self.calls += 1
            return Command("HELP")

    extractor = Extractor()
    enabled = Settings(
        db_path=settings.db_path, phone_hash_secret=settings.phone_hash_secret, llm_enabled=True
    )
    handler = MessageHandler(enabled, gateway, extractor)
    handler.handle(mobile(), "HELP")
    assert extractor.calls == 0
    assert handler.handle(mobile(), "what can I text").template_id == "T_HELP"
    assert extractor.calls == 1


def test_webhook_authentication_failure(environment: SmsEnvironment) -> None:
    client, _, gateway, settings = environment
    for authorization in (
        "",
        "Bearer invalid",
        token("wrong"),
        token(settings.webhook_secret, {"exp": 1}),
    ):
        assert (
            client.post(
                "/webhook/httpsms", json=event("auth"), headers={"Authorization": authorization}
            ).status_code
            == 401
        )
    assert not gateway.sent
    with connect_db(settings.db_path) as connection:
        assert connection.execute("SELECT count(*) FROM processed_events").fetchone()[0] == 0


def test_webhook_deduplicates_message_id_not_delivery_id(environment: SmsEnvironment) -> None:
    client, _, gateway, settings = environment
    payload = event("same-message")
    headers = {"Authorization": token(settings.webhook_secret)}
    assert client.post("/webhook/httpsms", json=payload, headers=headers).status_code == 200
    payload["id"] = "another-delivery"
    assert client.post("/webhook/httpsms", json=payload, headers=headers).status_code == 200
    assert len(gateway.sent) == 1
    with connect_db(settings.db_path) as connection:
        assert (
            connection.execute("SELECT type FROM events ORDER BY id DESC").fetchone()[0]
            == "duplicate_dropped"
        )


@pytest.mark.parametrize("sender", ["PROMO", "1234", "+1" + "0" * 10, "02" + "0" * 9])
def test_non_mobile_senders_ignored(environment: SmsEnvironment, sender: str) -> None:
    client, _, gateway, settings = environment
    assert (
        client.post(
            "/webhook/httpsms",
            json=event("ignored", sender),
            headers={"Authorization": token(settings.webhook_secret)},
        ).status_code
        == 200
    )
    assert not gateway.sent


def test_webhook_only_handles_inbound_event(environment: SmsEnvironment) -> None:
    client, _, gateway, settings = environment
    payload = {"type": "message.phone.sent", "data": {}}
    assert (
        client.post(
            "/webhook/httpsms",
            json=payload,
            headers={"Authorization": token(settings.webhook_secret)},
        ).status_code
        == 200
    )
    assert not gateway.sent


def test_webhook_rate_limit_is_per_number_durable_and_expires(environment: SmsEnvironment) -> None:
    client, _, gateway, settings = environment
    headers = {"Authorization": token(settings.webhook_secret)}
    for index in range(11):
        assert (
            client.post("/webhook/httpsms", json=event(str(index)), headers=headers).status_code
            == 200
        )
    assert len(gateway.sent) == 10
    with connect_db(settings.db_path) as connection:
        assert (
            connection.execute("SELECT type FROM events ORDER BY id DESC").fetchone()[0]
            == "rate_limit_hit"
        )
    with TestClient(create_app(settings, gateway)) as restarted:
        restarted.post("/webhook/httpsms", json=event("restart"), headers=headers)
    assert len(gateway.sent) == 10
    client.post("/webhook/httpsms", json=event("other-number", mobile(1)), headers=headers)
    assert len(gateway.sent) == 11
    with connect_db(settings.db_path) as connection:
        connection.execute("UPDATE processed_events SET received_at = datetime('now', '-2 hours')")
    client.post("/webhook/httpsms", json=event("new-hour"), headers=headers)
    assert len(gateway.sent) == 12


def test_webhook_queues_background_task(
    environment: SmsEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, gateway, settings = environment
    queued = []

    def capture(self: BackgroundTasks, func, *args, **kwargs) -> None:
        queued.append((func, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", capture)
    start = time.monotonic()
    assert (
        client.post(
            "/webhook/httpsms",
            json=event("background"),
            headers={"Authorization": token(settings.webhook_secret)},
        ).status_code
        == 200
    )
    assert time.monotonic() - start < 1
    assert len(queued) == 1
    assert not gateway.sent


def test_mobile_canonicalization() -> None:
    assert canonical_mobile(mobile()) == mobile()
    assert canonical_mobile("0" + mobile()[3:]) == mobile()
    assert canonical_mobile(mobile()[1:]) == mobile()
    assert canonical_mobile("9" * 11) is None


@pytest.mark.parametrize("authorization", ["Basic x", "Bearer ...", "Bearer a.b.c", "Bearer [].."])
def test_malformed_tokens_rejected(authorization: str) -> None:
    assert not verify_token(authorization, "fixture")


def test_token_algorithm_and_time_guards() -> None:
    assert verify_token(token("fixture"), "fixture")
    assert not verify_token(token("fixture", algorithm="none"), "fixture")
    assert not verify_token(token("fixture", {"nbf": time.time() + 60}), "fixture")
    assert not verify_token(token("fixture"), "")


def test_templates_verbatim_against_spec() -> None:
    spec = (DATA.parent / "docs/Technical_spec.md").read_text()
    rows = [line.split(" | ") for line in spec.splitlines() if line.startswith("| `T_")]
    assert len(rows) == 9
    for row in rows:
        assert TEMPLATES[row[0].removeprefix("| `").removesuffix("`")] == row[1].removesuffix(" |")


def test_all_templates_with_longest_names() -> None:
    with (DATA / "barangays/barangays.csv").open() as handle:
        barangays = list(csv.DictReader(handle))
    longest_barangay = max(
        [value for row in barangays for value in [row["name"], *row["aliases"].split("|")]], key=len
    )
    with (DATA / "crops/crops_engine.csv").open() as handle:
        longest_crop = max((row["crop"] for row in csv.DictReader(handle)), key=len)
    longest_reasons = sorted(REASON_CODES.values(), key=len, reverse=True)[:2]
    values = dict(
        brgy=longest_barangay,
        tubig="PATUBIG",
        crop=longest_crop,
        crop1=longest_crop,
        crop2=longest_crop,
        a=45,
        b=45,
        n=45,
        reason1=longest_reasons[0],
        reason2=longest_reasons[1],
        rain=100,
        soil=100,
        sources="FAO-56",
        priority="TUBIG",
    )
    for template_id in TEMPLATES:
        reply = render(template_id, **values)
        assert validate_sms(reply.text)
        assert len(reply.text) <= 150
        assert reply.template_id == template_id


def test_sms_replacements_validation_and_plain_fallback() -> None:
    assert (
        clean_sms("₱50 ‘quoted’ “words” - \u2013 \u2014 😀 **bold** `text` #tag")
        == "P50 quoted words -    bold text tag"
    )
    assert validate_sms("a" * 150)
    assert not validate_sms("a" * 151)
    assert not validate_sms("中文")
    assert not validate_sms("😀")
    assert validate_sms("^" * 75)
    assert not validate_sms("^" * 76)
    assert not validate_sms("a" * 149 + "€")
    assert validate_sms("a" * 148 + "€")
    assert not validate_sms("a" * 140 + "€" * 10)
    reply = render("T_REG_OK", brgy="X" * 80, tubig="ULAN")
    assert reply.template_id == "T_REG_OK"
    assert reply.text.startswith("Rehistrado:")
    assert render("T_REG_OK", brgy="X" * 200, tubig="ULAN").template_id == "T_FALLBACK"
    assert render("T_REG_OK", brgy="中文", tubig="ULAN").template_id == "T_FALLBACK"


def test_gateway_contract_and_send_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def post(url: str, **kwargs) -> httpx.Response:
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    settings = Settings(
        httpsms_api_key=hashlib.sha256(b"gateway-fixture").hexdigest(),
        httpsms_from="synthetic-gateway",
    )
    gateway = HttpSmsGateway(settings)
    gateway.send("synthetic-recipient", "₱20 😀")
    assert calls[0][0] == "https://api.httpsms.com/v1/messages/send"
    assert calls[0][1]["headers"] == {"x-api-key": settings.httpsms_api_key}
    assert calls[0][1]["json"] == {
        "from": "synthetic-gateway",
        "to": "synthetic-recipient",
        "content": "P20 ",
    }
    gateway.send("synthetic-recipient", "a" * 151)
    assert calls[1][1]["json"]["content"] == TEMPLATES["T_FALLBACK"]


def test_schema_migrates_existing_message_storage(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with connect_db(path) as connection:
        connection.execute(
            "CREATE TABLE processed_events (event_id TEXT PRIMARY KEY, received_at TEXT)"
        )
        connection.execute("""CREATE TABLE messages (
            id INTEGER PRIMARY KEY, phone_hash TEXT, direction TEXT, text TEXT, intent TEXT,
            template_id TEXT, created_at TEXT)""")
    init_db(path)
    with connect_db(path) as connection:
        assert "context" in {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        assert "phone_hash" in {
            row[1] for row in connection.execute("PRAGMA table_info(processed_events)")
        }


def test_gateway_failure_is_recorded_without_claiming_recommendation_sent(
    environment: SmsEnvironment,
) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")

    class FailingGateway:
        def send(self, recipient: str, text: str) -> None:
            raise httpx.ConnectError("Synthetic gateway failure")

    handler.gateway = FailingGateway()
    handler.handle(mobile(), "PLANT")
    with connect_db(settings.db_path) as connection:
        assert (
            connection.execute("SELECT type FROM events ORDER BY id DESC").fetchone()[0]
            == "send_failed"
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM events WHERE type = 'recommendation_sent'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM messages WHERE template_id IN ('T_PLANT', 'T_PLANT_BORDER')"
            ).fetchone()[0]
            == 0
        )


def test_missing_crop_source_refers_without_inventing_citation(environment: SmsEnvironment) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    with connect_db(settings.db_path) as connection:
        connection.execute("DELETE FROM crops")
    assert handler.handle(mobile(), "PLANT").template_id == "T_REFER"


def test_disabled_extractor_is_never_called(environment: SmsEnvironment) -> None:
    _, handler, _, _ = environment

    class UnusedExtractor:
        def extract(self, text: str) -> Command:
            raise AssertionError("Disabled extraction must not run")

    handler.extractor = UnusedExtractor()
    assert handler.handle(mobile(), "unrecognized input").template_id == "T_FALLBACK"


def test_webhook_parallel_admission_is_atomic(environment: SmsEnvironment) -> None:
    from concurrent.futures import ThreadPoolExecutor

    client, _, gateway, settings = environment
    headers = {"Authorization": token(settings.webhook_secret)}

    def send(index: int) -> int:
        return client.post(
            "/webhook/httpsms", json=event("parallel-" + str(index)), headers=headers
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(send, range(12))) == [200] * 12
    assert len(gateway.sent) == 10
    with connect_db(settings.db_path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM events WHERE type = 'rate_limit_hit'"
            ).fetchone()[0]
            == 2
        )


def test_why_single_reason_preserves_scope(environment: SmsEnvironment) -> None:
    _, handler, _, _ = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    handler.handle(mobile(), "PLANT")
    reply = handler.handle(mobile(), "WHY")
    assert reply.template_id == "T_WHY"
    assert reply.text.count(REASON_CODES["R_WATER_OK"]) == 1
    assert "Di sakop: presyo, peste." in reply.text
    assert validate_sms(reply.text)


def test_why_uses_first_two_distinct_reasons(environment: SmsEnvironment) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    handler.handle(mobile(), "PLANT")
    with connect_db(settings.db_path) as connection:
        connection.execute(
            "UPDATE messages SET context = ? WHERE template_id IN ('T_PLANT', 'T_PLANT_BORDER')",
            (
                json.dumps(
                    {
                        "reasons": ["R_WATER_OK", "R_WATER_OK", "R_LESS_WATER", "R_LEGUME"],
                        "source": "FAO-56",
                        "crop": "rice",
                    }
                ),
            ),
        )
    reply = handler.handle(mobile(), "WHY")
    assert reply.text.count(REASON_CODES["R_WATER_OK"]) == 1
    assert REASON_CODES["R_LESS_WATER"] in reply.text
    assert REASON_CODES["R_LEGUME"] not in reply.text


@pytest.mark.parametrize("body", [b"{broken", b"", b"[]", b'"text"', b"{}"])
def test_unauthenticated_malformed_body_is_unauthorized(
    environment: SmsEnvironment,
    body: bytes,
) -> None:
    client, _, gateway, _ = environment
    response = client.post(
        "/webhook/httpsms",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
    assert not gateway.sent


def test_authenticated_malformed_body_is_rejected(environment: SmsEnvironment) -> None:
    client, _, _, settings = environment
    response = client.post(
        "/webhook/httpsms",
        content="{broken",
        headers={
            "Content-Type": "application/json",
            "Authorization": token(settings.webhook_secret),
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("source", ["unrecognized " * 30, "FAO-560 unknown source"])
def test_unrecognized_crop_source_refers(environment: SmsEnvironment, source: str) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC ULAN")
    with connect_db(settings.db_path) as connection:
        connection.execute("UPDATE crops SET source = ?", (source,))
    assert handler.handle(mobile(), "PLANT").template_id == "T_REFER"


def test_expired_rate_records_lose_phone_link_but_keep_dedup_id(
    environment: SmsEnvironment,
) -> None:
    client, _, _, settings = environment
    with connect_db(settings.db_path) as connection:
        connection.execute(
            """INSERT INTO processed_events (event_id, phone_hash, received_at)
            VALUES (?, ?, datetime('now', '-2 hours'))""",
            ("expired-link", hash_phone(mobile(1), settings)),
        )
    client.post(
        "/webhook/httpsms",
        json=event("trigger-cleanup"),
        headers={"Authorization": token(settings.webhook_secret)},
    )
    with connect_db(settings.db_path) as connection:
        row = connection.execute(
            "SELECT phone_hash FROM processed_events WHERE event_id = ?", ("expired-link",)
        ).fetchone()
        assert row is not None and row[0] is None


def test_seed_uses_named_columns_and_only_engine_crops(tmp_path: Path) -> None:
    path = str(tmp_path / "catalog.sqlite3")
    init_db(path)
    with connect_db(path) as connection:
        connection.execute("ALTER TABLE crops ADD COLUMN review_note TEXT")
    seed_sms_data(path)
    seed_sms_data(path)
    with connect_db(path) as connection:
        rows = connection.execute("SELECT crop, source FROM crops").fetchall()
        assert {row["crop"] for row in rows} == {"rice", "mungbean", "soybean"}
        assert all(row["source"].startswith("FAO-56") for row in rows)


@pytest.mark.parametrize("missing", ["rain", "soil", "all"])
def test_irrigated_missing_indicators_use_separate_sentence(
    environment: SmsEnvironment,
    missing: str,
) -> None:
    _, handler, _, settings = environment
    handler.handle(mobile(), "REG BATAC BOMBA")
    with connect_db(settings.db_path) as connection:
        if missing == "rain":
            connection.execute("UPDATE indicators SET rain30_pct = NULL")
        elif missing == "soil":
            connection.execute("UPDATE indicators SET soilwet_pct = NULL")
        else:
            connection.execute("DELETE FROM indicators")
    reply = handler.handle(mobile(), "PLANT")
    assert reply.template_id == "T_IRRIGATED_NO_DATA"
    assert reply.text.startswith("Kulang pa ang datos")
    assert "sa 100" not in reply.text
    assert reply.text.endswith("Kumonsulta sa agri office ng munisipyo.")
    assert validate_sms(reply.text)


def test_sqlite_admission_runs_off_event_loop(
    environment: SmsEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from app import webhook

    client, _, gateway, settings = environment
    threads: dict[str, int] = {}
    verify = webhook.verify_token
    admit = webhook.admit_message

    def capture_verification(authorization: str, secret: str) -> bool:
        threads["request"] = threading.get_ident()
        return verify(authorization, secret)

    def capture_admission(config: Settings, message_id: str, sender: str | None) -> bool:
        threads["admission"] = threading.get_ident()
        return admit(config, message_id, sender)

    monkeypatch.setattr(webhook, "verify_token", capture_verification)
    monkeypatch.setattr(webhook, "admit_message", capture_admission)
    response = client.post(
        "/webhook/httpsms",
        json=event("off-loop"),
        headers={"Authorization": token(settings.webhook_secret)},
    )
    assert response.status_code == 200
    assert threads["request"] != threads["admission"]
    assert len(gateway.sent) == 1
