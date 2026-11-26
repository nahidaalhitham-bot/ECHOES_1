"""Tell everyone the app's new public address as soon as it is ready.

The quick-tunnel address changes on every start, so:
  * paired watches get it through ntfy (watch_relay),
  * the family gets it on Telegram, with the caregiver and patient links.
"""

from __future__ import annotations

import threading

_last = {"url": None}


def links(url: str, wait: float = 45) -> dict:
    url = url.rstrip("/")
    from . import patient_link
    return {"caregiver": f"{url}/login", "patient": patient_link.url(url, wait=wait)}


def message(url: str, wait: float = 45) -> str:
    l = links(url, wait)
    return ("✅ تطبيق ECHOES شغّال الآن\n\n"
            f"📱 جوال المسؤول (لوحة التحكم):\n{l['caregiver']}\n\n"
            f"👴 جوال المريض فقط (تطبيق المريض — بدون لوحة المسؤول):\n{l['patient']}\n\n"
            "⌚ ساعة المريض تعرف الرابط الجديد تلقائيًا.\n"
            "لربط الساعة: من جوال المسؤول ← «حالة الجهاز» ← «📷 مسح QR الساعة».\n\n"
            "الرابط يتغير عند كل إعادة تشغيل — يصلك الجديد هنا دائمًا. أرسلي /app لأخذه في أي وقت.")


def public_url_ready(url: str) -> None:
    url = (url or "").rstrip("/")
    if not url or _last["url"] == url:
        return
    _last["url"] = url
    try:
        from . import watch_relay
        watch_relay.announce_url(url)
    except Exception:
        pass

    def tg():
        try:
            from . import notify, bot
            s = notify._settings()
            token = (s.get("telegram_token") or "").strip()
            chats = [c.strip() for c in (s.get("telegram_chat_id") or "").split(",") if c.strip()]
            for c in chats:
                bot.send_message(token, c, message(url))
        except Exception:
            pass
    threading.Thread(target=tg, daemon=True).start()   # waits for the patient address
