"""Full simulated (fictional) data for presenting ECHOES.

Used only when the app is started in demo mode (run_demo.py /
run_demo_windows.bat). It uses its OWN database and uploads folder, so it
never touches the family's real data.

Everything here is invented: the patient «سعد بن عبدالرحمن», his family,
places, memories, conversations, alerts and the location trail.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from . import auth, investigate, media, network, vision
from .db import connect

DEMO_EMAIL = "demo@echoes.app"
DEMO_PASSWORD = "Echoes2026"

HOME = (24.8090, 46.6200)          # fictional home, north Riyadh
MOSQUE = (24.8106, 46.6215)        # ~220 m away, inside the safe zone
PARK = (24.8142, 46.6262)          # ~850 m away, outside it

DEMO_IMAGES_DIR = Path(__file__).resolve().parent.parent / "demo_images"


# ------------------------------------------------------------ pictures ----
# Drawn illustrations with rich texture so the camera's scene matcher (SIFT)
# can recognise them when you show them on a phone/screen in front of it.

def _texture(h, w, seed):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8)
    base = cv2.resize(base, (w, h), interpolation=cv2.INTER_NEAREST)
    noise = rng.integers(0, 60, (h, w, 3), dtype=np.uint8)
    return cv2.addWeighted(base, 0.35, noise, 0.65, 0)


def _sofa_image():
    h, w = 600, 800
    img = _texture(h, w, 11)
    img[:] = cv2.addWeighted(img, 0.3, np.full_like(img, (200, 220, 235)), 0.7, 0)   # wall
    cv2.rectangle(img, (0, 430), (w, h), (60, 90, 140), -1)                        # rug floor
    rng = np.random.default_rng(3)
    for _ in range(140):                                                          # rug pattern
        x, y = int(rng.integers(0, w)), int(rng.integers(440, h))
        cv2.circle(img, (x, y), int(rng.integers(3, 12)), (int(rng.integers(20, 200)), 40, 160), -1)
    green = (60, 130, 70)
    cv2.rectangle(img, (120, 230), (680, 330), (45, 105, 55), -1)                  # back
    cv2.rectangle(img, (120, 320), (680, 420), green, -1)                          # seat
    cv2.rectangle(img, (90, 260), (160, 440), (40, 95, 50), -1)                    # arms
    cv2.rectangle(img, (640, 260), (710, 440), (40, 95, 50), -1)
    for x in (230, 400, 570):                                                     # cushions
        cv2.ellipse(img, (x, 300), (70, 45), 0, 0, 360, (90, 160, 210), -1)
        for k in range(0, 360, 30):
            cv2.ellipse(img, (x, 300), (50 - k % 20, 30), k, 0, 180, (30, 60, 150), 2)
    cv2.rectangle(img, (520, 60), (720, 200), (30, 30, 30), 6)                     # frame on wall
    img[66:194, 526:714] = _texture(128, 188, 99)
    return img


def _cup_image():
    h, w = 600, 800
    img = _texture(h, w, 21)
    img[:] = cv2.addWeighted(img, 0.4, np.full_like(img, (40, 70, 120)), 0.6, 0)   # wooden tray
    for y in range(0, h, 18):
        cv2.line(img, (0, y), (w, y + 10), (30, 55, 95), 2)
    cv2.ellipse(img, (400, 330), (250, 120), 0, 0, 360, (200, 170, 60), -1)         # brass tray
    cv2.ellipse(img, (400, 330), (250, 120), 0, 0, 360, (90, 70, 20), 4)
    for k in range(12):
        cv2.ellipse(img, (400, 330), (230 - k * 6, 110 - k * 3), 0, k * 15, k * 15 + 200, (120, 90, 30), 1)
    cv2.ellipse(img, (330, 300), (60, 22), 0, 0, 360, (250, 250, 250), -1)          # white cup
    cv2.rectangle(img, (272, 300), (388, 370), (245, 245, 245), -1)
    cv2.ellipse(img, (330, 370), (58, 18), 0, 0, 180, (235, 235, 235), -1)
    cv2.ellipse(img, (330, 300), (52, 16), 0, 0, 360, (40, 90, 150), -1)            # coffee
    for x in range(280, 385, 12):
        cv2.line(img, (x, 320), (x + 6, 360), (60, 140, 200), 2)                    # gold pattern
    cv2.ellipse(img, (500, 290), (40, 70), 0, 0, 360, (60, 160, 200), -1)           # dallah
    cv2.rectangle(img, (470, 200), (530, 260), (60, 160, 200), -1)
    cv2.line(img, (530, 230), (600, 200), (60, 160, 200), 10)
    for _ in range(20):                                                            # dates
        rng = np.random.default_rng(_)
        cv2.ellipse(img, (int(rng.integers(150, 650)), int(rng.integers(400, 440))), (16, 9),
                    int(rng.integers(0, 180)), 0, 360, (20, 40, 90), -1)
    return img


def _farm_image():
    h, w = 600, 800
    img = np.zeros((h, w, 3), np.uint8)
    for y in range(300):                                                           # sky
        img[y, :] = (235 - y // 3, 200 - y // 6, 140)
    img[300:] = _texture(300, w, 31)
    img[300:] = cv2.addWeighted(img[300:], 0.4, np.full((300, w, 3), (90, 160, 200), np.uint8), 0.6, 0)  # sand
    rng = np.random.default_rng(5)
    for x in range(60, 780, 110):                                                  # palm trees
        top = int(rng.integers(120, 180))
        cv2.line(img, (x, 470), (x + 10, top), (40, 70, 100), 14)
        for a in range(0, 360, 40):
            dx, dy = int(70 * np.cos(np.radians(a))), int(40 * np.sin(np.radians(a)))
            cv2.line(img, (x + 10, top), (x + 10 + dx, top + dy + 25), (40, 120, 40), 6)
    cv2.rectangle(img, (520, 360), (700, 470), (150, 190, 220), -1)                # mud house
    cv2.rectangle(img, (585, 400), (625, 470), (60, 80, 110), -1)
    for x in range(530, 700, 22):
        cv2.rectangle(img, (x, 350), (x + 12, 362), (130, 170, 200), -1)
    cv2.line(img, (0, 520), (w, 500), (180, 130, 60), 8)                            # water channel
    return img


def _avatar(seed: int, bg, robe, headwear: str, beard: bool, older: bool) -> np.ndarray:
    """A simple drawn avatar (not a photo of a real person)."""
    s = 400
    img = np.full((s, s, 3), bg, np.uint8)
    for r in range(200, 0, -20):                                     # soft halo
        cv2.circle(img, (200, 170), r, tuple(min(255, c + (200 - r) // 6) for c in bg), -1)
    skin = (150, 185, 225) if seed % 2 else (130, 170, 210)
    cv2.ellipse(img, (200, 400), (150, 110), 0, 180, 360, robe, -1)        # shoulders
    cv2.circle(img, (200, 175), 75, skin, -1)                             # face
    if headwear == "shemagh":
        pts = np.array([[110, 160], [200, 70], [290, 160], [310, 330], [90, 330]], np.int32)
        cv2.fillPoly(img, [pts], (245, 245, 245))
        for x in range(120, 290, 18):
            for y in range(90, 320, 18):
                if cv2.pointPolygonTest(pts, (x, y), False) > 0:
                    cv2.circle(img, (x, y), 3, (40, 40, 200), -1)
        cv2.circle(img, (200, 185), 62, skin, -1)
        cv2.ellipse(img, (200, 112), (82, 18), 0, 0, 360, (20, 20, 20), 7)      # agal
    elif headwear == "hijab":
        cv2.ellipse(img, (200, 190), (100, 120), 0, 0, 360, robe, -1)
        cv2.circle(img, (200, 185), 60, skin, -1)
    elif headwear == "child":
        cv2.ellipse(img, (200, 125), (80, 45), 0, 180, 360, (30, 40, 60), -1)   # hair
        cv2.circle(img, (200, 180), 62, skin, -1)
        cv2.ellipse(img, (200, 120), (70, 30), 0, 180, 360, (30, 40, 60), -1)
    for x in (175, 225):                                              # eyes
        cv2.circle(img, (x, 175), 7, (40, 30, 30), -1)
        if older:
            cv2.ellipse(img, (x, 175), (18, 13), 0, 0, 360, (80, 80, 80), 2)    # glasses
    if older:
        cv2.line(img, (193, 175), (207, 175), (80, 80, 80), 2)
    cv2.ellipse(img, (200, 210), (22, 10), 0, 0, 180, (60, 60, 140), 3)      # smile
    if beard:
        col = (225, 225, 225) if older else (40, 40, 40)
        cv2.ellipse(img, (200, 220), (55, 42), 0, 0, 180, col, -1)
        cv2.ellipse(img, (200, 212), (24, 8), 0, 0, 180, (60, 60, 140), 3)
    return img


AVATARS = {   # person name -> drawing parameters
    "__patient__": (1, (200, 170, 150), (230, 230, 230), "shemagh", True, True),
    "منيرة": (2, (190, 160, 210), (60, 40, 90), "hijab", False, True),
    "فهد": (3, (170, 200, 160), (235, 235, 235), "shemagh", True, False),
    "نورة": (4, (210, 180, 170), (110, 60, 130), "hijab", False, False),
    "ريم": (5, (150, 210, 230), (120, 90, 220), "child", False, False),
    "خالد": (6, (160, 190, 210), (235, 235, 235), "shemagh", True, True),
}


def _jpeg(img) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


# ---------------------------------------------------------------- data ----

PEOPLE = [
    ("منيرة", "زوجتك", "أم فهد، تطبخ لك الجريش كل جمعة",
     "تزوجتما في الطائف سنة 1972"),
    ("فهد", "ابنك الأكبر", "فهد مهندس ويزورك كل يوم بعد العصر",
     "يحب يلعب معك الشطرنج"),
    ("نورة", "ابنتك", "نورة معلمة مثلك وتتصل عليك كل مساء",
     "ساعدتك في زراعة الحديقة"),
    ("ريم", "حفيدتك", "ريم بنت فهد، عمرها ثمان سنوات وتحب تسمع قصصك",
     ""),
    ("خالد", "أخوك", "خالد أخوك الأصغر، كنتم تزرعون النخيل معًا في الخرج",
     ""),
]

PROFILE = {
    "full_name": "سعد بن عبدالرحمن",
    "age": 76,
    "home_address": "حي الملقا، الرياض (عنوان وهمي للعرض)",
    "medical_info": "ارتفاع ضغط الدم، مرحلة مبكرة من الزهايمر (بيانات وهمية)",
    "allergies": "حساسية من البنسلين",
    "emergency_notes": "عند الارتباك الشديد: تواصل مع فهد أولًا ثم نورة",
    "important_info": "يرتاح عند سماع القرآن من الراديو القديم. يحب أن يُنادى «أبو فهد».",
    "routine": ("يصلي الفجر في مسجد الحي ثم يشرب القهوة العربية في فنجانه الأبيض. "
                "يقرأ الجريدة بعد الفطور. يمشي في الحديقة القريبة بعد العصر مع فهد"),
    "preferences": "يحب الهدوء، والقهوة بالهيل، ولا يحب الأصوات العالية",
    "memories": ("كان يجلس على الكنبة الخضراء في الصالة مع أطفاله كل مساء ويحكي لهم القصص. "
                 "سافر مع منيرة إلى مكة لأداء العمرة سنة 1995. "
                 "علّم الرياضيات ثلاثين سنة في مدرسة الملقا"),
    "reminder_scope": "أوقات الصلاة، مواعيد الدواء، أسماء المقربين عند رؤيتهم، تنبيهات السلامة",
}

EXTRA = {
    "nickname": "أبو فهد",
    "date_of_birth": "1950-04-12",
    "language": "ar",
    "medical_instructions": ("قياس الضغط صباحًا. عدم تركه وحده قرب الفرن. "
                             "عند الارتباك: كلّمه بهدوء وذكّره باسم من حوله (تعليمات وهمية للعرض)"),
    "gender": "ذكر",
    "dialect": "نجدي",
    "birthplace": "الطائف",
    "childhood": ("كبر في الطائف بين مزارع الورد. "
                  "كان يساعد أباه في قطف الورد الطائفي كل ربيع"),
    "occupation": "معلم رياضيات متقاعد",
    "education": "بكالوريوس رياضيات",
    "life_events": ("تزوج منيرة في الطائف سنة 1972. "
                    "وُلد ابنه فهد سنة 1975. "
                    "اشترى مزرعة الخرج مع أخيه خالد سنة 1988. "
                    "تقاعد من التدريس سنة 2010"),
    "hobbies": "الزراعة، الشطرنج، صيد السمك",
    "favourite_activities": "المشي بعد العصر، سقي النخل",
    "favourite_foods": "الجريش، التمر السكري",
    "favourite_drinks": "القهوة العربية بالهيل",
    "favourite_music": "القرآن الكريم، الشعر النبطي",
    "favourite_places": "مكة، الطائف، مزرعة الخرج",
    "favourite_topics": "الزراعة، أيام التدريس",
    "comfort_items": "المسبحة، الراديو القديم",
    "confusion_triggers": "الأماكن المزدحمة، المساء المتأخر",
    "medications": "دواء الضغط (وهمي)",
    "medication_schedule": "حبة بعد الفطور",
    "mobility": "يمشي بدون مساعدة لمسافات قصيرة",
    "phone": "0500000000",
    "allergy_items": "الفول السوداني، الموز",
    "danger_items": "سكين، مقص، الفرن، الولاعة، باب الشارع",
    "private_topics": "الورث، الأمور المالية",
    "home_lat": HOME[0], "home_lon": HOME[1],
}

MEMORIES = [
    ("place", "البيت", "تعيش في بيتك في حي الملقا مع منيرة"),
    ("place", "مسجد الحي", "تصلي الفجر في مسجد الحي القريب من البيت"),
    ("place", "مزرعة الخرج", "مزرعتك مع أخيك خالد، زرعتما فيها خمسين نخلة"),
    ("routine", "قهوة الصباح", "تشرب القهوة العربية بعد صلاة الفجر"),
    ("fact", "الشطرنج", "تلعب الشطرنج مع فهد وتفوز عليه غالبًا"),
]

PLACES = [
    ("مسجد الحي", "المسجد القريب من البيت، يصلي فيه الفجر"),
    ("مزرعة الخرج", "مزرعة العائلة، فيها نخيل وبيت طين قديم"),
    ("الحديقة القريبة", "يمشي فيها بعد العصر مع فهد"),
]

PHOTOS = [   # (image fn, category, title, description, related_to, function)
    (_sofa_image, "place", "الكنبة الخضراء في الصالة",
     "كان يجلس على الكنبة الخضراء مع أطفاله كل مساء ويحكي لهم القصص",
     "فهد، نورة", "مكان الجلسة العائلية"),
    (_cup_image, "object", "فنجان القهوة الأبيض",
     "الفنجان الذي يشرب فيه القهوة العربية بعد صلاة الفجر",
     "منيرة", "يشرب فيه القهوة كل صباح"),
    (_farm_image, "place", "مزرعة الخرج",
     "زرع النخيل في مزرعة الخرج مع أخيه خالد",
     "خالد", "مزرعة العائلة"),
]

# (hours ago, role, text, basis)
CHAT = [
    (50, "user", "يا إيكوس من فهد؟", None),
    (50, "assistant", "فهد ابنك الأكبر، يزورك كل يوم بعد العصر.", "people"),
    (30, "user", "تتذكر يوم سافرت مع منيرة إلى مكة؟", "heard"),
    (30, "assistant", "سافر مع منيرة إلى مكة لأداء العمرة سنة 1995.", "network"),
    (26, "user", "فهد بيجي اليوم العصر ويلعب معك شطرنج", "heard"),
    (26, "assistant", "تتذكر فهد؟ يحب يلعب معك الشطرنج.", "companion:reminder"),
    (6, "user", "وش رأيك نروح مزرعة الخرج الجمعة؟", "heard"),
    (5, "user", "كم الورث اللي عندك؟", "heard:private"),
    (2, "user", "يا إيكوس وش اسم زوجتي؟", None),
    (2, "assistant", "زوجتك منيرة، أم فهد.", "people"),
]

# (hours ago, kind, message, lat, lon, read)
ALERTS = [
    (49, "exited_safe_zone", "خرج سعد من نطاق المنزل الآمن باتجاه الحديقة.", PARK[0], PARK[1], True),
    (28, "allergen_contact", "الكاميرا رأت سعد يلمس/يتناول «موز» وهو مسجّل ضمن الأشياء التي يتحسس منها (الموز).",
     HOME[0], HOME[1], True),
    (3, "danger_contact", "الكاميرا رأت سعد قريبًا جدًا من «سكين» أو يمسكه — شيء مسجّل كخطر.",
     HOME[0], HOME[1], False),
]

# Web cards (offline, general knowledge) so the board shows the internet link
WEB = [
    ("مكة", "🌐 مكة المكرمة", "أقدس مدن الإسلام، وفيها المسجد الحرام والكعبة المشرفة، ويقصدها المسلمون للحج والعمرة."),
    ("الطائف", "🌐 الطائف", "مدينة جبلية في منطقة مكة المكرمة، تشتهر بالورد الطائفي واعتدال مناخها صيفًا."),
    ("مزرعة الخرج", "🌐 الخرج", "محافظة جنوب الرياض تشتهر بالزراعة ومزارع النخيل."),
]

AI_LINKS = [   # simulated AI suggestions (dashed on the board)
    ("الطائف", "مكان الزواج", "تزوج منيرة في الطائف سنة 1972", "منيرة"),
    ("فهد", "يلعب مع", "تلعب الشطرنج مع فهد", "الشطرنج"),
]


def _ago(hours: float) -> str:
    return (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def copy_real_settings() -> int:
    """Copy the family's Telegram / e-mail / AI settings from the real
    installation, so demo alerts really arrive. Both use the same
    app/.secret_key, so the encrypted tokens stay valid. Read-only on the
    real database."""
    import os
    import sqlite3
    from .db import DB_PATH
    real = Path(__file__).resolve().parent.parent / "echeos.db"
    if not real.exists() or real.resolve() == Path(DB_PATH).resolve():
        return 0
    n = 0
    try:
        src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        notif = src.execute("SELECT key, value FROM notif_settings").fetchall()
        ai_rows = src.execute("SELECT key, value FROM assistant_settings "
                              "WHERE key LIKE 'ai_%' OR key='reply_delay'").fetchall()
        src.close()
    except Exception:
        return 0
    with connect() as conn:
        for r in notif:
            conn.execute("INSERT OR REPLACE INTO notif_settings(key,value) VALUES (?,?)",
                         (r["key"], r["value"]))
            n += 1
        for r in ai_rows:
            conn.execute("INSERT OR REPLACE INTO assistant_settings(key,value) VALUES (?,?)",
                         (r["key"], r["value"]))
    return n


def seed_full_demo(auto_build, patient_memory_id) -> None:
    """Fill a fresh demo database. `auto_build` / `patient_memory_id` are
    passed in from main to avoid a circular import."""
    try:   # the demo account always exists in demo mode (even beside a real owner)
        auth.create_user(DEMO_EMAIL, DEMO_PASSWORD, "عرض ECHOES", "owner")
    except Exception:
        pass
    copy_real_settings()

    with connect() as conn:
        for name, rel, pref, notes in PEOPLE:
            conn.execute("INSERT OR IGNORE INTO people(name,relation,preferred,notes) "
                         "VALUES (?,?,?,?)", (name, rel, pref, notes))
        for kind, subject, fact in MEMORIES:
            conn.execute("INSERT INTO memories(kind,subject,fact) VALUES (?,?,?)",
                         (kind, subject, fact))
        for name, desc in PLACES:
            conn.execute("INSERT OR IGNORE INTO places(name,description) VALUES (?,?)",
                         (name, desc))

        cols = ", ".join(["id"] + list(PROFILE))
        conn.execute(f"INSERT OR REPLACE INTO patient_profile({cols}) VALUES "
                     f"({', '.join('?' * (len(PROFILE) + 1))})", [1] + list(PROFILE.values()))
        have = {r["name"] for r in conn.execute("PRAGMA table_info(patient_profile_extra)")}
        ex = {k: v for k, v in EXTRA.items() if k in have}
        conn.execute(f"INSERT OR REPLACE INTO patient_profile_extra(patient_id, {', '.join(ex)}) "
                     f"VALUES (1, {', '.join('?' * len(ex))})", list(ex.values()))

        conn.execute("INSERT INTO caregivers(full_name,relation,phone,email,is_primary) VALUES "
                     "('فهد سعد (وهمي)','الابن','0500000001','fahad@example.com',1)")
        conn.execute("INSERT INTO caregivers(full_name,relation,phone,email,is_primary) VALUES "
                     "('نورة سعد (وهمي)','الابنة','0500000002','noura@example.com',0)")

        # simulated bracelet + safe zone + a walk trail over the last hours
        conn.execute("INSERT OR IGNORE INTO devices(name,kind,simulated,connected,battery,last_seen_at) "
                     "VALUES ('قلادة الصدى (محاكاة)','simulator',1,1,78,datetime('now'))")
        dev = conn.execute("SELECT id FROM devices ORDER BY id LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO safe_zones(name,lat,lon,radius_m) VALUES ('المنزل',?,?,300)", HOME)
        trail = []
        # two days ago: walked out to the park (left the zone), then home
        for i in range(9):
            t = i / 8
            trail.append((50 - i * 0.15, HOME[0] + (PARK[0] - HOME[0]) * t,
                          HOME[1] + (PARK[1] - HOME[1]) * t))
        for i in range(9):
            t = 1 - i / 8
            trail.append((48.5 - i * 0.15, HOME[0] + (PARK[0] - HOME[0]) * t,
                          HOME[1] + (PARK[1] - HOME[1]) * t))
        # today: fajr at the mosque and back, then at home
        for i in range(6):
            t = i / 5
            trail.append((10 - i * 0.1, HOME[0] + (MOSQUE[0] - HOME[0]) * t,
                          HOME[1] + (MOSQUE[1] - HOME[1]) * t))
        for i in range(6):
            t = 1 - i / 5
            trail.append((9 - i * 0.1, HOME[0] + (MOSQUE[0] - HOME[0]) * t,
                          HOME[1] + (MOSQUE[1] - HOME[1]) * t))
        for h in (6, 4, 2, 1, 0.5, 0.05):
            trail.append((h, HOME[0] + 0.00005, HOME[1] - 0.00004))
        for h, lat, lon in trail:
            conn.execute("INSERT INTO locations(device_id,lat,lon,accuracy_m,reported_at,simulated) "
                         "VALUES (?,?,?,?,?,1)", (dev, round(lat, 6), round(lon, 6), 12, _ago(h)))

        for h, kind, msg, lat, lon, read in ALERTS:
            conn.execute("INSERT INTO alerts(kind,message,device_id,lat,lon,location_at,created_at,"
                         "read_at,dedupe_key) VALUES (?,?,?,?,?,?,?,?,?)",
                         (kind, msg, dev, lat, lon, _ago(h), _ago(h),
                          _ago(h - 0.2) if read else None, f"demo:{kind}:{h}"))

        for h, role, text, basis in CHAT:
            conn.execute("INSERT INTO chat_log(role,content,basis,created_at) VALUES (?,?,?,?)",
                         (role, text, basis, _ago(h)))

        today = datetime.now()
        for kind, title, detail, due in [
            ("medication", "دواء الضغط", "حبة واحدة بعد الفطور", today.replace(hour=8, minute=0)),
            ("routine", "المشي مع فهد", "في الحديقة القريبة بعد العصر", today.replace(hour=16, minute=30)),
            ("appointment", "موعد عيادة الذاكرة", "الدور الثالث (وهمي)",
             (today + timedelta(days=2)).replace(hour=10, minute=30)),
            ("event", "زيارة مزرعة الخرج", "مع خالد وفهد",
             (today + timedelta(days=4)).replace(hour=9, minute=0)),
        ]:
            conn.execute("INSERT INTO reminders(kind,title,detail,due_at) VALUES (?,?,?,?)",
                         (kind, title, detail, due.strftime("%Y-%m-%dT%H:%M")))

    # drawn avatars for the patient and his family (profile & family pages)
    for name, args in AVATARS.items():
        data = _jpeg(_avatar(*args))
        if name == "__patient__":
            info = media.save_photo("patient", 1, data)
            with connect() as conn:
                conn.execute("UPDATE patient_profile SET photo_path=? WHERE id=1",
                             (info["filename"],))
        else:
            with connect() as conn:
                row = conn.execute("SELECT id FROM people WHERE name=?", (name,)).fetchone()
            if row:
                media.save_photo("person", row["id"], data)

    # photos the camera can recognise (also saved to demo_images/ to show it)
    DEMO_IMAGES_DIR.mkdir(exist_ok=True)
    mem_id = patient_memory_id()
    for i, (fn, cat, title, desc, related, func) in enumerate(PHOTOS, 1):
        data = _jpeg(fn())
        (DEMO_IMAGES_DIR / f"{i}_{cat}.jpg").write_bytes(data)
        info = media.save_album_photo(mem_id, data)
        with connect() as conn:
            conn.execute("INSERT OR REPLACE INTO media_annotations(media_type,media_id,category,"
                         "title,description,related_to,function_text) VALUES ('photo',?,?,?,?,?,?)",
                         (info["id"], cat, title, desc, related, func))
        desc_vec = vision.scene_descriptor(data)
        if desc_vec:
            with connect() as conn:
                conn.execute("INSERT OR REPLACE INTO scene_embeddings(photo_id,memory_id,label,"
                             "descriptor) VALUES (?,?,?,?)",
                             (info["id"], mem_id, title, json.dumps(desc_vec)))

    # the investigator board: evidence + conversations (offline), then the
    # simulated internet cards and AI suggestions
    auto_build()
    investigate.run(use_web=False, use_ai=False)
    with connect() as conn:
        labels = {r["label"]: r["id"] for r in conn.execute("SELECT id,label FROM nodes")}
    for anchor, title, text in WEB:
        if anchor in labels:
            wid = network.upsert_node("web", title, text + "\n(بطاقة محاكاة للعرض)", source="web")
            network.link(labels[anchor], "معلومة من الإنترنت", wid, "ويكيبيديا (محاكاة)", source="web")
    for a, rel, reason, b in AI_LINKS:
        ida = labels.get(a)
        idb = labels.get(b) or next((v for k, v in labels.items() if b in k), None)
        if ida and idb:
            network.link(ida, rel, idb, f"اقتراح الذكاء الاصطناعي (محاكاة): {reason}", source="ai")
