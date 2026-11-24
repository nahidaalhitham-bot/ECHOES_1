"""Outbound notifications to caregivers.

The requirement: when the patient leaves the safe zone, the caregiver's phone
must receive a message *without opening the app* — carrying the location, a
map link, and the exit time.

Delivery is real, but it needs a channel the caregiver has configured:

- **telegram** — works if a bot token and chat id are set. Uses the public
  Bot API; no extra dependency (standard library urllib).
- **none** — nothing is delivered. The notification is still composed and
  stored in the outbox, and `delivered` stays False.

Hard rule: this module never reports success it did not observe. If no channel
is configured, the record says so plainly.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import secrets as _secrets
from .db import connect

# The spec asks specifically for a clickable Google Maps link.
# Documented universal link: opens the Maps app on a phone if installed,
# otherwise the web map. Coordinates go in the query, never a fixed point.
MAP_TEMPLATE = "https://www.google.com/maps/search/?api=1&query={lat},{lon}"

KIND_LABEL = {
    "exited_safe_zone": "خروج من النطاق الآمن",
    "help_requested": "طلب مساعدة",
    "device_offline": "انقطاع اتصال الجهاز",
    "device_reconnected": "عاد الجهاز للاتصال",
    "returned_safe_zone": "عاد إلى النطاق الآمن",
    "battery_low": "بطارية الجهاز منخفضة",
    "stale_location": "انقطاع تحديث الموقع",
    "no_recent_location": "لا يوجد موقع مسجّل",
    "allergen_contact": "المريض لمس/تناول شيئًا يتحسس منه",
    "danger_contact": "المريض يمسك شيئًا خطيرًا",
    "danger_action": "تصرف خطير من المريض",
}

# Credentials come from the environment first (as the spec requires), then
# from settings saved in the UI. Env wins so a deployment can override.
ENV_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT = "TELEGRAM_CHAT_ID"
ENV_SMTP_HOST = "SMTP_HOST"
ENV_SMTP_PORT = "SMTP_PORT"
ENV_SMTP_USER = "SMTP_USER"
ENV_SMTP_PASSWORD = "SMTP_PASSWORD"
ENV_SMTP_FROM = "SMTP_FROM"
ENV_SMTP_TO = "SMTP_TO"

ENV_WA_TOKEN = "WHATSAPP_TOKEN"
ENV_WA_PHONE_ID = "WHATSAPP_PHONE_NUMBER_ID"
ENV_WA_TO = "WHATSAPP_TO"

# WhatsApp Cloud API (Meta). Sending to a personal number requires a Meta
# Business app, an approved message template, and the recipient must have
# opted in — this is Meta's rule, not ours.
WA_API_BASE = os.environ.get("WHATSAPP_API_BASE", "https://graph.facebook.com").rstrip("/")
WA_GRAPH_VERSION = os.environ.get("WHATSAPP_GRAPH_VERSION", "v20.0")


def map_link(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    return MAP_TEMPLATE.format(lat=f"{lat:.6f}", lon=f"{lon:.6f}")


def create_temporary_live_share(hours: int = 24,
                                wait_seconds: float = 20) -> str | None:
    """Create an expiring, read-only PUBLIC live-location URL for an alert.

    Uses ECHOES_PUBLIC_URL / RENDER_EXTERNAL_URL, otherwise the Cloudflare
    tunnel the app opens automatically (see tunnel.py). Returns None only if
    no public https host is available at all — never a 127.0.0.1 link.
    """
    from . import tunnel
    base = tunnel.public_base(wait_seconds=wait_seconds)
    if not base or not base.startswith("https://"):
        return None
    token = __import__("secrets").token_urlsafe(32)
    from datetime import timedelta
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO share_links(token,created_by,expires_at) VALUES (?,?,?)",
            (token, None, expires),
        )
    return f"{base}/live/{token}"


def compose_exit(patient_name: str, lat: float | None, lon: float | None,
                 live_url: str | None, when: str = "") -> dict:
    """The exact zone-exit message the family asked for:

        خرج <اسم المريض> من المنزل وهو هنا الآن !
        <رابط الموقع المباشر — رابط عام>

    If no public live page can be opened, the Google Maps link is used instead
    (also public, opens on any phone) so the message always carries a link.
    """
    name = (patient_name or "").strip() or "المريض"
    link = live_url or map_link(lat, lon) or ""
    text = f"خرج {name} من المنزل وهو هنا الآن !"
    if link:
        text += f"\n{link}"
    return {
        "kind": "exited_safe_zone",
        "label": KIND_LABEL["exited_safe_zone"],
        "lat": lat,
        "lon": lon,
        "map_link": map_link(lat, lon),
        "live_share_url": live_url,
        "when": when,
        "text": text,
    }


def compose(kind: str, patient_name: str, lat: float | None,
            lon: float | None, when: str, extra: str = "",
            accuracy_m: float | None = None,
            device_online: bool | None = None,
            battery: int | None = None,
            live_url: str | None = None) -> dict:
    """Build the exact message a caregiver receives.

    Returns structured fields plus a ready-to-send text body, so the same
    content can go to Telegram, WhatsApp Cloud, Email, or the in-app outbox.
    """
    label = KIND_LABEL.get(kind, kind)
    parts = [f"⚠️ {label}"]
    if patient_name:
        parts.append(f"المريض: {patient_name}")
    if extra:
        parts.append(extra)
    if lat is not None and lon is not None:
        parts.append(f"الإحداثيات: {lat:.6f}, {lon:.6f}")
        if accuracy_m is not None:
            parts.append(f"دقة GPS: ±{round(accuracy_m)} متر")
        link = map_link(lat, lon)
        parts.append(f"افتح موقع المريض على الخريطة:\n{link}")
        if live_url:
            parts.append(f"رابط تتبع مباشر مؤقت (ينتهي خلال 24 ساعة):\n{live_url}")
    else:
        parts.append("الموقع: غير متوفر حاليًا")
    if device_online is not None:
        parts.append(f"حالة الجهاز: {'متصل' if device_online else 'غير متصل'}")
    if battery is not None:
        parts.append(f"البطارية: {battery}%")
    if when:
        parts.append(f"وقت الحدث: {when}")
    # Only a zone exit implies continued tracking; it would be nonsense on a
    # connection-loss or reconnection message.
    if kind == "exited_safe_zone":
        parts.append("سيستمر تحديث الموقع ما دام خارج النطاق.")
    return {
        "kind": kind,
        "label": label,
        "lat": lat,
        "lon": lon,
        "map_link": map_link(lat, lon) if lat is not None else None,
        "live_share_url": live_url,
        "when": when,
        "text": "\n".join(parts),
    }


def _send_email(host: str, port: int, user: str, password: str,
                sender: str, to: str, text: str,
                patient: str = "") -> tuple[bool, str]:
    """Send the alert by email over SMTP.

    Uses STARTTLS on 587 (the common case) and implicit TLS on 465. The body is
    a plain-text message with an ASCII Subject plus a UTF-8 body, so Arabic
    renders correctly in every client.
    """
    import smtplib
    import ssl
    from email.message import EmailMessage

    if not host:
        return False, "missing_smtp_host: لم يُدخل خادم البريد"
    if not to:
        return False, "missing_email_to: لم يُدخل بريد المستلم"
    if not sender:
        sender = user
    if not sender:
        return False, "missing_email_from: لم يُدخل بريد المرسل"

    msg = EmailMessage()
    msg["Subject"] = "ECHOES alert"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text)

    try:
        if int(port) == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, int(port), timeout=15, context=ctx) as srv:
                if user and password:
                    srv.login(user, password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, int(port), timeout=15) as srv:
                srv.ehlo()
                try:
                    srv.starttls(context=ssl.create_default_context())
                    srv.ehlo()
                except smtplib.SMTPException:
                    pass  # server without STARTTLS (local relay)
                if user and password:
                    srv.login(user, password)
                srv.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"smtp 535 — بيانات الدخول مرفوضة: {str(e)[:80]}"
    except smtplib.SMTPRecipientsRefused:
        return False, "smtp — عنوان المستلم مرفوض"
    except Exception as e:  # noqa: BLE001
        return False, f"smtp error: {type(e).__name__}: {str(e)[:90]}"


def _send_whatsapp(token: str, phone_id: str, to: str, text: str) -> tuple[bool, str]:
    """Send one WhatsApp text message via the Cloud API.

    Honest failure modes, all reported as-is:
      - no token / phone number id / recipient  -> refused here, no HTTP call
      - 401/403 from Meta                        -> credentials rejected
      - 131047                                    -> outside the 24h window
      - anything else                             -> Meta's own description
    """
    if not token:
        return False, "missing_whatsapp_token: لم يُدخل رمز وصول واتساب"
    if not phone_id:
        return False, "missing_whatsapp_phone_id: لم يُدخل معرّف رقم المرسل"
    if not to:
        return False, "missing_whatsapp_to: لم يُدخل رقم المستلم"

    url = f"{WA_API_BASE}/{WA_GRAPH_VERSION}/{phone_id}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode() or "{}")
            if body.get("messages"):
                return True, "sent"
            return False, f"whatsapp unexpected reply: {str(body)[:120]}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode() or "{}").get("error", {})
            detail = err.get("message", "")
            code = err.get("code")
        except Exception:
            code = None
        if e.code in (401, 403):
            return False, f"whatsapp {e.code} — الرمز غير صحيح أو منتهي: {detail}"
        if code == 131047:
            return False, ("whatsapp 131047 — خارج نافذة الـ24 ساعة. "
                           "واتساب يسمح بالرسائل الحرة فقط خلال 24 ساعة من آخر رسالة "
                           "من المستلم؛ خارجها يلزم قالب معتمد من Meta.")
        if code == 131026:
            return False, ("whatsapp 131026 — الرقم غير مسجَّل في واتساب "
                           "أو لم يوافق على استقبال الرسائل.")
        return False, f"whatsapp {e.code}" + (f": {detail}" if detail else "")
    except Exception as e:  # noqa: BLE001
        return False, f"whatsapp error: {type(e).__name__}"


def _settings() -> dict:
    """Environment variables take precedence over UI-saved values."""
    with connect() as conn:
        s = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM notif_settings")}

    # Stored values are encrypted; decrypt for use only.
    if s.get("telegram_token"):
        s["telegram_token"] = _secrets.decrypt(s["telegram_token"])
    if s.get("whatsapp_token"):
        s["whatsapp_token"] = _secrets.decrypt(s["whatsapp_token"])

    # Email settings: env wins, then stored values.
    for env_key, field in (
        (ENV_SMTP_HOST, "smtp_host"),
        (ENV_SMTP_PORT, "smtp_port"),
        (ENV_SMTP_USER, "smtp_user"),
        (ENV_SMTP_FROM, "smtp_from"),
        (ENV_SMTP_TO, "email_to"),
    ):
        v = os.environ.get(env_key, "").strip()
        if v:
            s[field] = v
    smtp_pw_env = os.environ.get(ENV_SMTP_PASSWORD, "").strip()
    if smtp_pw_env:
        s["smtp_password"] = smtp_pw_env
    if s.get("smtp_password"):
        s["smtp_password"] = _secrets.decrypt(s["smtp_password"])

    env_wa_token = os.environ.get(ENV_WA_TOKEN, "").strip()
    env_wa_phone = os.environ.get(ENV_WA_PHONE_ID, "").strip()
    env_wa_to = os.environ.get(ENV_WA_TO, "").strip()
    if env_wa_token:
        s["whatsapp_token"] = env_wa_token
        s["channel"] = "whatsapp"
    if env_wa_phone:
        s["whatsapp_phone_id"] = env_wa_phone
    if env_wa_to:
        s["whatsapp_to"] = env_wa_to

    env_token = os.environ.get(ENV_TOKEN, "").strip()
    env_chat = os.environ.get(ENV_CHAT, "").strip()
    if env_token:
        s["telegram_token"] = env_token
        s["channel"] = "telegram"
    if env_chat:
        s["telegram_chat_id"] = env_chat
    s["_credential_source"] = "env" if (env_token or env_chat) else "settings"
    return s


API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")


def _send_telegram(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Send to every linked family chat (comma-separated ids)."""
    ids = [c.strip() for c in (chat_id or "").split(",") if c.strip()]
    if len(ids) > 1:
        results = [_send_telegram_one(token, c, text) for c in ids]
        ok = any(r[0] for r in results)
        bad = [f"{c}: {r[1]}" for c, r in zip(ids, results) if not r[0]]
        return ok, ("sent" if not bad else ("sent to some — " if ok else "") + "; ".join(bad))
    return _send_telegram_one(token, ids[0] if ids else "", text)


def _send_telegram_one(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    # A missing token makes Telegram answer 404 "Not Found", which looks like a
    # broken URL rather than a missing credential. Say what is actually wrong.
    if not token:
        return False, ("missing_bot_token: لم يُدخل رمز البوت. "
                       "احصلي عليه من @BotFather ثم الصقيه في خانة Telegram Bot Token")
    if not chat_id:
        return False, ("missing_chat_id: لم يُدخل معرّف المحادثة. "
                       "أرسلي رسالة للبوت ثم اقرئي chat.id")
    url = f"{API_BASE}/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "disable_web_page_preview": "false",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=8) as resp:
            body = json.loads(resp.read().decode() or "{}")
            if body.get("ok"):
                return True, "sent"
            return False, f"telegram rejected: {body.get('description', 'unknown')}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode() or "{}")
            detail = body.get("description", "")
        except Exception:
            pass
        hint = {
            401: "الرمز غير صحيح — تأكدي من نسخه كاملًا من BotFather",
            403: "البوت محظور أو لا يستطيع مراسلة هذه المحادثة — اضغطي Start في البوت",
            400: "المعرّف (chat id) غير صحيح — تأكدي أنه رقم المحادثة",
            404: "رمز البوت غير صحيح أو غير مكتمل",
        }.get(e.code, "")
        return False, f"telegram http {e.code}" + (f" — {hint}" if hint else "") + (f": {detail}" if detail else "")
    except Exception as e:  # noqa: BLE001 - network errors are expected
        return False, f"telegram error: {type(e).__name__}"


# ------------------------------------------------ Telegram live location --
# Telegram's own "live location" pin: sent once on exit, moved on every new
# fix while the patient is outside, and stopped when he is back home. It works
# even when no public web link can be opened.
LIVE_PERIOD_SECONDS = 86400          # Telegram's maximum for a fixed period
LIVE_EDIT_MIN_SECONDS = 5            # Telegram rate-limits edits
_LIVE_KEY = "tg_live_message"


def _tg_call(token: str, method: str, params: dict) -> tuple[bool, dict | str]:
    url = f"{API_BASE}/bot{token}/{method}"
    data = urllib.parse.urlencode({k: str(v) for k, v in params.items()}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=8) as resp:
            body = json.loads(resp.read().decode() or "{}")
            if body.get("ok"):
                return True, body.get("result") or {}
            return False, body.get("description", "unknown")
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode() or "{}").get("description", f"http {e.code}")
        except Exception:
            return False, f"http {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def _telegram_creds() -> tuple[str, str] | None:
    s = _settings()
    token = (s.get("telegram_token") or "").strip()
    # the live pin goes to the first linked chat
    chat = (s.get("telegram_chat_id") or "").split(",")[0].strip()
    if not token or not chat:
        return None
    return token, chat


def _live_get() -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (_LIVE_KEY,)).fetchone()
    if not row or not row["value"]:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


def _live_set(value: dict | None) -> None:
    with connect() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (_LIVE_KEY,))
        else:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_LIVE_KEY, json.dumps(value)),
            )


def telegram_start_live(lat: float, lon: float,
                        accuracy_m: float | None = None) -> tuple[bool, str]:
    creds = _telegram_creds()
    if not creds:
        return False, "telegram not configured"
    token, chat = creds
    old = _live_get()
    if old:
        _tg_call(token, "stopMessageLiveLocation",
                 {"chat_id": old["chat_id"], "message_id": old["message_id"]})
    params = {"chat_id": chat, "latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}",
              "live_period": LIVE_PERIOD_SECONDS}
    if accuracy_m:
        params["horizontal_accuracy"] = min(1500, max(0, round(accuracy_m)))
    ok, res = _tg_call(token, "sendLocation", params)
    if ok and isinstance(res, dict) and res.get("message_id"):
        _live_set({"chat_id": chat, "message_id": res["message_id"], "t": time.time()})
        return True, "live location sent"
    return False, f"sendLocation failed: {res}"


def telegram_update_live(lat: float, lon: float,
                         accuracy_m: float | None = None) -> bool:
    """Move the live pin, if one is active. Throttled; never raises."""
    live = _live_get()
    if not live:
        return False
    if time.time() - float(live.get("t", 0)) < LIVE_EDIT_MIN_SECONDS:
        return False
    creds = _telegram_creds()
    if not creds:
        return False
    params = {"chat_id": live["chat_id"], "message_id": live["message_id"],
              "latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}"}
    if accuracy_m:
        params["horizontal_accuracy"] = min(1500, max(0, round(accuracy_m)))
    ok, res = _tg_call(creds[0], "editMessageLiveLocation", params)
    if ok or "not modified" in str(res):
        live["t"] = time.time()
        _live_set(live)
        return True
    if "expired" in str(res) or "not found" in str(res) or "can't be edited" in str(res):
        _live_set(None)
    return False


def telegram_stop_live() -> None:
    live = _live_get()
    if not live:
        return
    creds = _telegram_creds()
    if creds:
        _tg_call(creds[0], "stopMessageLiveLocation",
                 {"chat_id": live["chat_id"], "message_id": live["message_id"]})
    _live_set(None)


def deliver(alert_id: int, message: dict, patient_name: str = "") -> dict:
    """Attempt delivery and record the outcome in the outbox. Always honest."""
    s = _settings()
    channel = s.get("channel", "none")
    token = s.get("telegram_token", "")
    chat_id = s.get("telegram_chat_id", "")
    # A linked Telegram is never silently skipped: if the family linked the
    # bot but the channel was left on email/none, safety alerts go to
    # Telegram too (this was the #1 reason "no alert when he left home").
    if token and chat_id and channel in ("none", "", "email"):
        channel = "both" if channel == "email" else "telegram"

    delivered = False
    detail = "no channel configured — nothing was sent"

    parts = []
    if channel in ("telegram", "both"):
        if token and chat_id:
            ok, d = _send_telegram(token, chat_id, message["text"])
        else:
            ok, d = False, "telegram selected but credentials are missing"
        delivered = delivered or ok
        parts.append(f"telegram: {d}")
    if channel in ("email", "both"):
        ok, d = _send_email(
            s.get("smtp_host", ""),
            s.get("smtp_port", "587"),
            s.get("smtp_user", ""),
            s.get("smtp_password", ""),
            s.get("smtp_from", ""),
            s.get("email_to", ""),
            message["text"],
            patient_name,
        )
        delivered = delivered or ok
        parts.append(f"email: {d}")
    if channel == "whatsapp":
        delivered, d = _send_whatsapp(
            s.get("whatsapp_token", ""),
            s.get("whatsapp_phone_id", ""),
            s.get("whatsapp_to", ""),
            message["text"],
        )
        parts.append(f"whatsapp: {d}")
    if parts:
        detail = " | ".join(parts)
        if channel == "telegram":
            detail = parts[0][len("telegram: "):]

    with connect() as conn:
        conn.execute(
            "INSERT INTO notif_outbox(alert_id,channel,payload,delivered,detail) "
            "VALUES (?,?,?,?,?)",
            (alert_id, channel, message["text"],
             1 if delivered else 0, detail),
        )
    return {"delivered": delivered, "channel": channel, "detail": detail}


def outbox(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notif_outbox ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def notify_geofence_exit(alert_id: int, patient_name: str, lat: float,
                         lon: float, when: str, zone_name: str,
                         accuracy_m: float | None = None,
                         device_online: bool | None = None,
                         battery: int | None = None) -> dict:
    """The requirement's headline case: text + public live link, then the
    Telegram live-location pin so the caregiver can follow him in the app."""
    live_url = create_temporary_live_share(hours=24)
    msg = compose_exit(
        patient_name, lat, lon, live_url,
        when or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    result = deliver(alert_id, msg, patient_name)
    if result.get("channel") in ("telegram", "both") and lat is not None and lon is not None:
        ok, detail = telegram_start_live(lat, lon, accuracy_m)
        result["live_location"] = detail
    if not live_url:
        result["public_link_note"] = ("no public https host — sent the Google Maps "
                                      "link instead of the live page")
    return {**msg, **result}


def notify_help(alert_id: int, patient_name: str, lat: float | None,
                lon: float | None, when: str) -> dict:
    msg = compose("help_requested", patient_name, lat, lon, when)
    result = deliver(alert_id, msg, patient_name)
    return {**msg, **result}


def notify_reconnected(alert_id: int, patient_name: str, lat: float | None,
                       lon: float | None) -> dict:
    """Device came back. Caregivers should stop worrying."""
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    msg = compose("device_reconnected", patient_name, lat, lon, when,
                  extra="عاد الجهاز إلى الاتصال ويُرسل الموقع من جديد.")
    return {**msg, **deliver(alert_id, msg, patient_name)}


def notify_connection_lost(alert_id: int, patient_name: str,
                           last_lat: float | None, last_lon: float | None,
                           minutes_silent: int) -> dict:
    """Device stopped reporting. We must not call the old fix 'live'."""
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    msg = compose(
        "device_offline", patient_name, last_lat, last_lon, when,
        extra=(f"توقف الجهاز عن إرسال الموقع منذ {minutes_silent} دقيقة. "
               "الموقع أدناه هو آخر موقع معروف، وليس الموقع الحالي."),
    )
    if last_lat is not None:
        # Make the last-known framing explicit inside the body too.
        msg["text"] = msg["text"].replace("الموقع:", "آخر موقع معروف:")
    return {**msg, **deliver(alert_id, msg, patient_name)}


def notify_location_update(patient_name: str, lat: float, lon: float,
                           when: str) -> dict:
    """A position update while the patient is outside the safe zone."""
    msg = compose("exited_safe_zone", patient_name, lat, lon, when,
                  extra="تحديث الموقع — المريض ما زال خارج النطاق.")
    return {**msg, **deliver(0, msg, patient_name)}


def notify_returned_zone(alert_id: int, patient_name: str, lat: float | None,
                         lon: float | None, when: str,
                         accuracy_m: float | None = None,
                         device_online: bool | None = None,
                         battery: int | None = None) -> dict:
    """Patient is back inside the safe zone — reassure the caregiver."""
    telegram_stop_live()
    msg = compose("returned_safe_zone", patient_name, lat, lon, when,
                  extra="عاد المريض إلى داخل النطاق الآمن.",
                  accuracy_m=accuracy_m, device_online=device_online,
                  battery=battery)
    return {**msg, **deliver(alert_id, msg, patient_name)}
