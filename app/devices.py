"""Real GPS device ingestion.

A physical device (smartwatch, phone, or tracker) posts its coordinates here
with a per-device bearer token. No coordinates are invented anywhere in this
module: if no device has posted, there is simply no location.

Pairing flow:
    1. Caregiver creates a device in the UI  -> server returns a token once.
    2. Device stores that token.
    3. Device posts  {lat, lon, accuracy, battery}  to /api/device/report
       with header  Authorization: Bearer <token>
    4. Server records the fix, evaluates the safe zone, and notifies.

The token is shown once at creation and never returned again.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from .db import connect


def create_device(name: str, kind: str = "wearable") -> dict:
    """Create a real (non-simulated) device and issue its token."""
    token = "ech_" + secrets.token_urlsafe(28)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO devices(name,kind,connected,simulated,token) "
            "VALUES (?,?,0,0,?)",
            (name.strip(), kind, token),
        )
        dev_id = cur.lastrowid
    return {"id": dev_id, "name": name, "kind": kind, "token": token,
            "simulated": False}


def create_simulator(name: str = "محاكي الجهاز") -> dict:
    """Explicitly opt-in test device. Never used unless asked for."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO devices(name,kind,connected,simulated) VALUES (?,?,1,1)",
            (name, "simulator"),
        )
        dev_id = cur.lastrowid
    return {"id": dev_id, "name": name, "kind": "simulator", "simulated": True}


def resolve_token(token: str) -> dict | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE token = ?", (token,)
        ).fetchone()
    return dict(row) if row else None


def rotate_token(device_id: int) -> str:
    token = "ech_" + secrets.token_urlsafe(28)
    with connect() as conn:
        conn.execute("UPDATE devices SET token = ? WHERE id = ?", (token, device_id))
    return token


def status() -> dict:
    """Honest connection state for the dashboard."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        last = conn.execute(
            "SELECT * FROM locations ORDER BY id DESC LIMIT 1"
        ).fetchone()

    devices = [dict(r) for r in rows]
    real = [d for d in devices if not d["simulated"]]

    if not real:
        state = "no_device"
        message = "لا يوجد جهاز حقيقي مرتبط. أضيفي جهازًا من صفحة الجهاز."
    else:
        real_ids = {d["id"] for d in real}
        # Only trust a fix that came from a REAL device.
        fix = None
        if last and last["device_id"] in real_ids:
            from .safety import latest_location
            fix = latest_location(last["device_id"])
        if fix is None:
            state = "no_fix"
            message = "الجهاز مرتبط لكنه لم يرسل أي إحداثيات بعد."
        elif fix["is_fresh"]:
            state = "live"
            message = "الموقع حيّ."
        else:
            state = "last_known"
            message = "آخر موقع معروف فقط — لا يوجد تحديث حديث."
    return {
        "state": state,
        "message": message,
        "device_connected": bool(real and any(d["connected"] for d in real)),
        "real_devices": len(real),
    }
