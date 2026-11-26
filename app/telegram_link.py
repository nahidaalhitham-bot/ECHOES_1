"""One-tap Telegram linking — no Chat ID to look up or type.

1. The caregiver pastes the bot token once (from @BotFather).
2. We show a link/QR:  https://t.me/<bot>?start=<code>
3. Each family member opens it and presses Start. We read that /start
   message from Telegram, save their chat id (several family members can
   join), switch alerts to Telegram and send a confirmation message.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from . import bot
from . import secrets as secrets_mod
from .db import connect

JOIN_MINUTES = 30


def _set(conn, table: str, key: str, value: str) -> None:
    conn.execute(f"INSERT INTO {table}(key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _get(table: str, key: str) -> str:
    with connect() as conn:
        row = conn.execute(f"SELECT value FROM {table} WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""


def _token() -> str:
    enc = _get("notif_settings", "telegram_token")
    try:
        return secrets_mod.decrypt(enc) if enc else ""
    except Exception:
        return ""


def start(token: str | None) -> dict:
    """Validate/save the token and create a join link valid for 30 minutes."""
    token = (token or "").strip() or _token()
    if not token:
        return {"ok": False, "error": "الصقي رمز البوت من @BotFather أولًا."}
    me = bot._api(token, "getMe")
    if not me:
        return {"ok": False, "error": "رمز البوت غير صحيح، أو لا يوجد اتصال بالإنترنت. "
                                      "انسخي الرمز كاملًا من @BotFather."}
    username = me["result"].get("username", "")
    code = secrets.token_hex(4)
    exp = (datetime.now(timezone.utc) + timedelta(minutes=JOIN_MINUTES)).isoformat()
    with connect() as conn:
        _set(conn, "notif_settings", "telegram_token", secrets_mod.encrypt(token))
        _set(conn, "settings", "tg_join_code", code)
        _set(conn, "settings", "tg_join_expires", exp)
    url = f"https://t.me/{username}?start={code}"
    qr = None
    try:
        import segno
        qr = segno.make(url, error="m").svg_inline(scale=5, border=2)
    except Exception:
        pass
    return {"ok": True, "bot": username, "url": url, "qr_svg": qr,
            "minutes": JOIN_MINUTES, "linked": linked_chats()}


def _bot_id() -> str:
    t = _token()
    return t.split(":", 1)[0] if ":" in t else ""


def linked_chats() -> list[str]:
    ids = _get("notif_settings", "telegram_chat_id")
    bot_id = _bot_id()
    # the number before ':' in the token is the BOT, never a family chat
    return [c.strip() for c in ids.split(",") if c.strip() and c.strip() != bot_id]


def check() -> dict:
    """Look for '/start <code>' messages and link those chats.

    While nobody is linked yet and the setup window is open, a plain /start
    (just opening the bot and pressing Start) is accepted too."""
    token = _token()
    code = _get("settings", "tg_join_code")
    exp = _get("settings", "tg_join_expires")
    if not token:
        return {"ok": False, "error": "ابدئي الربط أولًا."}
    expired = not exp or exp <= datetime.now(timezone.utc).isoformat()
    open_until = _get("settings", "tg_open_until")
    first_link_open = bool(open_until) and open_until > datetime.now(timezone.utc).isoformat()
    body = bot._api(token, "getUpdates", {"offset": bot._offset() + 1, "timeout": 0})
    if body is None:
        return {"ok": False, "error": "تعذّر الاتصال بتيليجرام — تحققي من الإنترنت."}
    chats = linked_chats()
    new_names = []
    last_id = bot._offset()
    for upd in body.get("result", []):
        last_id = max(last_id, upd.get("update_id", 0))
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        cid = str(chat.get("id", ""))
        if not cid:
            continue
        plain_start = (text == "/start" and first_link_open and not linked_chats() and not new_names)
        if (code and text == f"/start {code}" and not expired) or plain_start:
            name = chat.get("first_name") or chat.get("title") or chat.get("username") or cid
            if cid not in chats:
                chats.append(cid)
                new_names.append(name)
            bot.send_message(token, cid,
                             f"✅ تم ربطك بتنبيهات ECHOES يا {name}.\n"
                             "ستصلك رسالة فور خروج المريض من البيت أو عند طلبه المساعدة.\n"
                             "/where آخر موقع · /status حالة الجهاز")
        elif cid in chats:
            reply = bot.handle_update(upd, token, ",".join(chats))
            if reply == "LINK":
                bot.send_tracker_link(token, cid)
            elif reply:
                bot.send_message(token, cid, reply)
                if reply.startswith(bot.NO_DEVICE[:20]):
                    bot.send_tracker_link(token, cid)
    if last_id != bot._offset():
        bot._set_offset(last_id)
    if new_names:
        with connect() as conn:
            _set(conn, "notif_settings", "telegram_chat_id", ",".join(chats))
            ch = conn.execute("SELECT value FROM notif_settings WHERE key='channel'").fetchone()
            host = conn.execute("SELECT value FROM notif_settings WHERE key='smtp_host'").fetchone()
            current = ch["value"] if ch else "none"
            email_ok = bool(host and host["value"].strip() and not host["value"].strip().isdigit())
            # keep e-mail too if it was chosen AND actually set up correctly
            _set(conn, "notif_settings", "channel",
                 "both" if current in ("email", "both") and email_ok else "telegram")
    return {"ok": True, "new": new_names, "linked": chats, "expired": expired}


def unlink_all() -> None:
    with connect() as conn:
        _set(conn, "notif_settings", "telegram_chat_id", "")


# ------------------------------------------------ automatic background setup --

TOKEN_FILE = "telegram_token.txt"


def import_token_file(root) -> str | None:
    """A bot token placed in telegram_token.txt is saved (encrypted) at start."""
    from pathlib import Path
    f = Path(root) / TOKEN_FILE
    if not f.exists():
        return None
    tok = ""
    for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            tok = line
            break
    if not tok:
        return None
    if tok != _token():
        with connect() as conn:
            _set(conn, "notif_settings", "telegram_token", secrets_mod.encrypt(tok))
    return tok


def clean_wrong_chat() -> None:
    """Remove the bot's own id if it was typed into the Chat ID box."""
    ids = _get("notif_settings", "telegram_chat_id")
    good = linked_chats()
    if ids and ",".join(good) != ids.replace(" ", ""):
        with connect() as conn:
            _set(conn, "notif_settings", "telegram_chat_id", ",".join(good))


def status() -> dict:
    tok = _token()
    username = ""
    if tok:
        me = bot._api(tok, "getMe")
        username = me["result"].get("username", "") if me else ""
    return {"token": bool(tok), "bot": username, "linked": len(linked_chats()),
            "url": f"https://t.me/{username}" if username else ""}


def background_loop(root) -> None:
    """Runs for the life of the app: links whoever presses Start during the
    first 60 minutes (until someone is linked), answers /where and /status."""
    import time as _t
    try:
        import_token_file(root)
        clean_wrong_chat()
        if _token() and not linked_chats():
            with connect() as conn:
                _set(conn, "settings", "tg_open_until",
                     (datetime.now(timezone.utc) + timedelta(minutes=60)).isoformat())
            st = status()
            if st["bot"]:
                print("\n  ===========================================================")
                print("   تيليجرام: افتحي من جوالك هذا الرابط واضغطي Start:")
                print(f"   {st['url']}")
                print("   (يرتبط تلقائيًا خلال ثوانٍ — صالح 60 دقيقة)")
                print("  ===========================================================\n", flush=True)
    except Exception:
        pass
    while True:
        try:
            if _token():
                r = check()
                for n in r.get("new") or []:
                    print(f"  ✅ تيليجرام: تم ربط {n}", flush=True)
        except Exception:
            pass
        _t.sleep(4)
