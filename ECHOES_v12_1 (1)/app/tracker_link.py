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
