"""SQLite schema and small persistence helpers."""

import csv
import hashlib
import hmac
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from app.config import Settings
from engine import params

DATA = Path(__file__).resolve().parent.parent / "data"

EventSource = Literal["keyword", "model", "fallback"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    phone_hash TEXT PRIMARY KEY NOT NULL CHECK(length(phone_hash) = 64
        AND phone_hash NOT GLOB '*[^0-9a-f]*'),
    barangay_code TEXT NOT NULL,
    water_source TEXT NOT NULL,
    last_crop TEXT,
    priority TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    phone_hash TEXT NOT NULL CHECK(length(phone_hash) = 64
        AND phone_hash NOT GLOB '*[^0-9a-f]*'),
    direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
    text TEXT NOT NULL,
    intent TEXT,
    template_id TEXT,
    context TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS messages_phone ON messages(phone_hash, id);
CREATE TRIGGER IF NOT EXISTS messages_keep_three AFTER INSERT ON messages
BEGIN
    DELETE FROM messages WHERE phone_hash = NEW.phone_hash AND id NOT IN (
        SELECT id FROM messages WHERE phone_hash = NEW.phone_hash ORDER BY id DESC LIMIT 3
    );
END;
CREATE TRIGGER IF NOT EXISTS farmers_delete_messages AFTER DELETE ON farmers
BEGIN
    DELETE FROM messages WHERE phone_hash = OLD.phone_hash;
END;
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY NOT NULL,
    phone_hash TEXT,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS indicators (
    barangay_code TEXT NOT NULL,
    crop TEXT NOT NULL,
    sow_window TEXT NOT NULL,
    n_years INTEGER NOT NULL,
    n_adequate INTEGER NOT NULL,
    n_elnino INTEGER NOT NULL,
    n_adequate_elnino INTEGER NOT NULL,
    median_ratio REAL NOT NULL,
    heat_freq REAL NOT NULL,
    harvest_rain_freq REAL NOT NULL,
    rain30_pct REAL,
    soilwet_pct REAL,
    soilwet_source TEXT CHECK(soilwet_source IN ('smap', 'power')),
    soilwet_date TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (barangay_code, crop, sow_window)
);
CREATE TABLE IF NOT EXISTS crops (
    crop TEXT PRIMARY KEY NOT NULL,
    kc_ini REAL NOT NULL,
    kc_mid REAL NOT NULL,
    kc_end REAL NOT NULL,
    days INTEGER NOT NULL,
    is_legume INTEGER NOT NULL CHECK(is_legume IN (0, 1)),
    income_flag REAL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS barangays (
    barangay_code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    soil_class TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id TEXT PRIMARY KEY NOT NULL,
    doc_id TEXT NOT NULL,
    source_tag TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    url TEXT NOT NULL,
    crop TEXT,
    topic TEXT,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    intent TEXT,
    template_id TEXT,
    source TEXT CHECK(source IN ('keyword', 'model', 'fallback')),
    latency_ms INTEGER CHECK(latency_ms >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: str | Path) -> None:
    """Enable WAL and create missing schema objects at application startup."""
    with connect_db(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        for table, column, query in (
            ("messages", "context", "ALTER TABLE messages ADD COLUMN context TEXT"),
            (
                "processed_events",
                "phone_hash",
                "ALTER TABLE processed_events ADD COLUMN phone_hash TEXT",
            ),
        ):
            columns = connection.execute("SELECT name FROM pragma_table_info(?)", (table,))
            if column not in {row[0] for row in columns}:
                connection.execute(query)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS processed_phone "
            "ON processed_events(phone_hash, received_at)"
        )


@contextmanager
def connect_db(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open and close a connection; commit or roll back its writes."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def seed_sms_data(db_path: str) -> None:
    """Import named catalog fields, limited to the configured engine crops."""
    with connect_db(db_path) as connection:
        for path, columns, query in (
            (
                DATA / "barangays/barangays.csv",
                ("barangay_code", "name", "aliases", "lat", "lon", "soil_class"),
                """INSERT INTO barangays
                (barangay_code, name, aliases, lat, lon, soil_class)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(barangay_code) DO NOTHING""",
            ),
            (
                DATA / "crops/crops_engine.csv",
                (
                    "crop",
                    "kc_ini",
                    "kc_mid",
                    "kc_end",
                    "days",
                    "is_legume",
                    "income_flag",
                    "source",
                ),
                """INSERT INTO crops
                (crop, kc_ini, kc_mid, kc_end, days, is_legume, income_flag, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(crop) DO NOTHING""",
            ),
            (
                DATA / "indicators.csv",
                (
                    "barangay_code",
                    "crop",
                    "sow_window",
                    "n_years",
                    "n_adequate",
                    "n_elnino",
                    "n_adequate_elnino",
                    "median_ratio",
                    "heat_freq",
                    "harvest_rain_freq",
                    "rain30_pct",
                    "soilwet_pct",
                    "soilwet_source",
                    "soilwet_date",
                    "updated_at",
                ),
                """INSERT INTO indicators
                (barangay_code, crop, sow_window, n_years, n_adequate, n_elnino,
                 n_adequate_elnino, median_ratio, heat_freq, harvest_rain_freq,
                 rain30_pct, soilwet_pct, soilwet_source, soilwet_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(barangay_code, crop, sow_window) DO NOTHING""",
            ),
        ):
            with path.open(newline="") as handle:
                rows = csv.DictReader(handle)
                nullable = {
                    "income_flag",
                    "soilwet_pct",
                    "rain30_pct",
                    "soilwet_date",
                    "soilwet_source",
                }
                connection.executemany(
                    query,
                    [
                        tuple(
                            None if key in nullable and row[key] == "" else row[key]
                            for key in columns
                        )
                        for row in rows
                        if "crop" not in row or row["crop"] in params.KC_END
                    ],
                )


def expire_event_phones(connection: sqlite3.Connection) -> None:
    """Retain deduplication IDs without phone links beyond the rate window."""
    connection.execute(
        """UPDATE processed_events SET phone_hash = NULL
        WHERE phone_hash IS NOT NULL AND received_at <= datetime('now', '-1 hour')"""
    )


def hash_phone(number: str, settings: Settings) -> str:
    """Hash the gateway's canonical number without retaining the original."""
    secret = settings.require("phone_hash_secret")
    return hmac.new(secret.encode(), number.encode(), hashlib.sha256).hexdigest()


def record_event(
    connection: sqlite3.Connection,
    event_type: str,
    *,
    intent: str | None = None,
    template_id: str | None = None,
    source: EventSource | None = None,
    latency_ms: int | None = None,
) -> int:
    cursor = connection.execute(
        "INSERT INTO events (type, intent, template_id, source, latency_ms) VALUES (?, ?, ?, ?, ?)",
        (event_type, intent, template_id, source, latency_ms),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("Event insert did not return an id")
    return int(cursor.lastrowid)
