"""The link + QR that turns the patient's phone into his tracker.

The same code stays valid (it is NOT regenerated each time the page opens),
so a phone that is already linked keeps working. «رمز جديد» rotates it.
The link carries the device token in the #fragment (never sent to servers).
"""

from __future__ import annotations

import io

from . import devices as dev_mod
from . import tunnel
from .db import connect

PHONE_TRACKER_NAME = "جوال المريض"


def _device(rotate: bool) -> tuple[int, str]:
    with connect() as conn:
        row = conn.execute("SELECT id, token FROM devices WHERE name=?",
                           (PHONE_TRACKER_NAME,)).fetchone()
    if row:
        if rotate or not row["token"]:
            return row["id"], dev_mod.rotate_token(row["id"])
        return row["id"], row["token"]
    created = dev_mod.create_device(PHONE_TRACKER_NAME, "phone")
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO device_state(device_id,online) VALUES (?,0)",
                     (created["id"],))
    return created["id"], created["token"]


def get(rotate: bool = False, wait: float = 20) -> dict:
    dev_id, token = _device(rotate)
    base = tunnel.public_base(wait_seconds=wait)
    path = f"/tracker#t={token}"
    url = f"{base}{path}" if base else None
    qr_svg = None
    if url:
        try:
            import segno
            qr_svg = segno.make(url, error="m").svg_inline(scale=6, border=2)
        except Exception:
            qr_svg = None
    return {"ok": True, "device_id": dev_id, "url": url, "path": path,
            "public": bool(base), "qr_svg": qr_svg, "tunnel": tunnel.status()}


def qr_png(url: str) -> bytes | None:
    try:
        import segno
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="png", scale=10, border=3)
        return buf.getvalue()
    except Exception:
        return None


# ---- reverse pairing: the PATIENT's phone shows a QR, the dashboard scans it ----
import secrets
import time as _time

PAIR_PREFIX = "ECHOES-PHONE:"
PAIR_TTL = 15 * 60
_ALPH = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _pair_table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS phone_pairs ("
                 "code TEXT PRIMARY KEY, created REAL, token TEXT, device_id INTEGER)")
    conn.execute("DELETE FROM phone_pairs WHERE created < ?", (_time.time() - PAIR_TTL,))


def pair_new() -> dict:
    code = "".join(secrets.choice(_ALPH) for _ in range(8))
    with connect() as conn:
        _pair_table(conn)
        n = conn.execute("SELECT COUNT(*) c FROM phone_pairs WHERE token IS NULL").fetchone()["c"]
        if n > 200:   # abuse guard
            conn.execute("DELETE FROM phone_pairs WHERE token IS NULL")
        conn.execute("INSERT INTO phone_pairs(code,created) VALUES (?,?)", (code, _time.time()))
    qr_svg = None
    try:
        import segno
        qr_svg = segno.make(PAIR_PREFIX + code, error="m").svg_inline(scale=9, border=2)
    except Exception:
        pass
    return {"code": code, "qr": PAIR_PREFIX + code, "qr_svg": qr_svg, "expires_in": PAIR_TTL}


def pair_status(code: str) -> dict:
    code = (code or "").strip().upper()
    with connect() as conn:
        _pair_table(conn)
        row = conn.execute("SELECT * FROM phone_pairs WHERE code=?", (code,)).fetchone()
        if row is None:
            return {"status": "expired"}
        if not row["token"]:
            return {"status": "waiting"}
        conn.execute("DELETE FROM phone_pairs WHERE code=?", (code,))   # hand the token over once
        return {"status": "linked", "token": row["token"], "device_id": row["device_id"]}


def normalize_code(text: str) -> str:
    t = (text or "").strip()
    if t.upper().startswith(PAIR_PREFIX):
        t = t[len(PAIR_PREFIX):]
    return "".join(ch for ch in t.upper() if ch.isalnum())


def pair_claim(text: str) -> dict:
    """Called when the caregiver scans (or types) the code shown on the patient's phone."""
    code = normalize_code(text)
    with connect() as conn:
        _pair_table(conn)
        row = conn.execute("SELECT * FROM phone_pairs WHERE code=?", (code,)).fetchone()
    if row is None:
        return {"ok": False, "reason": "expired"}
    dev_id, token = _device(rotate=False)
    with connect() as conn:
        conn.execute("UPDATE phone_pairs SET token=?, device_id=? WHERE code=?", (token, dev_id, code))
    return {"ok": True, "device_id": dev_id, "name": PHONE_TRACKER_NAME}
