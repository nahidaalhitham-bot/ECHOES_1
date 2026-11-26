"""Why didn't the safe-zone exit reach Telegram? Check every link in the chain.

exit detected -> alert recorded -> notification queued -> sent to Telegram.
Each check says what it found and, when it fails, exactly what to do.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from . import tunnel
from .db import connect
from .safety import haversine_m


def _age_text(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        sec = (datetime.now(timezone.utc) - t).total_seconds()
    except ValueError:
        return ts
    if sec < 90:
        return "قبل لحظات"
    if sec < 3600:
        return f"قبل {int(sec // 60)} دقيقة"
    if sec < 86400:
        return f"قبل {int(sec // 3600)} ساعة"
    return f"قبل {int(sec // 86400)} يوم"


def exit_alert() -> dict:
    checks: list[dict] = []

    def add(ok, title, detail="", fix=""):
        checks.append({"ok": ok, "title": title, "detail": detail, "fix": fix})

    demo = os.environ.get("ECHEOS_DEMO", "0") == "1"
    with connect() as conn:
        s = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM notif_settings")}
        zones = [dict(r) for r in conn.execute("SELECT * FROM safe_zones WHERE enabled=1")]
        dev = conn.execute(
            "SELECT d.*, MAX(l.id) AS last_id FROM devices d "
            "LEFT JOIN locations l ON l.device_id=d.id GROUP BY d.id "
            "ORDER BY (last_id IS NULL), last_id DESC LIMIT 1").fetchone()
        loc = conn.execute("SELECT * FROM locations WHERE id=?",
                           (dev["last_id"],)).fetchone() if dev and dev["last_id"] else None
        last_exit = conn.execute(
            "SELECT * FROM alerts WHERE kind='exited_safe_zone' ORDER BY id DESC LIMIT 1").fetchone()
        last_out = conn.execute(
            "SELECT * FROM notif_outbox ORDER BY id DESC LIMIT 1").fetchone()
        exit_out = conn.execute(
            "SELECT * FROM notif_outbox WHERE alert_id=? ORDER BY id DESC LIMIT 1",
            (last_exit["id"],)).fetchone() if last_exit else None

    if demo:
        add(None, "نسخة العرض المحاكية",
            "لها قاعدة بيانات خاصة تُعاد كل تشغيل. إعدادات تيليجرام تُنسخ تلقائيًا من نسختك الحقيقية إن وُجدت.",
            "إذا لم تُضبط تيليجرام في النسخة الحقيقية بعد: اضبطيها هنا من الإعدادات (تُمسح عند إعادة التشغيل) أو في النسخة الحقيقية.")

    # 1) channel + credentials
    channel = s.get("channel", "none")
    if channel not in ("telegram", "both") and s.get("telegram_token") and s.get("telegram_chat_id"):
        add(True, "تيليجرام مربوط — تنبيهات الأمان تُرسل له تلقائيًا",
            f"(القناة المختارة «{channel}»، ومع ذلك يُرسل تنبيه الخروج إلى تيليجرام أيضًا)")
    elif channel not in ("telegram", "both"):
        add(False, "قناة الإرسال ليست تيليجرام",
            f"القناة الحالية: «{channel}» — لذلك يُسجَّل التنبيه داخل التطبيق فقط.",
            "الإعدادات ← الإشعارات ← اختاري «Telegram» واحفظي. "
            "وإذا كنتِ ضبطتِ تيليجرام سابقًا في مجلد نسخة أقدم: أغلقي البرنامج وشغّلي "
            "import_old_data_windows.bat لنقل إعداداتك وبياناتك إلى هذا المجلد.")
    else:
        add(True, "قناة الإرسال: تيليجرام" + (" + البريد" if channel == "both" else ""))
    add(bool(s.get("telegram_token")), "رمز البوت (Bot Token)",
        "محفوظ" if s.get("telegram_token") else "غير موجود",
        "" if s.get("telegram_token") else "من تيليجرام افتحي @BotFather ← /newbot ← انسخي الرمز والصقيه في الإعدادات.")
    add(bool(s.get("telegram_chat_id")), "معرّف المحادثة (Chat ID)",
        s.get("telegram_chat_id") or "غير موجود",
        "" if s.get("telegram_chat_id") else "الإعدادات ← «ربط تيليجرام بضغطة» ← افتحي الرابط من جوالك واضغطي Start.")

    # 2) safe zone
    if not zones:
        add(False, "لا يوجد نطاق آمن",
            "بدون نطاق لا يوجد شيء «يخرج» منه المريض.",
            "صفحة الموقع والأمان ← حدّدي موقع المنزل ونصف القطر ← «حفظ النطاق».")
    else:
        z = zones[0]
        add(True, "النطاق الآمن", f"«{z['name']}» بنصف قطر {int(z['radius_m'])} م")

    # 3) device + latest location vs zone
    if not dev:
        add(False, "لا يوجد جهاز تتبع",
            "لا ساعة ولا جوال يرسل موقع المريض.",
            "حالة الجهاز ← اربطي الساعة أو جوال المريض.")
    elif not loc:
        add(False, f"الجهاز «{dev['name']}» لم يرسل أي موقع",
            "", "تأكدي أن تطبيق الساعة/صفحة الجوال مفتوحة ومسموح لها بالموقع.")
    else:
        sim = " (محاكاة)" if loc["simulated"] else ""
        add(True, f"آخر موقع من «{dev['name']}»{sim}", _age_text(loc["reported_at"]))
        if zones:
            z = zones[0]
            dist = haversine_m(loc["lat"], loc["lon"], z["lat"], z["lon"])
            from .safety import _margin
            acc = float(loc["accuracy_m"] or 0)
            need = z["radius_m"] + _margin(acc, z["radius_m"])
            if dist <= z["radius_m"]:
                add(None, "آخر موقع داخل النطاق الآمن",
                    f"يبعد {int(dist)} م عن مركز البيت (النطاق {int(z['radius_m'])} م).")
            elif dist <= need:
                add(False, "المريض خارج النطاق لكن دقة GPS ضعيفة",
                    f"يبعد {int(dist)} م، ودقة الموقع ±{int(acc)} م؛ لا يُعتبر الخروج مؤكدًا قبل {int(need)} م "
                    "(حتى لا تصل تنبيهات خاطئة).",
                    "انتظري حتى يبتعد أكثر أو تتحسن الإشارة (خارج المباني)، أو صغّري نصف قطر النطاق.")
            else:
                add(True, "آخر موقع خارج النطاق (خروج مؤكد)", f"يبعد {int(dist)} م عن مركز البيت.")
            if dist > 20000:
                add(False, "مركز النطاق الآمن بعيد جدًا عن المريض",
                    f"مركز «{z['name']}» يبعد {int(dist/1000)} كم عن آخر موقع — غالبًا ما زال على الموقع الافتراضي.",
                    "صفحة الموقع والأمان ← حدّدي موقع المنزل الحقيقي ← «حفظ النطاق».")

    # 4) was an exit recorded, and what happened to its message?
    if not last_exit:
        add(False, "لم يُسجَّل أي خروج من النطاق",
            "التطبيق لم يرصد خروجًا بعد — راجعي بنود النطاق والموقع أعلاه.",
            "للتجربة: صفحة الموقع والأمان ← «محاكاة الخروج من المنزل».")
    else:
        add(True, "آخر خروج مسجّل", f"{last_exit['message']} — {_age_text(last_exit['created_at'])}")
        if not exit_out:
            add(False, "لم تُرسل رسالة لهذا الخروج",
                "سُجّل التنبيه لكن لم تُجرَّب أي رسالة له.",
                "أعيدي تشغيل البرنامج ثم جرّبي «محاكاة الخروج» مرة أخرى.")
        elif exit_out["delivered"]:
            add(True, "وصلت رسالة الخروج إلى تيليجرام ✓", _age_text(exit_out["created_at"]))
        else:
            add(False, "حاول التطبيق الإرسال لكن فشل", exit_out["detail"] or "",
                _fix_for(exit_out["detail"] or ""))

    if last_out and (not exit_out or last_out["id"] != exit_out["id"]) and not last_out["delivered"]:
        add(False, "آخر محاولة إرسال (أي تنبيه) فشلت", last_out["detail"] or "",
            _fix_for(last_out["detail"] or ""))

    # 5) public link (only affects the link inside the message)
    url = tunnel.public_base()
    add(True if url else None, "الرابط العام للموقع المباشر",
        url or "غير جاهز — الرسالة ستحمل رابط خرائط جوجل بدلًا منه",
        "" if url else "للرابط المباشر شغّلي run_public_windows.bat مع اتصال إنترنت.")

    first_fail = next((c for c in checks if c["ok"] is False), None)
    return {"checks": checks,
            "verdict": first_fail["title"] if first_fail else "كل البنود سليمة",
            "fix": first_fail["fix"] if first_fail else
            "جرّبي «محاكاة الخروج من المنزل» أو «إرسال رسالة تجريبية» من الإعدادات."}


def _fix_for(detail: str) -> str:
    d = detail.lower()
    if "no channel" in d:
        return "الإعدادات ← الإشعارات ← اختاري Telegram وأدخلي الرمز والمعرّف."
    if "missing_bot_token" in d or "credentials are missing" in d:
        return "أدخلي رمز البوت ومعرّف المحادثة في الإعدادات."
    if "missing_chat_id" in d or "chat not found" in d or "400" in d:
        return "معرّف المحادثة غير صحيح: افتحي البوت واضغطي Start ثم أعيدي كتابة المعرّف."
    if "unauthorized" in d or "401" in d or "404" in d:
        return "رمز البوت غير صحيح: انسخيه كاملًا من @BotFather."
    if "blocked" in d or "403" in d:
        return "البوت محظور أو لم تضغطي Start: افتحي البوت في تيليجرام واضغطي Start."
    if "urlerror" in d or "urlopen" in d or "timed out" in d or "network" in d or "name or service" in d:
        return "لا يوجد اتصال إنترنت على الكمبيوتر وقت الإرسال، أو تيليجرام محجوب على الشبكة."
    return "جرّبي «إرسال رسالة تجريبية» من الإعدادات لرؤية الخطأ بالتفصيل."
