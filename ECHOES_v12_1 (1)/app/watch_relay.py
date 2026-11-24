"""Pairing a Wear OS watch, and keeping it pointed at the right address.

Problems this solves:
1. A watch has no camera for a QR code, and typing a long link on it is
   painful -> the dashboard shows a short 6-character code instead.
2. The free public link (trycloudflare) changes on every restart -> the app
   publishes the current link to a private channel on ntfy.sh (a free
   push/relay service). The watch reads its channel when its saved address
   stops answering, and continues automatically.

Only the server ADDRESS goes through ntfy.sh. Locations and the device token
go straight from the watch to this app over HTTPS.
"""

from __future__ import annotations

import json
import secrets
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

from . import devices as dev_mod
from .db import connect

NTFY = "https://ntfy.sh"
WATCH_NAME = "ساعة المريض"
CODE_ALPHABET = "ACDEFHJKMNPRTUVWXY34679"     # no 0/O, 1/I/L, 5/S, 8/B
CODE_MINUTES = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS device_pairing (
    code       TEXT PRIMARY KEY,
    device_id  INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE TABLE IF NOT EXISTS device_relay (
    device_id INTEGER PRIMARY KEY,
    topic     TEXT NOT NULL UNIQUE
);
"""


def _init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def publish(topic: str, payload: dict) -> bool:
    """Post a small JSON message to an ntfy topic (cached there ~12 h)."""
    try:
        req = urllib.request.Request(
            f"{NTFY}/{topic}", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Title": "ECHOES", "Content-Type": "text/plain; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def _publish_async(topic: str, payload: dict) -> None:
    threading.Thread(target=publish, args=(topic, payload), daemon=True).start()


def _watch_device() -> int:
    with connect() as conn:
        row = conn.execute("SELECT id FROM devices WHERE name=?", (WATCH_NAME,)).fetchone()
    if row:
        return row["id"]
    created = dev_mod.create_device(WATCH_NAME, "wearable")
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO device_state(device_id,online) VALUES (?,0)",
                     (created["id"],))
    return created["id"]


def new_code(public_url: str | None) -> dict:
    """A fresh 6-character pairing code for the patient's watch."""
    _init()
    dev_id = _watch_device()
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    exp = datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)
    with connect() as conn:
        conn.execute("DELETE FROM device_pairing WHERE device_id=? AND used_at IS NULL",
                     (dev_id,))
        conn.execute("INSERT INTO device_pairing(code,device_id,expires_at) VALUES (?,?,?)",
                     (code, dev_id, exp.isoformat()))
    published = publish(f"echoes-pair-{code}", {"url": public_url}) if public_url else False
    return {"code": code, "device_id": dev_id, "expires_at": exp.isoformat(),
            "minutes": CODE_MINUTES, "published": published}


def scan(pair_id: str, public_url: str) -> dict | None:
    """The caregiver scanned the QR shown on the watch.

    The QR holds a random id the watch generated. We create a pairing code and
    drop {url, code} into the watch's own ntfy channel; the watch is listening
    there and finishes pairing by itself within a few seconds."""
    import re
    if not re.fullmatch(r"[A-Za-z0-9]{12,40}", pair_id or ""):
        return None
    info = new_code(public_url)
    delivered = publish(f"echoes-claim-{pair_id}", {"url": public_url, "code": info["code"]})
    return {**info, "delivered": delivered}


def claim(code: str) -> dict | None:
    """The watch exchanges the code for its own token + private relay channel."""
    _init()
    code = (code or "").strip().upper().replace("-", "").replace(" ", "")
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM device_pairing WHERE code=? AND used_at IS NULL AND expires_at>?",
            (code, now)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE device_pairing SET used_at=? WHERE code=?", (now, code))
    dev_id = row["device_id"]
    token = dev_mod.rotate_token(dev_id)          # cancels any older watch
    topic = "echoes-dev-" + secrets.token_hex(16)
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO device_relay(device_id,topic) VALUES (?,?)",
                     (dev_id, topic))
        dev = conn.execute("SELECT name FROM devices WHERE id=?", (dev_id,)).fetchone()
        p = conn.execute("SELECT full_name FROM patient_profile WHERE id=1").fetchone()
    return {"token": token, "device_id": dev_id, "device_name": dev["name"],
            "relay_topic": topic,
            "patient_name": (p["full_name"] if p and p["full_name"] else "")}


def announce_url(url: str) -> None:
    """Tell every paired watch (and pending codes) the current public link."""
    if not url:
        return
    try:
        _init()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as conn:
            topics = [r["topic"] for r in conn.execute("SELECT topic FROM device_relay")]
            codes = [r["code"] for r in conn.execute(
                "SELECT code FROM device_pairing WHERE used_at IS NULL AND expires_at>?",
                (now,))]
    except Exception:
        return
    for t in topics:
        _publish_async(t, {"url": url})
    for c in codes:
        _publish_async(f"echoes-pair-{c}", {"url": url})
