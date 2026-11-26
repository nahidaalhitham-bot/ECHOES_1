"""The companion brain: what the watch says, and when it alerts the family.

It ties three inputs to the memory network:
  - what the camera sees (faces, the family's photographed places/objects,
    everyday objects from the local detector or the AI vision model);
  - what the microphone hears (speech turned into text in the browser);
  - the caregiver's safety lists (allergies, dangerous things, private topics).

Rules:
- A reminder is spoken only when a memory written by the family actually
  mentions the thing in front of the patient. No memory -> silence.
- Every reminder / alert has a cool-down so the patient is not nagged.
- Allergy / danger contact sends a family notification immediately.
- When answering on the patient's behalf (after 13 s of silence), very
  personal information is never spoken.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone

from . import ai, notify, objects
from .db import connect

PATIENT_MEMORY_SUBJECT = "__patient_memories__"

# Profile fields that may be used for memory reminders (never medical/contact).
MEMORY_FIELDS_BASE = {
    "routine": "الروتين اليومي", "memories": "الذكريات المهمة",
    "important_info": "معلومات مهمة", "preferences": "التفضيلات",
}
MEMORY_FIELDS_EXTRA = {
    "childhood": "ذكريات الطفولة", "life_events": "أحداث الحياة",
    "occupation": "المهنة", "hobbies": "الهوايات",
    "favourite_activities": "الأنشطة المفضلة", "favourite_foods": "الأطعمة المفضلة",
    "favourite_drinks": "المشروبات المفضلة", "favourite_music": "الموسيقى المفضلة",
    "favourite_places": "الأماكن المفضلة", "favourite_topics": "مواضيع مفضلة",
    "comfort_items": "ما يريحه", "birthplace": "مكان الولادة",
}

# Never spoken on the patient's behalf.
PRIVATE_KEYWORDS = (
    "دواء", "ادوية", "أدوية", "علاج", "مرض", "مريض", "حساسية", "تشخيص", "سكر",
    "ضغط", "زهايمر", "الزهايمر", "مستشفى", "طبيب", "دكتور",
    "عنوان", "ساكن", "تسكن", "يسكن", "رقم", "جوال", "جوالك", "تلفون", "هاتف",
    "فلوس", "راتب", "حساب", "بنك", "بطاقة", "رصيد", "ديون", "دين", "ورث", "ميراث",
    "هوية", "جواز", "سجل", "رقم سري", "باسورد", "كلمة المرور", "كلمة السر",
    "الرمز", "مفتاح", "خزنة", "موقع", "وينه", "وين ساكن",
    "دوا", "حبوب", "إبرة", "ابرة", "صحة", "صحتك", "عملية", "تحاليل",
)

QUESTION_STARTS = (
    "هل", "وش", "ايش", "إيش", "شو", "متى", "وين", "أين", "اين", "كيف", "ليش",
    "لماذا", "مين", "من هو", "من هي", "كم", "تذكر", "تتذكر", "تعرف", "ماذا",
    "ما هو", "ما هي", "ما اسم", "وشو", "شنو", "فين", "منو", "أي", "اي",
)

WAKE_WORDS = ("يا إيكوس", "يا ايكوس", "إيكوس", "ايكوس", "ايكو", "إيكو", "echoes", "يا صدى")


# --------------------------------------------------------------- helpers ---

_DIAC = re.compile(r"[ً-ْـ]")


def norm(s: str) -> str:
    s = _DIAC.sub("", (s or "").lower())
    s = re.sub("[أإآ]", "ا", s)
    return s.replace("ة", "ه").replace("ى", "ي")


def split_items(text: str) -> list[str]:
    parts = re.split(r"[،,;\n؛]+|\s+-\s+", text or "")
    return [p.strip(" .-•") for p in parts if p.strip(" .-•")]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.\n!؟?]+", text or "") if len(s.strip()) > 3]


def mentions(text: str, terms: list[str]) -> bool:
    t = " " + norm(text) + " "
    for term in terms:
        n = norm(term).strip()
        if len(n) < 2:
            continue
        # whole word, allowing the Arabic article / common prefixes
        if re.search(r"(?:^|[\s،,.])(?:ال|وال|بال|لل|و|ب|ل|ف)?" + re.escape(n)
                     + r"(?:ه|ها|هم|ات|ين|ك|ي|كم|نا|ته|تك|يه)?(?=$|[\s،,.؟?!])", t):
            return True
    return False


def _cfg(conn, key, default=""):
    row = conn.execute("SELECT value FROM assistant_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _extra() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM patient_profile_extra WHERE patient_id=1").fetchone()
    return dict(row) if row else {}


def _profile() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM patient_profile WHERE id=1").fetchone()
    return dict(row) if row else {}


def patient_name() -> str:
    p = _profile()
    return (p.get("full_name") or "").strip()


# ------------------------------------------------------------ cool-downs ---

def allow(key: str, seconds: int) -> bool:
    """True (and records now) if `key` did not fire in the last `seconds`."""
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM companion_events WHERE key=? AND "
            "last_at >= datetime('now', ?)", (key, f"-{int(seconds)} seconds")).fetchone()
        if row:
            return False
        conn.execute("INSERT INTO companion_events(key,last_at) VALUES (?,datetime('now')) "
                     "ON CONFLICT(key) DO UPDATE SET last_at=datetime('now')", (key,))
    return True


# ------------------------------------------------------------ watch lists --

def watch_lists() -> dict:
    e = _extra()
    p = _profile()
    allergy = split_items(e.get("allergy_items", ""))
    # the older free-text «الحساسية» field also counts
    allergy += [x for x in split_items(p.get("allergies", "") or "") if len(x) <= 30]
    danger = split_items(e.get("danger_items", ""))
    private = split_items(e.get("private_topics", ""))
    return {"allergy": list(dict.fromkeys(allergy)),
            "danger": list(dict.fromkeys(danger)),
            "private": private}


# --------------------------------------------------------- memory corpus ---

def corpus() -> list[dict]:
    """Every memory sentence the family wrote, with where it came from."""
    out: list[dict] = []
    p, e = _profile(), _extra()
    for k, label in MEMORY_FIELDS_BASE.items():
        for s in sentences(p.get(k) or ""):
            out.append({"source": f"profile:{k}", "title": label, "text": s})
    for k, label in MEMORY_FIELDS_EXTRA.items():
        for s in sentences(e.get(k) or ""):
            out.append({"source": f"extra:{k}", "title": label, "text": s})
    with connect() as conn:
        for m in conn.execute("SELECT * FROM memories WHERE subject != ?",
                              (PATIENT_MEMORY_SUBJECT,)):
            out.append({"source": f"memories:{m['id']}", "title": m["subject"],
                        "text": f"{m['fact']}", "subject": m["subject"]})
        for a in conn.execute("SELECT * FROM media_annotations"):
            txt = " ".join(x for x in (a["description"], a["function_text"]) if x)
            if txt or a["title"]:
                out.append({"source": f"media:{a['media_type']}:{a['media_id']}",
                            "title": a["title"] or "", "subject": a["title"] or "",
                            "text": txt or a["title"],
                            "related": a["related_to"] or ""})
        for n in conn.execute("SELECT * FROM nodes WHERE kind != 'web'"):
            for sent in sentences(n["detail"] or ""):
                out.append({"source": f"node:{n['id']}", "title": n["label"],
                            "subject": n["label"], "text": sent})
        for pe in conn.execute("SELECT * FROM people"):
            txt = " ".join(x for x in (pe["preferred"], pe["notes"]) if x)
            out.append({"source": f"people:{pe['id']}", "title": pe["name"],
                        "subject": pe["name"], "text": f"{pe['name']} {pe['relation']}. {txt}"})
    seen, uniq = set(), []
    for row in out:
        k = norm(row["text"])
        if k and k not in seen:
            seen.add(k)
            uniq.append(row)
    return uniq


_NO_POSSESSIVE = {"الله", "والله", "وجه", "اتجاه", "مياه", "شبه", "انتبه", "فاكهه", "كره",
                  # prepositions usually point at the thing, not at him: "يشرب فيه"
                  "فيه", "به", "منه", "عليه", "اليه", "عنه", "له", "معه"}


def to_second_person(text: str) -> str:
    """Family notes describe the patient ('كان يجلس مع أطفاله'); the watch
    speaks TO him ('كنت تجلس مع أطفالك'). Light, conservative rewrite."""
    toks = text.split()
    out = []
    verb_seen = False
    for i, t in enumerate(toks):
        prev = out[-1] if out else ""
        if verb_seen and len(t) >= 5 and t.startswith("وي"):
            out.append("وت" + t[2:])      # «…وتحكي لهم» continues the same subject
            continue
        if t == "كان":
            t = "كنت"
        elif len(t) >= 4 and t.startswith("ي") and (i == 0 or prev in ("كنت", "و", "ثم")):
            t = "ت" + t[1:]
            verb_seen = True
        elif len(t) >= 5 and t.startswith("وي") and (i == 0 or prev in ("كنت",)):
            t = "وت" + t[2:]
        elif t.endswith("ه") and len(t) >= 2 and norm(t) not in _NO_POSSESSIVE:
            t = t[:-1] + "ك"
        out.append(t)
    return " ".join(out)


def find_memories(terms: list[str], limit: int = 4) -> list[dict]:
    hits = []
    for row in corpus():
        if mentions(row["text"], terms) or mentions(row.get("subject", ""), terms):
            hits.append(row)
    # richer sentences first, dedupe by text
    seen, out = set(), []
    for h in sorted(hits, key=lambda r: -len(r["text"])):
        k = norm(h["text"])
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out[:limit]


def memory_vocabulary() -> list[str]:
    """Short names of things that appear in memories (for the AI vision prompt)."""
    vocab = set()
    for row in corpus():
        for en, names in objects.ARABIC.items():
            if en != "person" and mentions(row["text"], names):
                vocab.add(names[0])
        if row.get("subject") and len(row["subject"]) <= 25:
            vocab.add(row["subject"])
    return sorted(vocab)


PERSON_MAX_M = 5.0          # remind about a family member up to 5 metres away
OBJECT_MAX_M = 1.5          # objects only when within reach
GLOBAL_GAP = 45             # never two memory reminders closer than this
_last_reminder = [0.0]


def is_close(d: dict) -> bool:
    """Is this object within the patient's reach? Far things are never discussed."""
    if d.get("distance_m") is not None:
        try:
            return float(d["distance_m"]) <= OBJECT_MAX_M
        except (TypeError, ValueError):
            return False
    if d.get("near_hand"):
        return True
    area = d.get("area") or 0
    if d.get("en") in objects.BACKGROUND:
        return area >= 0.18     # furniture: he is sitting at / right next to it
    return area >= 0.08


def reminder_for(thing_ar: str, synonyms: list[str], key: str,
                 cooldown: int = 600, facts_override: list[dict] | None = None,
                 mode: str = "seen") -> dict | None:
    """Spoken reminder for a thing in front of the patient, or None."""
    hits = facts_override if facts_override is not None else find_memories(synonyms)
    if not hits:
        return None
    import time as _t
    if _t.time() - _last_reminder[0] < GLOBAL_GAP:
        return None
    if not allow(f"remind:{key}", cooldown):
        return None
    facts = []
    for h in hits:
        t = h["text"]
        if str(h.get("source", "")) == "media:related" and facts:
            continue
        if str(h.get("source", "")).startswith(("profile:", "extra:", "media:")):
            t = to_second_person(t)
        if not any(norm(t) in norm(f) for f in facts):
            facts.append(t)
    # The patient can see the thing — never announce it ("هذا كوب").
    # Say only the memory, in one short sentence.
    # the same memory may be reached by several routes (photo match, object,
    # speech) — say it once
    if not allow(f"fact:{norm(facts[0])[:60]}", cooldown):
        return None
    text = ai.phrase_reminder(thing_ar, facts, mode)
    if not text:
        if mode == "place":
            text = f"تذكر {thing_ar}؟ " + (ai.brief(facts[0], 14) or "")
        elif mode == "person":
            # facts[0] is "<name> <relation>"; add one memory if there is one
            text = f"هذا {facts[0].rstrip('. ')}."
            if len(facts) > 1:
                text += " " + (ai.brief(facts[1], 12) or "")
        else:                    # an object: the memory only, never its name
            text = ai.brief(facts[0], 16)
    _last_reminder[0] = _t.time()
    _log("reminder", text)
    return {"text": text.strip(), "thing": thing_ar, "mode": mode,
            "basis": [h.get("source", "") for h in hits]}


def place_memories(name: str) -> list[dict]:
    """Memories about a place the camera (or AI) recognised."""
    return find_memories([name] + ([name[2:]] if name.startswith("ال") else []), limit=3)


def person_facts(person_id: int, name: str, relation: str) -> list[dict]:
    facts = [{"source": f"people:{person_id}", "text": f"{name}، {relation}".strip("، ")}]
    with connect() as conn:
        pe = conn.execute("SELECT preferred, notes FROM people WHERE id=?", (person_id,)).fetchone()
    for t in ((pe["notes"], pe["preferred"]) if pe else ()):
        for snt in sentences(t or ""):
            facts.append({"source": f"people:{person_id}", "text": snt})
    for h in find_memories([name], limit=3):
        if not h["source"].startswith("people:"):
            facts.append(h)
    return facts


# ------------------------------------------------- what the camera sees ----

import time as _time

LAST_SEEN: dict = {"at": 0.0, "objects": [], "face": None, "scene": None}


def remember_seen(objects_ar: list[str], face: str | None, scene: str | None) -> None:
    LAST_SEEN.update(at=_time.time(), objects=objects_ar, face=face, scene=scene)


def seen_recently(max_age: float = 15) -> list[str]:
    if _time.time() - LAST_SEEN["at"] > max_age:
        return []
    out = []
    if LAST_SEEN["face"]:
        out.append(f"شخص: {LAST_SEEN['face']}")
    if LAST_SEEN["scene"]:
        out.append(LAST_SEEN["scene"])
    return out + list(LAST_SEEN["objects"])


VISUAL_CUES = ("هذا", "هذي", "هذه", "هاذا", "هاذي", "قدامي", "امامي", "أمامي", "بيدي",
               "يدي", "ايدي", "إيدي", "اصابع", "أصابع", "اشوف", "أشوف", "شايف", "تشوف",
               "لونه", "لونها", "مكتوب", "اقرأ", "اقرا", "ماسك", "امسك",
               "أمسك", "عيني", "الصورة")


def is_visual_question(text: str) -> bool:
    return is_question(text) and mentions(text, list(VISUAL_CUES))


def relevant_facts(question: str, limit: int = 10) -> list[str]:
    """Family sentences that share a meaningful word with the question."""
    words = [w for w in re.split(r"[\s؟?!.,،]+", question) if len(w) > 2]
    scored = []
    for row in corpus():
        sc = sum(1 for w in words if mentions(row["text"], [w]) or
                 mentions(row.get("subject", ""), [w]))
        if sc:
            scored.append((sc, row["text"]))
    scored.sort(key=lambda t: -t[0])
    return [t for _, t in scored[:limit]]


# --------------------------------------------------------------- hazards ---

def _location():
    try:
        from . import safety
        with connect() as conn:
            dev = conn.execute("SELECT id FROM devices ORDER BY id LIMIT 1").fetchone()
        return safety.latest_location(dev["id"]) if dev else None
    except Exception:
        return None


def raise_alert(kind: str, item: str, message: str, cooldown: int = 180) -> dict | None:
    """Record an alert and send it to the family now (in the background)."""
    if not allow(f"alert:{kind}:{norm(item)}", cooldown):
        return None
    loc = _location() or {}
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp() // max(cooldown, 1))
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO alerts(kind,message,lat,lon,location_at,dedupe_key) "
                "VALUES (?,?,?,?,?,?)",
                (kind, message, loc.get("lat"), loc.get("lon"), loc.get("reported_at"),
                 f"{kind}:{norm(item)}:{bucket}"))
            alert_id = cur.lastrowid
        except Exception:
            return None
    name = patient_name()

    def _send():
        msg = notify.compose(kind, name, loc.get("lat"), loc.get("lon"),
                             now.isoformat(timespec="seconds"), extra=message)
        notify.deliver(alert_id, msg, name)

    threading.Thread(target=_send, daemon=True).start()
    _log("alert", message)
    return {"alert_id": alert_id, "kind": kind, "item": item, "message": message}


def check_hazards(dets: list[dict], ai_scan: dict | None) -> tuple[list[dict], list[str]]:
    """Returns (alerts sent, gentle spoken warnings for the patient)."""
    lists = watch_lists()
    allergy, danger = lists["allergy"], lists["danger"]
    sent, spoken = [], []
    name = patient_name() or "المريض"

    for d in dets:
        if d["en"] == "person":
            continue
        syn = d["synonyms"]
        hit_allergy = next((a for a in allergy if mentions(a, syn) or
                            any(mentions(s, [a]) for s in syn)), None)
        if hit_allergy and d.get("near_hand"):
            a = raise_alert("allergen_contact", d["ar"],
                            f"الكاميرا رأت {name} يلمس/يتناول «{d['ar']}» وهو مسجّل ضمن "
                            f"الأشياء التي يتحسس منها ({hit_allergy}).")
            if a:
                sent.append(a)
                spoken.append(f"انتبه، {d['ar']} يسبب لك حساسية. اتركه من فضلك.")
        is_danger = d["en"] in objects.DEFAULT_DANGER or any(
            mentions(x, syn) or any(norm(s) == norm(x) for s in syn) for x in danger)
        if is_danger and d.get("near_hand"):
            a = raise_alert("danger_contact", d["ar"],
                            f"الكاميرا رأت {name} قريبًا جدًا من «{d['ar']}» أو يمسكه — "
                            "شيء مسجّل كخطر.")
            if a:
                sent.append(a)
                spoken.append(f"انتبه من {d['ar']}، ضعه جانبًا بهدوء.")

    if ai_scan:
        for item in ai_scan.get("allergen_contact") or []:
            a = raise_alert("allergen_contact", str(item),
                            f"الذكاء الاصطناعي رأى {name} يلمس/يتناول «{item}» "
                            "وهو من الأشياء التي يتحسس منها.")
            if a:
                sent.append(a)
                spoken.append(f"انتبه، {item} يسبب لك حساسية.")
        for o in ai_scan.get("objects") or []:
            nm = str(o.get("name_ar", ""))
            if not nm or not (o.get("touching") or o.get("eating")):
                continue
            hit = next((a for a in allergy if mentions(nm, [a]) or mentions(a, [nm])), None)
            if hit:
                a = raise_alert("allergen_contact", nm,
                                f"{name} {'يتناول' if o.get('eating') else 'يلمس'} «{nm}» "
                                f"وهو يتحسس منه ({hit}).")
                if a:
                    sent.append(a)
                    spoken.append(f"انتبه، {nm} يسبب لك حساسية.")
        for desc in ai_scan.get("danger") or []:
            a = raise_alert("danger_action", str(desc)[:40],
                            f"تصرف خطير محتمل: {desc}")
            if a:
                sent.append(a)
                spoken.append("انتبه من فضلك، توقف لحظة. أهلك في الطريق للاطمئنان عليك.")
    return sent, spoken


# --------------------------------------------------------------- privacy ---

def is_private(text: str) -> bool:
    words = list(PRIVATE_KEYWORDS) + watch_lists()["private"]
    return mentions(text, words)


def leaks_private(answer: str) -> bool:
    """Does an answer contain a value from a private profile field?"""
    p, e = _profile(), _extra()
    secret_vals = [p.get("home_address"), p.get("medical_info"), p.get("allergies"),
                   p.get("emergency_notes"), e.get("phone"), e.get("medications"),
                   e.get("medication_schedule"), e.get("medical_instructions")]
    a = norm(answer)
    for v in secret_vals:
        for piece in split_items(v or ""):
            if len(piece) >= 4 and norm(piece) in a:
                return True
    return bool(re.search(r"\d{7,}", answer))


def is_question(text: str) -> bool:
    t = text.strip()
    if "؟" in t or "?" in t:
        return True
    first = norm(t).split(" ")[:2]
    joined = " ".join(first)
    return any(joined.startswith(norm(q)) for q in QUESTION_STARTS)


def strip_wake(text: str, extra_phrase: str = "") -> tuple[bool, str]:
    words = list(WAKE_WORDS) + ([extra_phrase] if extra_phrase else [])
    t = text
    for w in sorted(words, key=len, reverse=True):
        if w and norm(w) in norm(t):
            idx = norm(t).find(norm(w))
            return True, (t[:idx] + t[idx + len(w):]).strip(" ،,")
    return False, t


# ------------------------------------------------------ network answers ----

def answer_from_network(question: str) -> tuple[str | None, list[str]]:
    """Answer a memory question from the network/corpus, or (None, [])."""
    stop = {"هل", "وش", "ايش", "متى", "وين", "أين", "كيف", "ليش", "لماذا", "مين",
            "تعرف", "تذكر", "تتذكر", "عن", "ماذا", "هو", "هي", "كم", "اللي",
            "الذي", "التي", "كان", "كانت", "يوم", "ابوي", "يبه", "يمه", "انت", "أنت"}
    words = []
    for w in re.split(r"[\s؟?!.,،]+", question):
        if len(w) <= 2 or w in stop:
            continue
        for suf in ("تم", "نا", "ت", "ك", "ي"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        words.append(w)
    if not words:
        return None, []
    hits = []
    for row in corpus():
        score = sum(1 for w in words if mentions(row["text"], [w]) or
                    mentions(row.get("subject", ""), [w]))
        if score:
            hits.append((score, row))
    if not hits:
        return None, []
    hits.sort(key=lambda t: (-t[0], -len(t[1]["text"])))
    best = [h[1] for h in hits[:2]]
    # one weak keyword hit is how "dumb" answers happen — demand more
    if hits[0][0] < 2 and len(words) > 1:
        return None, []
    return ai.brief(best[0]["text"], 18), [best[0]["source"]]


def _log(kind: str, text: str) -> None:
    try:
        with connect() as conn:
            conn.execute("INSERT INTO chat_log(role,content,basis) VALUES (?,?,?)",
                         ("assistant", text, f"companion:{kind}"))
    except Exception:
        pass
