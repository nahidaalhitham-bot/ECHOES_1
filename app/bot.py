"""Telegram bot commands, so a caregiver can ask the bot questions.

Supported:
  /where   — latest location, clearly labelled live vs last-known
  /status  — device connection, battery, safe-zone state
  /start   — what the bot does

Polling is long-poll based on getUpdates with an offset stored in the
database, so restarting the app does not replay old commands.

This module never sends location to anyone but the configured caregiver chat.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import notify, safety
from .db import connect

API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

HELP_TEXT = (
    "ECHOES — بوت متابعة المريض\n\n"
    "/where  — آخر موقع معروف للمريض\n"
    "/status — حالة الجهاز والنطاق الآمن\n"
    "/link   — رمز QR لربط جوال المريض كتراكر\n"
    "/app    — رابط التطبيق الحالي (للمسؤول والمريض)\n\n"
    "ستصلك رسالة تلقائية فور خروج المريض من النطاق الآمن."
)


def _creds() -> tuple[str, str] | None:
    s = notify._settings()
    if s.get("channel") not in ("telegram", "both"):
        return None
    token = (s.get("telegram_token") or "").strip()
    chat = (s.get("telegram_chat_id") or "").strip()
    if not token or not chat:
        return None
    return token, chat


def _offset() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'telegram_offset'"
        ).fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def _set_offset(v: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES ('telegram_offset',?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(v),),
        )


def _api(token: str, method: str, params: dict | None = None) -> dict | None:
    url = f"{API_BASE}/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            body = json.loads(resp.read().decode() or "{}")
            return body if body.get("ok") else None
    except Exception:  # noqa: BLE001 - network errors are expected
        return None


def send_message(token: str, chat_id: str, text: str) -> bool:
    return _api(token, "sendMessage",
                {"chat_id": chat_id, "text": text}) is not None


def _patient_name() -> str:
    with connect() as conn:
        row = conn.execute("SELECT full_name FROM patient_profile WHERE id = 1").fetchone()
    return (row["full_name"] if row and row["full_name"] else "")


NO_DEVICE = ("لم يُربط جهاز تتبع للمريض بعد، لذلك لا أعرف موقعه.\n"
             "سأرسل لك الآن رمز الربط: افتحيه من جوال المريض واسمحي بالموقع.")


def _tracking_device():
    """The device that sent the most recent location (watch, phone, simulator)."""
    with connect() as conn:
        dev = conn.execute(
            "SELECT d.*, MAX(l.id) AS last_id FROM devices d JOIN locations l ON l.device_id=d.id "
            "GROUP BY d.id ORDER BY last_id DESC LIMIT 1").fetchone()
        if dev is None:
            dev = conn.execute("SELECT * FROM devices ORDER BY simulated ASC, id LIMIT 1").fetchone()
    return dev


def build_where() -> str:
    """Latest location, labelled honestly."""
    dev = _tracking_device()
    if dev is None:
        return NO_DEVICE
    loc = safety.latest_location(dev["id"])
    name = _patient_name()
    if loc is None:
        return (f"الجهاز «{dev['name']}» مربوط لكنه لم يرسل أي موقع بعد.\n"
                "تأكدي أن تطبيق الساعة أو صفحة الجوال مفتوحة ومسموح لها بالموقع.")

    link = notify.map_link(loc["lat"], loc["lon"])
    when = loc["reported_at"]
    if loc["is_fresh"]:
        head = "الموقع الحالي (حديث)"
    else:
        head = "آخر موقع معروف — وليس الموقع الحالي"
    lines = [
        f"{head} للمريض {name}" if name else head,
        f"الإحداثيات: {loc['lat']:.6f}, {loc['lon']:.6f}",
        f"وقت التحديث: {when}",
    ]
    if link:
        lines.append(f"الخريطة: {link}")
    if not loc["is_fresh"]:
        lines.append(f"⚠️ مرّ {loc['age_seconds'] // 60} دقيقة بدون تحديث.")
    return "\n".join(lines)


def build_status() -> str:
    dev = _tracking_device()
    with connect() as conn:
        zones = conn.execute("SELECT * FROM safe_zones WHERE enabled = 1").fetchall()
    if dev is None:
        return NO_DEVICE + ("" if zones else "\nولم يُحدَّد النطاق الآمن (البيت) بعد.")
    name = _patient_name()
    loc = safety.latest_location(dev["id"])
    inside = None
    if loc and zones:
        inside = all(
            safety.haversine_m(loc["lat"], loc["lon"], z["lat"], z["lon"]) <= z["radius_m"]
            for z in zones
        )
    parts = [f"الحالة للمريض {name}" if name else "الحالة:"]
    parts.append(f"الجهاز: {dev['name']} — {'متصل' if dev['connected'] else 'غير متصل'}")
    if dev["battery"] is not None:
        parts.append(f"البطارية: {dev['battery']}%")
    if inside is True:
        parts.append("داخل النطاق الآمن ✅")
    elif inside is False:
        parts.append("خارج النطاق الآمن ⚠️")
    elif not zones:
        parts.append("لم يُحدَّد النطاق الآمن (البيت) بعد — صفحة «الموقع المباشر».")
    else:
        parts.append("حالة النطاق: غير معروفة (لا يوجد موقع بعد)")
    if loc:
        parts.append(f"آخر تحديث للموقع: {loc['reported_at']}")
        if not loc["is_fresh"]:
            parts.append("الموقع قديم — لا يُعرض كموقع حالي.")
    return "\n".join(parts)


def handle_update(update: dict, token: str, chat_id: str) -> str | None:
    """Answer one Telegram update. Only the configured chat gets a reply."""
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    from_chat = str((msg.get("chat") or {}).get("id", ""))
    if from_chat not in [c.strip() for c in str(chat_id).split(",")]:
        # Silently ignore strangers: they must not learn anything.
        return None
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    if cmd in ("/where", "/location", "/موقع"):
        return build_where()
    if cmd in ("/status", "/حالة"):
        return build_status()
    if cmd in ("/link", "/ربط", "/qr"):
        return "LINK"
    if cmd in ("/app", "/رابط", "/url"):
        from . import tunnel, announce
        base = tunnel.public_base()
        return announce.message(base, wait=3) if base else (
            "التطبيق يعمل بدون رابط عام الآن.\nشغّليه من أيقونة ECHOES ← الخيار 1 (رابط عام) ويصلك الرابط هنا تلقائيًا.")
    if cmd in ("/start", "/help", "/مساعدة"):
        return HELP_TEXT
    return "الأوامر المتاحة:\n/where — آخر موقع\n/status — حالة الجهاز\n/link — ربط جوال المريض\n/app — رابط التطبيق"


def poll_once() -> int:
    """Fetch and answer pending updates. Returns how many were handled."""
    creds = _creds()
    if creds is None:
        return 0
    token, chat_id = creds
    body = _api(token, "getUpdates", {"offset": _offset() + 1, "timeout": 0})
    if not body:
        return 0
    handled = 0
    last_id = _offset()
    for upd in body.get("result", []):
        last_id = max(last_id, upd.get("update_id", 0))
        reply = handle_update(upd, token, chat_id)
        if reply:
            frm = str(((upd.get("message") or {}).get("chat") or {}).get("id", "")) or chat_id.split(",")[0]
            if reply == "LINK":
                send_tracker_link(token, frm)
            else:
                send_message(token, frm, reply)
                if reply.startswith(NO_DEVICE[:20]):
                    send_tracker_link(token, frm)
            handled += 1
    if last_id != _offset():
        _set_offset(last_id)
    return handled


def send_photo(token: str, chat_id: str, png: bytes, caption: str = "") -> bool:
    """sendPhoto with a multipart upload (the QR image)."""
    import uuid
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat_id), ("caption", caption)):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"qr.png\"\r\n"
                 "Content-Type: image/png\r\n\r\n".encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{API_BASE}/bot{token}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "{}").get("ok", False)
    except Exception:
        return False


def send_tracker_link(token: str, chat_id: str) -> None:
    """Send the phone-tracker link + QR image to a family chat."""
    from . import tracker_link
    info = tracker_link.get(wait=5)
    if not info.get("url"):
        send_message(token, chat_id,
                     "الرابط العام غير جاهز بعد، فلا أستطيع إرسال رمز الربط الآن.\n"
                     "شغّلي التطبيق من run_public_windows.bat مع اتصال إنترنت ثم أرسلي /link.")
        return
    from . import patient_link
    pair_url = patient_link.url(info["url"].split("/tracker")[0])
    text = ("📱 لربط جوال المريض كتراكر:\n"
            f"الطريقة الأولى: افتحي شاشة المريض في التطبيق على جواله {pair_url} — يظهر في أعلاها رمز QR، "
            "ثم من لوحة التحكم ← «حالة الجهاز» ← «📷 مسح QR جوال المريض».\n\n"
            "الطريقة الثانية (بدون مسح من اللوحة):\n"
            "1) افتحي هذا الرابط من جوال المريض (أو امسحي الصورة بكاميرته).\n"
            "2) اسمحي بالموقع واتركي الصفحة مفتوحة.\n\n"
            f"{info['url']}\n\n"
            "⚠️ لا ترسلي الرابط لأحد غير جوال المريض.")
    png = tracker_link.qr_png(info["url"])
    if png and send_photo(token, chat_id, png, "امسحي هذا الرمز بكاميرا جوال المريض"):
        send_message(token, chat_id, text)
    else:
        send_message(token, chat_id, text)
