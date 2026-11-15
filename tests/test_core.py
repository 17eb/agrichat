import csv
import hashlib
import hmac
import sqlite3
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_DB_PATH, Settings
from app.db import connect_db, hash_phone, init_db, record_event
from app.main import create_app
from engine import params

ROOT = Path(__file__).resolve().parent.parent


def test_configuration_reads_every_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert {item.name.upper() for item in fields(Settings)} == {
        "HTTPSMS_API_KEY",
        "HTTPSMS_FROM",
        "WEBHOOK_SECRET",
        "PHONE_HASH_SECRET",
        "LLM_ENDPOINT",
        "LLM_KEY",
        "LLM_MODEL",
        "LLM_ENABLED",
        "DB_PATH",
        "SEASON_EL_NINO",
        "ADMIN_PASSWORD_HASH",
        "SESSION_SECRET",
    }
    for item in fields(Settings):
        value = "true" if item.type is bool else f"configured-{item.name}"
        monkeypatch.setenv(item.name.upper(), value)
    settings = Settings.from_env()
    for item in fields(settings):
        value = getattr(settings, item.name)
        assert value is True if isinstance(value, bool) else value == f"configured-{item.name}"
    with pytest.raises(FrozenInstanceError):
        settings.db_path = "other"  # type: ignore[misc]


def test_missing_secrets_are_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    for item in fields(Settings):
        monkeypatch.delenv(item.name.upper(), raising=False)
    settings = Settings.from_env()
    assert not settings.llm_enabled
    assert not settings.season_el_nino
    assert settings.db_path == Settings().db_path == DEFAULT_DB_PATH == "data/agrichat.db"
    with pytest.raises(ValueError, match="PHONE_HASH_SECRET"):
        hash_phone("synthetic-subscriber", settings)
    with pytest.raises(ValueError, match="LLM_KEY"):
        settings.require("llm_key")


@pytest.mark.parametrize("name", ["LLM_ENABLED", "SEASON_EL_NINO"])
def test_invalid_boolean_fails(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name, "invalid")
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_hash_is_keyed_sha256() -> None:
    key = hashlib.sha256(b"fixture-key-material").hexdigest()
    settings = Settings(phone_hash_secret=key)
    number = "synthetic-subscriber"
    result = hash_phone(number, settings)
    assert result == hmac.new(key.encode(), number.encode(), hashlib.sha256).hexdigest()
    assert result == hash_phone(number, settings)
    assert result != hash_phone(number + "-other", settings)
    assert result != hash_phone(number, Settings(phone_hash_secret=key[::-1]))
    assert len(result) == 64
    assert key not in repr(settings)


def test_schema_is_idempotent_and_uses_wal(tmp_path: Path) -> None:
    path = tmp_path / "test.sqlite3"
    tables = {
        "farmers",
        "messages",
        "processed_events",
        "indicators",
        "crops",
        "barangays",
        "kb_chunks",
        "events",
    }
    for _ in range(2):
        init_db(path)
        with connect_db(path) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            found = connection.execute("SELECT name FROM sqlite_master WHERE type = ?", ("table",))
            assert {row[0] for row in found} == tables
            record_event(connection, "registered", source="keyword", latency_ms=1)
    with connect_db(path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        columns = connection.execute("PRAGMA table_info(events)")
        assert {row[1] for row in columns} == {
            "id",
            "type",
            "intent",
            "template_id",
            "source",
            "latency_ms",
            "created_at",
        }


def test_event_recording_is_parameterized_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    init_db(path)
    with connect_db(path) as connection:
        event_type = "registered'); DROP TABLE events; --"
        event_id = record_event(
            connection,
            event_type,
            intent="REG",
            template_id="T_REG",
            source="fallback",
            latency_ms=42,
        )
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        assert tuple(row)[1:6] == (event_type, "REG", "T_REG", "fallback", 42)
        assert row["created_at"]
        with pytest.raises(sqlite3.IntegrityError):
            record_event(connection, "invalid", source="other")  # type: ignore[arg-type]
        with pytest.raises(sqlite3.IntegrityError):
            record_event(connection, "invalid", latency_ms=-1)


def test_messages_retain_three_and_delete_with_farmer(tmp_path: Path) -> None:
    phone_hash = hashlib.sha256(b"synthetic-subscriber").hexdigest()
    path = tmp_path / "messages.sqlite3"
    init_db(path)
    with connect_db(path) as connection:
        connection.execute(
            "INSERT INTO farmers (phone_hash, barangay_code, water_source) VALUES (?, ?, ?)",
            (phone_hash, "BATAC", "ULAN"),
        )
        for index in range(5):
            connection.execute(
                "INSERT INTO messages (phone_hash, direction, text) VALUES (?, ?, ?)",
                (phone_hash, "in", str(index)),
            )
        rows = connection.execute("SELECT text FROM messages ORDER BY id").fetchall()
        assert [row[0] for row in rows] == ["2", "3", "4"]
        connection.execute("DELETE FROM farmers WHERE phone_hash = ?", (phone_hash,))
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO messages (phone_hash, direction, text) VALUES (?, ?, ?)",
                ("unhashed-input", "in", "REG"),
            )


def test_healthz_without_integration_secrets(tmp_path: Path) -> None:
    settings = Settings(db_path=str(tmp_path / "app.sqlite3"))
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    assert Path(settings.db_path).is_file()


def test_barangay_data() -> None:
    with (ROOT / "data/barangays/barangays.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    row = rows[0]
    assert row["barangay_code"] == "BATAC"
    assert (float(row["lat"]), float(row["lon"])) == (18.06, 120.56)
    assert 5 <= len(row["aliases"].split("|")) <= 10
    assert row["soil_class"] == ""


def test_reviewer_placeholders_match_spec() -> None:
    assert params.SOWING_WINDOW == ((11, 1), (11, 30))
    assert params.ROOT_ZONE_WATER_CAPACITY_MM == 100.0
    assert params.RICE_EXTRA_ALLOWANCE_MM == 0.0
    assert params.ADEQUACY_THRESHOLD == 0.8
    assert params.KC_END == {"rice": 0.75, "mungbean": 0.475, "soybean": 0.5}
    assert params.SCORING_WEIGHTS == {
        "water_reliability": 50,
        "rotation_benefit": 20,
        "timing_risk": 20,
        "farmer_priority": 10,
    }
    assert params.HEAT_THRESHOLD_C == 35
    assert params.HARVEST_RAIN_THRESHOLD_MM == 50
