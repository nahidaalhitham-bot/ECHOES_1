"""SQLite storage for Echeos (أصداء الذاكرة).

Scope note: this covers the modules that are actually implemented —
memory, family, location, safe zones, alerts, devices, audit.
It is not the full 14-table design from the brief; see README.md.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get(
    "ECHEOS_DB",
    os.path.join(os.path.dirname(__file__), "..", "echeos.db"),
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    relation    TEXT NOT NULL,
    preferred   TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,          -- person | place | routine | fact
    subject     TEXT NOT NULL,
    fact        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    basis       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A registered device (real watch, or the built-in simulator).
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL DEFAULT 'wearable',  -- wearable | phone | simulator
    connected    INTEGER NOT NULL DEFAULT 0,
    battery      INTEGER,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- 0 = a real device: its coordinates are treated as genuine.
    -- The simulator is created explicitly and keeps 1.
    simulated    INTEGER NOT NULL DEFAULT 0,
    token        TEXT UNIQUE,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Photos attached to a record. `owner_type` distinguishes a single portrait
-- (patient / person) from an unlimited album on a memory note (memory).
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type  TEXT NOT NULL,
    owner_id    INTEGER NOT NULL,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Voice notes attached to a memory. Also unlimited and auto-numbered.
CREATE TABLE IF NOT EXISTS media_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT NOT NULL,
    media_id INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'fact',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    related_to TEXT NOT NULL DEFAULT '',
    function_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(media_type, media_id)
);

CREATE TABLE IF NOT EXISTS audio_clips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   INTEGER NOT NULL,
    label       TEXT,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every reported position. Never presented as live unless recent.
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   INTEGER NOT NULL REFERENCES devices(id),
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    accuracy_m  REAL,
    altitude_m  REAL,
    reported_at TEXT NOT NULL DEFAULT (datetime('now')),
    simulated   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS safe_zones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    radius_m    REAL NOT NULL DEFAULT 300,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,   -- exited_safe_zone | device_offline | stale_location | no_recent_location | help_requested
    message     TEXT NOT NULL,
    device_id   INTEGER,
    lat         REAL,
    lon         REAL,
    location_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    read_at     TEXT,
    dedupe_key  TEXT UNIQUE      -- prevents alert spam
);

-- Opt-in face enrolment. One row per enrolled person.
CREATE TABLE IF NOT EXISTS face_enrollments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    embedding    TEXT NOT NULL,          -- JSON array of 128 floats
    consent      INTEGER NOT NULL DEFAULT 0,
    consented_by TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Places the family taught the device, as described in words.
-- Face descriptors derived automatically from an uploaded family photo.
-- Kept apart from face_enrollments so an explicit enrolment always wins.
CREATE TABLE IF NOT EXISTS photo_embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id   INTEGER NOT NULL,
    person_id  INTEGER NOT NULL,
    embedding  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(photo_id)
);

-- Visual descriptor for a photo in the personal-memory album, so the camera
-- can match a place or object the family taught it.
CREATE TABLE IF NOT EXISTS scene_embeddings (
    photo_id    INTEGER PRIMARY KEY,
    memory_id   INTEGER NOT NULL,
    label       TEXT NOT NULL,
    descriptor  TEXT NOT NULL,          -- JSON array of floats
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS places (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every recognition attempt, so "we didn't guess" is auditable.
CREATE TABLE IF NOT EXISTS recognition_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome     TEXT NOT NULL,           -- recognised | refused
    reason      TEXT,
    person_id   INTEGER,
    similarity  REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The memory NETWORK: typed nodes and typed edges between them.
-- This is what makes ECHOES a graph rather than a list of facts.
CREATE TABLE IF NOT EXISTS nodes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,          -- person | place | event | object | fact
    label      TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(kind, label)
);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id      INTEGER NOT NULL REFERENCES nodes(id),
    relation    TEXT NOT NULL,         -- visited | with | at | part_of | photo_of | remembers
    dst_id      INTEGER NOT NULL REFERENCES nodes(id),
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(src_id, relation, dst_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,         -- medication | appointment | routine | event
    title       TEXT NOT NULL,
    detail      TEXT,
    due_at      TEXT NOT NULL,         -- ISO timestamp
    done_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS review_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    asked       INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    hints       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES review_sessions(id),
    node_id     INTEGER,
    question    TEXT NOT NULL,
    expected    TEXT NOT NULL,
    answered    TEXT,
    is_correct  INTEGER,
    hint_used   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The patient profile. One row (id=1) for the prototype; every field is
-- editable from the dashboard so no code change is needed.
CREATE TABLE IF NOT EXISTS patient_profile (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    full_name       TEXT NOT NULL DEFAULT '',
    age             INTEGER,
    photo_path      TEXT,
    home_address    TEXT,
    medical_info    TEXT,
    allergies       TEXT,
    emergency_notes TEXT,
    important_info  TEXT,
    routine         TEXT,
    preferences     TEXT,
    memories        TEXT,
    -- what the caregiver wants the system to remind about automatically
    reminder_scope  TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Extra profile fields added later. Kept in a side table so existing installs
-- gain the columns without a migration step.
CREATE TABLE IF NOT EXISTS patient_profile_extra (
    patient_id  INTEGER PRIMARY KEY,
    nickname    TEXT DEFAULT '',
    date_of_birth TEXT DEFAULT '',
    gender      TEXT DEFAULT '',
    language    TEXT DEFAULT 'ar',
    dialect     TEXT DEFAULT '',
    home_lat    REAL,
    home_lon    REAL,
    phone       TEXT DEFAULT '',
    birthplace  TEXT DEFAULT '',
    childhood   TEXT DEFAULT '',
    occupation  TEXT DEFAULT '',
    education   TEXT DEFAULT '',
    life_events TEXT DEFAULT '',
    hobbies     TEXT DEFAULT '',
    favourite_activities TEXT DEFAULT '',
    favourite_foods TEXT DEFAULT '',
    favourite_drinks TEXT DEFAULT '',
    favourite_music TEXT DEFAULT '',
    favourite_places TEXT DEFAULT '',
    favourite_topics TEXT DEFAULT '',
    comfort_items TEXT DEFAULT '',
    confusion_triggers TEXT DEFAULT '',
    medications TEXT DEFAULT '',
    medication_schedule TEXT DEFAULT '',
    medical_instructions TEXT DEFAULT '',
    mobility TEXT DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Authorised caregivers. Multiple per patient.
CREATE TABLE IF NOT EXISTS caregivers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name      TEXT NOT NULL,
    relation       TEXT,
    phone          TEXT,
    email          TEXT,
    emergency_contact TEXT,
    is_primary     INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Assistant / device settings the caregiver can change without code.
CREATE TABLE IF NOT EXISTS assistant_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Zone exits queued for notification (filled inside the DB lock, drained after).
CREATE TABLE IF NOT EXISTS pending_notifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind      TEXT NOT NULL,
    zone_id   INTEGER,
    zone_name TEXT,
    lat       REAL,
    lon       REAL,
    event_at  TEXT,
    accuracy_m REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Where notifications go, configured by the caregiver, never hard-coded.
CREATE TABLE IF NOT EXISTS notif_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

-- Every outbound attempt, delivered or not. The audit trail for "did the
-- caregiver actually get the message?"
CREATE TABLE IF NOT EXISTS notif_outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id   INTEGER,
    channel    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    delivered  INTEGER NOT NULL DEFAULT 0,
    detail     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Caregiver accounts. Passwords are PBKDF2 hashes, never plaintext.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'caregiver',  -- viewer | caregiver | owner
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-device connection state, so we alert once on a transition rather than
-- on every poll.
CREATE TABLE IF NOT EXISTS device_state (
    device_id       INTEGER PRIMARY KEY,
    online          INTEGER NOT NULL DEFAULT 1,
    offline_since   TEXT,
    last_alert_kind TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Caregiver phone numbers used by the token-free channels (SMS / click-to-chat).
CREATE TABLE IF NOT EXISTS alert_contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL,
    channel    TEXT NOT NULL DEFAULT 'sms',   -- sms | whatsapp_link
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(phone, channel)
);

-- Time-limited, revocable public links so a caregiver can share the live
-- location with family by WhatsApp/SMS without giving them an account.
CREATE TABLE IF NOT EXISTS share_links (
    token      TEXT PRIMARY KEY,
    created_by INTEGER,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cool-down ledger for spoken reminders and companion alerts.
CREATE TABLE IF NOT EXISTS companion_events (
    key     TEXT PRIMARY KEY,
    last_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(media_annotations)")}
        if "function_text" not in cols:
            conn.execute("ALTER TABLE media_annotations ADD COLUMN function_text TEXT NOT NULL DEFAULT ''")
        # Safety lists + private topics (companion), added to existing installs.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(patient_profile_extra)")}
        for c in ("allergy_items", "danger_items", "private_topics"):
            if c not in cols:
                conn.execute(f"ALTER TABLE patient_profile_extra ADD COLUMN {c} TEXT DEFAULT ''")
        # Watches that report only when leaving the safe zone send a heartbeat
        # instead of constant locations.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)")}
        for c, ddl in (("report_mode", "TEXT DEFAULT 'continuous'"),
                       ("zone_status", "TEXT"), ("zone_checked_at", "TEXT")):
            if c not in cols:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {c} {ddl}")
        # Where a node / link came from: manual | evidence | ai | web | conversation
        for table in ("nodes", "edges"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "source" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN source TEXT DEFAULT 'manual'")


def reset_db() -> None:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
