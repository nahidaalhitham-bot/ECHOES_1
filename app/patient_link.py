"""The patient's app has its OWN link, separate from the caregiver's.

  caregiver:  <base>/login            (email + password, full control)
  patient:    <base>/patient#k=<key>  (patient screen only — no dashboard)

The key travels in the #fragment, is stored on the patient's phone, and is
sent as the X-Patient-Key header. The patient-screen APIs accept either a
caregiver session or this key, so a stranger who only knows the public
address can't talk to the assistant or read memories. «رابط جديد» rotates
the key (old patient phones lose access).
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Cookie, Header, HTTPException

from . import auth
from .db import connect

_KEY = "patient_app_key"


def get_key(rotate: bool = False) -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (_KEY,)).fetchone()
        if row and row["value"] and not rotate:
            return row["value"]
        k = secrets.token_urlsafe(18)
        conn.execute("INSERT INTO settings(key,value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_KEY, k))
        return k


def valid(key: str | None) -> bool:
    return bool(key) and hmac.compare_digest(key.strip(), get_key())


def url(base: str | None, wait: float = 0) -> str | None:
    """The patient's own address (a different domain) when it is open,
    otherwise <caregiver address>/patient as a fallback."""
    from . import tunnel
    pb = tunnel.patient_base(wait_seconds=wait)
    if pb:
        return f"{pb}/#k={get_key()}"
    return f"{base.rstrip('/')}/patient#k={get_key()}" if base else None


def require_patient_or_caregiver(session: str | None = Cookie(default=None),
                                 x_patient_key: str | None = Header(default=None)) -> dict:
    u = auth.user_for_token(session)
    if u:
        return u
    if valid(x_patient_key):
        return {"id": 0, "role": "patient", "full_name": "patient"}
    raise HTTPException(status_code=401, detail="رابط المريض غير صالح — اطلبي الرابط الجديد من المسؤول")
