"""Token-free alert channels.

These exist because the patient's family should not be blocked on obtaining a
Meta Business account or a bot token just to learn that someone left the house.

Two channels that need only a phone number:

1. **SMS** — via the phone's own messaging app. The server composes the exact
   message and produces a `sms:` deep link. Opening it on the caregiver's
   phone sends the SMS from their own number, billed by their carrier. No
   token, no account, no provider.

2. **WhatsApp click-to-chat** — a `wa.me` link that opens WhatsApp with the
   message pre-filled. The caregiver presses send. Again no token.

**What neither can do, and never will without credentials:** send the message
silently in the background. A `sms:` or `wa.me` link requires a human to press
send on a phone. That is a platform rule, not a missing feature — so this module
never claims a message was delivered on its own.

For unattended delivery the app still offers Telegram (bot token) or the
WhatsApp Cloud API (Meta Business). Those are the only fully automatic paths.
"""

from __future__ import annotations

import urllib.parse

from .db import connect


def normalise_phone(raw: str) -> str:
    """Keep digits and a leading +; drop spaces, dashes and brackets."""
    digits = "".join(c for c in raw if c.isdigit() or c == "+")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    return digits


def add_contact(name: str, phone: str, channel: str = "sms") -> dict:
    phone = normalise_phone(phone)
    if len(phone.lstrip("+")) < 7:
        raise ValueError("رقم الهاتف غير صالح")
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO alert_contacts(name,phone,channel) VALUES (?,?,?)",
                (name.strip(), phone, channel),
            )
        except Exception:
            raise ValueError("الرقم مسجَّل مسبقًا لهذه القناة")
        return {"id": cur.lastrowid, "name": name, "phone": phone,
                "channel": channel, "enabled": True}


def list_contacts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_contacts ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_contact(contact_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM alert_contacts WHERE id = ?", (contact_id,))
    return cur.rowcount > 0


def _body(text: str) -> str:
    # Keep the link short enough for SMS; the map URL is the long part.
    return text


def sms_link(phone: str, text: str) -> str:
    """A sms: deep link. `?body=` is understood by iOS and most Android apps."""
    return f"sms:{phone}?&body={urllib.parse.quote(_body(text))}"


def whatsapp_link(phone: str, text: str) -> str:
    """Click-to-chat link; `phone` must be digits only, international format."""
    digits = phone.replace("+", "")
    return f"https://wa.me/{digits}?text={urllib.parse.quote(_body(text))}"


def build_links(text: str, contacts: list[dict] | None = None) -> list[dict]:
    """One actionable link per enabled contact. Nothing is sent by the server."""
    out = []
    for c in (contacts if contacts is not None else list_contacts()):
        if not c.get("enabled"):
            continue
        if c["channel"] == "whatsapp_link":
            out.append({
                "contact": c["name"] or c["phone"],
                "phone": c["phone"],
                "channel": "whatsapp_link",
                "label": "افتحي واتساب وأرسلي",
                "link": whatsapp_link(c["phone"], text),
            })
        else:
            out.append({
                "contact": c["name"] or c["phone"],
                "phone": c["phone"],
                "channel": "sms",
                "label": "أرسلي رسالة نصية",
                "link": sms_link(c["phone"], text),
            })
    return out


def status() -> dict:
    return {
        "contact_count": len(list_contacts()),
        "note": ("هذه القنوات تفتح تطبيق الهاتف وتجهّز الرسالة — "
                 "لا تُرسل من الخادم تلقائيًا."),
    }
