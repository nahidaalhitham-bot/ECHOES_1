"""Echeos (أصداء الذاكرة) — FastAPI backend.

Implemented: personal memory base, grounded retrieval with refusal, family
dashboard data, device/simulator, location ingest, safe zones, alerts with
de-duplication, help requests, and audit.

NOT implemented: camera/face recognition (excluded by design), wearable
hardware sync, TTS, authentication. See README.md for the full list.
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import base64
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import (Cookie, Depends, FastAPI, File, Form, Header, HTTPException,
                     Query, Response, UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import patient_link as _patient_link  # noqa: E402
from . import (agent, ai, alerts, auth, bot, companion, db, devices as dev_mod,
               investigate, media, network, notify, objects, safety,
               secrets as secrets_mod, tunnel, vision)

BASE = Path(__file__).resolve().parent

# Real operation is the default. Demo data is opt-in only, so a fresh install
# never shows a fake patient or invented coordinates.
# A file named DEMO_MODE next to run.py turns on the ready-made fictional data
# (handy on Railway/Render: no settings to type).
if (Path(__file__).resolve().parent.parent / "DEMO_MODE").exists():
    os.environ.setdefault("ECHEOS_DEMO", "1")
    os.environ.setdefault("ECHEOS_ALLOW_SIMULATOR", "1")
DEMO_MODE = os.environ.get("ECHEOS_DEMO", "0") == "1"


def _cloud_bootstrap() -> None:
    """On a hosting service (Render): the owner account and the bot token come
    from the service's environment settings, so no stranger can register as
    the first owner and no secret lives in the GitHub repository."""
    email = os.environ.get("ECHOES_OWNER_EMAIL", "").strip()
    pw = os.environ.get("ECHOES_OWNER_PASSWORD", "").strip()
    if email and pw and auth.count_users() == 0:
        try:
            auth.create_user(email, pw, os.environ.get("ECHOES_OWNER_NAME", "المسؤول"), "owner")
        except Exception as e:  # noqa: BLE001
            print("owner bootstrap:", e)
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tok:
        try:
            from . import telegram_link, secrets as secrets_mod
            if tok != telegram_link._token():
                with db.connect() as conn:
                    telegram_link._set(conn, "notif_settings", "telegram_token", secrets_mod.encrypt(tok))
        except Exception as e:  # noqa: BLE001
            print("telegram bootstrap:", e)


def _cloud() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("ECHOES_CLOUD")
                or os.environ.get("RAILWAY_ENVIRONMENT"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    _cloud_bootstrap()
    from . import visual_qa as _vqa
    if os.environ.get("ECHEOS_FETCH_MODELS", "1") == "1" and not (
            vision.available() and objects.available() and _vqa.classifier_available()
            and (_vqa.HAND_PATH.exists())):
        try:
            from .fetch_models import ensure_models
            ensure_models(verbose=True)
        except Exception:
            pass  # recognition stays unavailable; the rest of the app works
    if DEMO_MODE:
        with db.connect() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
        if n == 0:
            from . import demo_seed
            demo_seed.seed_full_demo(_auto_build_memory_graph, _patient_memory_id)
    # Open the public HTTPS address in the background so live links sent to
    # Telegram work on any phone (skipped until the owner account exists).
    tunnel.start_async()
    # Telegram: import telegram_token.txt, drop a wrong Chat ID, and keep
    # linking family members / answering bot commands in the background.
    if os.environ.get("ECHOES_TG_BACKGROUND", "1") == "1":
        import threading
        from . import telegram_link
        threading.Thread(target=telegram_link.background_loop,
                         args=(BASE.parent,), daemon=True).start()
    yield
    tunnel.stop()


app = FastAPI(title="Echeos / أصداء الذاكرة", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


# ---------------------------------------------------------------- models ----

class MemoryIn(BaseModel):
    kind: str = Field(default="fact", pattern="^(person|place|routine|fact)$")
    subject: str = Field(min_length=1, max_length=80)
    fact: str = Field(min_length=1, max_length=400)


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    relation: str = Field(min_length=1, max_length=80)
    preferred: str = ""
    notes: str = ""


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    # True when the watch answers for the patient after he stayed silent.
    on_behalf: bool = False


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    device_id: int = 1
    accuracy_m: float | None = None
    simulated: bool = True


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=300, gt=0, le=50000)


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="simulator", pattern="^(simulator|wearable)$")


# ------------------------------------------------------------------ seed ----

def seed_demo() -> None:
    """Fictional demo data. The UI shows a DEMO badge while this is on."""
    people = [
        ("أحمد", "ابنك", "أحمد يحب القهوة العربية", ""),
        ("نورة", "ابنتك", "نورة تزورك كل خميس", ""),
        ("سارة", "حفيدتك", "سارة عمرها ست سنوات", ""),
    ]
    memories = [
        ("place", "المنزل", "تعيش في بيتك في حي النرجس"),
        ("routine", "الروتين", "تفطر عادة الساعة سبع وتسقي الزرع بعدها"),
        ("fact", "الهواية", "كنت تحب صيد السمك مع أخيك"),
    ]
    with db.connect() as conn:
        for name, rel, pref, notes in people:
            conn.execute(
                "INSERT OR IGNORE INTO people(name,relation,preferred,notes) VALUES (?,?,?,?)",
                (name, rel, pref, notes),
            )
        for kind, subject, fact in memories:
            conn.execute(
                "INSERT INTO memories(kind,subject,fact) VALUES (?,?,?)",
                (kind, subject, fact),
            )
        conn.execute(
            "INSERT OR IGNORE INTO devices(name,kind,simulated) VALUES ('محاكي الجهاز','simulator',1)"
        )
        conn.execute(
            "INSERT INTO safe_zones(name,lat,lon,radius_m) VALUES ('المنزل',24.7136,46.6753,300)"
        )
        conn.execute(
            "INSERT INTO locations(device_id,lat,lon,accuracy_m,simulated) VALUES (1,24.7136,46.6753,20,1)"
        )

    # The memory network opens its own connections, so seed it AFTER the
    # block above has closed — otherwise SQLite reports "database is locked".
    network.seed_network()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO reminders(kind,title,detail,due_at) VALUES "
            "('medication','دواء الضغط','حبة واحدة بعد الفطور','2026-11-09T08:00')"
        )
        conn.execute(
            "INSERT INTO reminders(kind,title,detail,due_at) VALUES "
            "('appointment','موعد الطبيب','عيادة الذاكرة — الدور الثالث','2026-11-12T10:30')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO patient_profile(id, full_name, age, home_address, "
            "medical_info, allergies, emergency_notes, routine, reminder_scope) VALUES "
            "(1, 'أحمد بن عبدالله', 72, 'الرياض، المملكة العربية السعودية', "
            "'ارتفاع ضغط الدم', 'حساسية من البنسلين', "
            "'في حال الارتباك الشديد تواصل مع الابن أحمد', "
            "'يفطر الساعة سبع، ويصلي الظهر في المسجد', "
            "'أوقات الصلاة، مواعيد الدواء، أسماء المقربين عند رؤيتهم، تنبيهات السلامة')"
        )
        conn.execute(
            "INSERT INTO caregivers(full_name,relation,phone,email,is_primary) VALUES "
            "('أحمد محمد عبدالله','الابن','0501234567','ahmad@example.com',1)"
        )
        conn.execute(
            "INSERT INTO caregivers(full_name,relation,phone,email,is_primary) VALUES "
            "('سارة محمد عبدالله','الابنة','0509876543','sara@example.com',0)"
        )


# ------------------------------------------------------------------ pages ---

_I18N_CACHE: dict = {}


@app.get("/i18n/{lang}.json")
def i18n_dict(lang: str) -> dict:
    """Interface translations, built from app/i18n/<lang>_*.tsv (Arabic<TAB>translation)."""
    if lang not in ("en",):
        raise HTTPException(status_code=404, detail="unknown language")
    files = sorted((BASE / "i18n").glob(f"{lang}_*.tsv"))
    version = str(int(max((f.stat().st_mtime for f in files), default=0)))
    hit = _I18N_CACHE.get(lang)
    if hit and hit["v"] == version:
        return hit
    d: dict = {}
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if "\t" in line and not line.startswith("#"):
                k, v = line.split("\t", 1)
                if k.strip() and v.strip():
                    d[k.strip()] = v.strip()
    _I18N_CACHE[lang] = {"v": version, "dict": d}
    return _I18N_CACHE[lang]


@app.get("/")
def index() -> RedirectResponse:
    """The bare address is the caregiver app. The patient app has its own link."""
    return RedirectResponse("/login", status_code=302)


@app.get("/patient.webmanifest")
def patient_manifest(k: str = "") -> Response:
    """Makes the patient screen installable on the phone like an app."""
    import json as _json
    start = "/patient" + (f"#k={k}" if k else "")
    body = {
        "name": "ECHOES — المريض", "short_name": "ECHOES",
        "description": "تطبيق المريض: المساعد الصوتي ورمز ربط الجوال",
        "start_url": start, "scope": "/", "display": "standalone", "orientation": "portrait",
        "dir": "rtl", "lang": "ar", "background_color": "#f6f1fb", "theme_color": "#3b1d5c",
        "icons": [{"src": "/static/icons/patient-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                  {"src": "/static/icons/patient-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
    }
    return Response(_json.dumps(body, ensure_ascii=False), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> Response:
    """Minimal service worker (required by Android to offer «Install app»).
    It never caches API data — everything stays live."""
    js = ("self.addEventListener('install',e=>self.skipWaiting());"
          "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
          "self.addEventListener('fetch',e=>{});")
    return Response(js, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/patient", response_class=HTMLResponse)
def patient_app() -> str:
    """Patient screen only (needs the patient link's key, kept on the phone)."""
    return (BASE / "templates" / "patient.html").read_text(encoding="utf-8")


@app.get("/api/app-links")
def app_links(user: dict = Depends(auth.require_user)) -> dict:
    """Both public addresses, for the card at the top of «نظرة عامة»."""
    from . import patient_link
    base = tunnel.public_base()
    st = tunnel.status()
    return {"caregiver": f"{base}/login" if base else None,
            "patient": patient_link.url(base) if base else None,
            "patient_separate": bool(tunnel.patient_base()),
            "status": st.get("status"), "detail": st.get("detail", "")}


@app.post("/api/patient-link")
def patient_link_info(new: bool = False, user: dict = Depends(auth.require_role("owner"))) -> dict:
    from . import patient_link
    if new:
        patient_link.get_key(rotate=True)
    base = tunnel.public_base(wait_seconds=10)
    u = patient_link.url(base, wait=15)
    local = f"/patient#k={patient_link.get_key()}"
    qr = None
    if u:
        try:
            import segno
            qr = segno.make(u, error="m").svg_inline(scale=5, border=2)
        except Exception:
            qr = None
    return {"url": u, "local": local, "public": bool(base), "qr_svg": qr}


@app.get("/family", response_class=HTMLResponse)
def family_page() -> str:
    return (BASE / "templates" / "family.html").read_text(encoding="utf-8")


@app.get("/safety", response_class=HTMLResponse)
def safety_page() -> str:
    return (BASE / "templates" / "safety.html").read_text(encoding="utf-8")


@app.get("/camera", response_class=HTMLResponse)
def camera_page() -> str:
    return (BASE / "templates" / "camera.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "demo_mode": DEMO_MODE, "version": "0.2.0",
            "public_url": tunnel.public_base() if DEMO_MODE else None}


# --------------------------------------------------------------- memories ---

@app.post("/api/memories", status_code=201)
def add_memory(m: MemoryIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO memories(kind,subject,fact) VALUES (?,?,?)",
            (m.kind, m.subject.strip(), m.fact.strip()),
        )
        new_id = cur.lastrowid
    return {"id": new_id, **m.model_dump()}


@app.delete("/api/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, _user: dict = Depends(auth.require_user)) -> None:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/api/family/{person_id}/recognition-status")
def person_recognition_status(person_id: int,
                              user: dict = Depends(auth.require_user)) -> dict:
    """Does this specific person have a usable face descriptor?"""
    with db.connect() as conn:
        enrolled = conn.execute(
            "SELECT 1 FROM face_enrollments WHERE person_id = ? AND consent = 1",
            (person_id,)).fetchone()
        derived = conn.execute(
            "SELECT 1 FROM photo_embeddings WHERE person_id = ?", (person_id,)).fetchone()
        has_photo = conn.execute(
            "SELECT 1 FROM photos WHERE owner_type='person' AND owner_id = ?",
            (person_id,)).fetchone()
    return {
        "person_id": person_id,
        "has_photo": bool(has_photo),
        "enrolled": bool(enrolled),
        "face_descriptor": bool(derived or enrolled),
        "ready": bool(derived or enrolled),
    }


@app.get("/api/family")
def list_family(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM people ORDER BY id").fetchall()
    return {"people": [dict(r) for r in rows]}


@app.post("/api/family", status_code=201)
def add_person(p: PersonIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO people(name,relation,preferred,notes) VALUES (?,?,?,?)",
                (p.name.strip(), p.relation.strip(), p.preferred, p.notes),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="name already exists")
        new_id = cur.lastrowid
    return {"id": new_id, **p.model_dump()}


# ------------------------------------------------------------------ agent ---

@app.post("/api/agent/chat")
def chat(body: ChatIn, _user: dict = Depends(_patient_link.require_patient_or_caregiver)) -> dict:
    # "مين هذا؟" refers to whoever the camera just saw. Use the most recent
    # recognition if it is recent and confident — never a guess.
    q = body.message.strip()
    if body.on_behalf and companion.is_private(q):
        # Very personal question asked by someone else: the watch stays silent.
        with db.connect() as conn:
            conn.execute("INSERT INTO chat_log(role,content,basis) VALUES ('user',?,?)",
                         (body.message, "heard:private"))
        return {"answer": "", "kind": "private", "grounded_in": [],
                "source": "privacy"}
    result = agent.answer(body.message)
    source = "memory"

    # "Where am I?" / "what is this place?" -> use the last recognised scene.
    place_q = any(x in q for x in ("وين أنا", "وين انا", "أين أنا", "اين انا",
                                   "وش هذا المكان", "هذا المكان", "any place"))
    if place_q and result.refused:
        with db.connect() as conn:
            scene = conn.execute(
                "SELECT label, memory_id FROM scene_embeddings "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            mem = None
            if scene:
                mem = conn.execute(
                    "SELECT fact FROM memories WHERE id = ?", (scene["memory_id"],)
                ).fetchone()
        if scene:
            text = f"هذا {scene['label']}."
            if mem and mem["fact"]:
                text += f" {mem['fact']}."
            return {"answer": text, "kind": "answered",
                    "grounded_in": [f"memories:{scene['memory_id']}", "scene:latest"]}
        return {"answer": "ما أعرف وين أنت. وجّه الكاميرا نحو المكان.",
                "kind": "refused", "grounded_in": []}

    if any(x in q for x in ("مين هذا", "من هذا", "مين ها", "who is this")) \
            and result.refused:
        with db.connect() as conn:
            # Prefer the most recent SUCCESSFUL recognition within 2 minutes.
            # A single failed frame (a blink, a turn of the head) must not erase
            # the person the camera just identified.
            last = conn.execute(
                "SELECT rl.outcome, rl.person_id, rl.similarity, rl.created_at, "
                "p.name, p.relation FROM recognition_log rl "
                "LEFT JOIN people p ON p.id = rl.person_id "
                "WHERE rl.outcome = 'recognised' "
                "AND rl.created_at >= datetime('now', '-2 minutes') "
                "ORDER BY rl.id DESC LIMIT 1"
            ).fetchone()
        if last and last["outcome"] == "recognised" and last["name"]:
            result = agent.Answer(
                f"{last['name']} {last['relation'] or ''}.".strip(),
                [f"people:{last['person_id']}", "recognition:latest"],
                "answered",
            )
        else:
            result = agent.Answer(
                "ما قدرت أتعرف عليه، خلينا نسأل أحد من أهلك.", [], "refused")

    # Not in the structured profile -> search the memory network / corpus,
    # then (for general questions only) the internet.
    if result.refused and not agent._is_location_probe(q.lower()):
        if ai.configured():
            # The smart path: Claude, grounded in the family's sentences and
            # what the camera sees, one short sentence, NONE if it doesn't know.
            smart = ai.smart_answer(q, companion.relevant_facts(q), companion.seen_recently())
            if smart and not companion.is_private(smart):
                result, source = agent.Answer(smart, ["ai"], "answered"), "ai"
        else:
            text, basis = companion.answer_from_network(q)
            if text:
                result, source = agent.Answer(text, basis, "answered"), "network"
            elif not _personal_cue(q) and not companion.is_private(q) \
                    and not companion.is_visual_question(q):
                web, how = ai.internet_answer(q)
                if web:
                    result, source = agent.Answer(web, [how], "answered"), how
    if body.on_behalf and result.kind == "answered" and companion.leaks_private(result.text):
        result, source = agent.Answer("", [], "private"), "privacy"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO chat_log(role,content,basis) VALUES ('user',?,NULL)",
            (body.message,),
        )
        conn.execute(
            "INSERT INTO chat_log(role,content,basis) VALUES ('assistant',?,?)",
            (result.text, ",".join(result.basis) or None),
        )
    return {"answer": result.text, "kind": result.kind, "grounded_in": result.basis,
            "source": source}


_PERSONAL_WORDS = ("ولدك", "ولدي", "بنتك", "بنتي", "زوجتك", "زوجك", "اسمك", "عمرك",
                   "بيتك", "أهلك", "اهلك", "عيالك", "أخوك", "اخوك", "أختك", "اختك",
                   "أمك", "امك", "أبوك", "ابوك", "جدك", "حفيدك", "انت", "أنت",
                   "تذكر", "تتذكر", "فاكر", "ذكرى", "ذكريات")


def _personal_cue(q: str) -> bool:
    """Questions about the patient's own life are never sent to the internet."""
    if companion.mentions(q, list(_PERSONAL_WORDS)):
        return True
    # second-person possessives (دواك، بيتكم، ولدك…) point at the patient
    common = {"ذلك", "هناك", "كذلك", "تلك", "مبارك", "البنك", "بنك", "الملك", "ملك",
              "سمك", "السمك", "شبابيك", "مشترك", "تبوك", "المبارك", "الضحك", "ضحك"}
    for w in re.findall(r"[\u0600-\u06FF]+", q):
        if len(w) >= 4 and (w.endswith("ك") or w.endswith("كم")) and w not in common:
            return True
    return False


class HearIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    direct: bool = False     # the patient pressed "ask" — answer immediately
    image: str | None = Field(default=None, max_length=4_000_000)  # current camera frame (base64 jpeg)


def _visual_answer(text: str, image_b64: str | None) -> str | None:
    """'وش هذا؟' / 'كم إصبع؟' / 'وش لونه؟' / 'وش الشكل؟' — from the camera, honestly.

    With an AI key: Claude looks at the frame. Without one (or if it fails):
    the on-device engine (visual_qa) — 1000-class classifier, object counter,
    hand landmarks, shapes and colours."""
    raw = None
    if image_b64:
        try:
            raw = base64.b64decode(image_b64.split(",", 1)[-1])
        except Exception:
            raw = None
    if raw is None:
        return "ما وصلتني صورة من الكاميرا — تأكدي أن الكاميرا شغالة."
    if ai.configured():
        ans = ai.look_and_answer(text, raw, companion.relevant_facts(text, 5))
        if ans:
            return ans
    try:
        img = vision._decode(raw)
    except ValueError:
        return "ما قدرت أقرأ صورة الكاميرا."
    from . import visual_qa
    dets = objects.detect(img) if objects.available() else []
    return visual_qa.answer(text, img, dets) or "ما أقدر أشوفه بوضوح."


def _heard_reminder(text: str) -> dict | None:
    """Someone mentioned a person / place / event from his memories.

    Everyday objects ("كوب", "كرسي") in conversation are ignored on purpose.
    """
    with db.connect() as conn:
        nodes = conn.execute(
            "SELECT id, kind, label FROM nodes WHERE kind IN ('person','place','event') "
            "AND label NOT LIKE 'محادثة %' AND length(label) BETWEEN 2 AND 30"
        ).fetchall()
    for n in nodes:
        lab = n["label"]
        if lab == PATIENT_MEMORY_SUBJECT or not companion.mentions(text, [lab]):
            continue
        rem = companion.reminder_for(lab, [lab], f"heard:{n['id']}", cooldown=3 * 3600,
                                     mode="heard")
        if rem:
            return rem
    return None


@app.post("/api/companion/hear")
def companion_hear(body: HearIn, _user: dict = Depends(_patient_link.require_patient_or_caregiver)) -> dict:
    """Everything the watch's microphone transcribes comes here.

    - Wake phrase (or the patient's button) -> answer now.
    - A question from someone else -> answer is prepared now, but the watch
      waits `wait_seconds` (13 s) and speaks only if the patient stayed silent.
      Very personal questions get no answer at all.
    - Anything else that mentions a memory -> a gentle spoken reminder.
    """
    s = get_assistant_settings()
    addressed, rest = companion.strip_wake(body.text, s.get("wake_phrase", ""))
    addressed = addressed or body.direct
    out = {"addressed": addressed, "is_question": False, "answer": None,
           "kind": None, "wait_seconds": 0, "reminder": None}
    question = rest if addressed else body.text
    from . import visual_qa
    if (visual_qa.detect_intent(question or "") is not None
            or ((addressed or companion.is_question(body.text))
                and companion.is_visual_question(question or ""))) \
            and not companion.is_private(question):
        ans = _visual_answer(question, body.image)
        with db.connect() as conn:
            conn.execute("INSERT INTO chat_log(role,content,basis) VALUES ('user',?,?)",
                         (question, "heard:visual"))
            conn.execute("INSERT INTO chat_log(role,content,basis) VALUES ('assistant',?,?)",
                         (ans, "camera"))
        out.update(answer=ans, kind="answered", source="camera", is_question=not addressed,
                   wait_seconds=0 if addressed else ai.settings()["reply_delay"])
        return out
    if addressed:
        if not rest.strip():
            out.update(answer="نعم، تفضّل.", kind="answered")
            return out
        r = chat(ChatIn(message=rest[:500]))
        out.update(answer=r["answer"], kind=r["kind"], source=r.get("source"))
        return out
    if companion.is_question(body.text):
        r = chat(ChatIn(message=body.text, on_behalf=True))
        out.update(is_question=True, answer=r["answer"], kind=r["kind"],
                   source=r.get("source"), wait_seconds=ai.settings()["reply_delay"])
        return out
    with db.connect() as conn:
        conn.execute("INSERT INTO chat_log(role,content,basis) VALUES ('user',?,?)",
                     (body.text, "heard"))
    out["reminder"] = _heard_reminder(body.text)
    return out


@app.get("/api/agent/history")
def history(limit: int = 50, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT role, content, basis, created_at FROM chat_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"messages": [dict(r) for r in reversed(rows)]}


# --------------------------------------------------------------- devices ----

@app.get("/api/devices")
def list_devices(_user: dict = Depends(auth.require_user)) -> dict:
    # Never expose the device bearer token through the API.
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, name, kind, connected, battery, last_seen_at, simulated, "
            "created_at FROM devices ORDER BY id"
        ).fetchall()
    return {"devices": [dict(r) for r in rows]}


@app.post("/api/devices", status_code=201)
def add_device(d: DeviceIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO devices(name,kind,simulated) VALUES (?,?,?)",
                (d.name.strip(), d.kind, 1 if d.kind == "simulator" else 0),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="device name already exists")
        new_id = cur.lastrowid
    return {"id": new_id, **d.model_dump()}


# -------------------------------------------------------------- locations ---

@app.post("/api/location", status_code=201)
async def post_location(loc: LocationIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        dev = conn.execute("SELECT id FROM devices WHERE id = ?", (loc.device_id,)).fetchone()
    if not dev:
        raise HTTPException(status_code=404, detail="unknown device")
    rec = safety.record_location(loc.lat, loc.lon, loc.device_id, loc.accuracy_m, loc.simulated)
    if rec.get("reconnected"):
        notify.notify_reconnected(0, _patient_name(), loc.lat, loc.lon)
    # Geofence exits queue a notification inside the DB lock; send it now that
    # the lock is free. This is what makes the alert reach the phone without
    # the caregiver opening the app.
    _p = _patient_name()
    sent = safety.drain_pending_notifications(_p)
    await _push_fix(loc.device_id)
    return {
        "ok": True,
        "note": "location recorded; freshness is computed on read",
        "notifications_sent": len(sent),
        "notifications": sent,
    }


@app.get("/api/location/latest")
def location_latest(device_id: int = 1, user: dict = Depends(auth.require_user)) -> dict:
    loc = safety.latest_location(device_id)
    if loc is None:
        return {"location": None, "note": "لا يوجد موقع مسجّل"}
    return {"location": loc}


@app.get("/api/location/active-device")
def active_device(user: dict = Depends(auth.require_user)) -> dict:
    """Which device should the map follow?

    Preference: the device that reported most recently; otherwise the newest
    real (non-simulator) device. The map must not assume id 1.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT d.id, d.name, d.simulated, MAX(l.id) AS last_id "
            "FROM devices d LEFT JOIN locations l ON l.device_id = d.id "
            "GROUP BY d.id HAVING last_id IS NOT NULL "
            "ORDER BY last_id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id, name, simulated FROM devices "
                "ORDER BY simulated ASC, id ASC LIMIT 1"
            ).fetchone()
    if row is None:
        return {"device_id": None, "name": None, "has_fix": False}
    return {"device_id": row["id"], "name": row["name"],
            "simulated": bool(row["simulated"]) if "simulated" in row.keys() else False,
            "has_fix": True}


@app.get("/api/location/history")
def location_history(device_id: int = 1, limit: int = Query(20, ge=1, le=200), user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return {"history": [dict(r) for r in rows]}


# ------------------------------------------------------------- safe zones ---

@app.get("/api/geofence")
def list_zones(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM safe_zones ORDER BY id").fetchall()
    return {"zones": [dict(r) for r in rows]}


@app.post("/api/geofence", status_code=201)
def add_zone(z: ZoneIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO safe_zones(name,lat,lon,radius_m) VALUES (?,?,?,?)",
            (z.name.strip(), z.lat, z.lon, z.radius_m),
        )
        new_id = cur.lastrowid
    safety.reset_zone_states()
    return {"id": new_id, **z.model_dump()}


@app.put("/api/geofence/{zone_id}")
def toggle_zone(zone_id: int, enabled: bool = True, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE safe_zones SET enabled = ? WHERE id = ?", (1 if enabled else 0, zone_id)
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="zone not found")
    safety.reset_zone_states()
    return {"ok": True, "enabled": enabled}


# ---------------------------------------------------------------- alerts ----

@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=200), user: dict = Depends(auth.require_user)) -> dict:
    return {"alerts": safety.list_alerts(limit)}


@app.put("/api/alerts/{alert_id}/read")
def mark_read(alert_id: int, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE alerts SET read_at = datetime('now') WHERE id = ? AND read_at IS NULL",
            (alert_id,),
        )
        row = conn.execute("SELECT id, read_at FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return {"ok": True, "id": alert_id, "read_at": row["read_at"]}


@app.post("/api/alerts/check-staleness")
def check_staleness(_user: dict = Depends(auth.require_user)) -> dict:
    return {"raised": safety.check_staleness()}


@app.post("/api/device/help")
def device_help(device_id: int = 1) -> dict:
    return safety.request_help(device_id)


@app.get("/api/family/where")
def family_where(device_id: int = 1, user: dict = Depends(auth.require_user)) -> dict:
    return safety.family_ask_where(device_id)


# ------------------------------------------------------- wearable simulator --

@app.get("/api/diagnose/exit-alert")
def diagnose_exit_alert(user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Step-by-step: why a safe-zone exit did (not) reach Telegram."""
    from . import diagnose
    return diagnose.exit_alert()


@app.post("/api/simulator/exit-home")
async def simulate_exit_home(device_id: int = 1, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """TEST ONLY: jump the device outside the safe zone and raise the alert.

    Used by the «محاكاة الخروج من المنزل» button so a demo can show the whole
    chain (exit → alert → notification) without waiting for a real device to
    walk out. The stored fix is flagged `simulated = 1` and is shown as
    «محاكي» everywhere. Requires ECHEOS_ALLOW_SIMULATOR=1.
    """
    if os.environ.get("ECHEOS_ALLOW_SIMULATOR", "0") != "1":
        raise HTTPException(
            status_code=403,
            detail=("المحاكاة معطّلة. شغّلي التطبيق مع "
                    "ECHEOS_ALLOW_SIMULATOR=1 لاستخدام زر المحاكاة."),
        )
    with db.connect() as conn:
        zone = conn.execute(
            "SELECT * FROM safe_zones WHERE enabled = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    if zone is None:
        raise HTTPException(
            status_code=400,
            detail="حدّدي النطاق الآمن أولًا (المنزل) حتى يكون هناك نطاق للخروج منه",
        )

    # ~600 m north-east of the zone centre: clearly outside any normal radius.
    lat = zone["lat"] + 0.0054
    lon = zone["lon"] + 0.0054

    # Each press is a NEW departure from home: forget the previous "outside"
    # state (silently, no "returned" message) so the alert fires every time.
    safety.reset_zone_state(device_id)
    notify.telegram_stop_live()
    safety.record_location(lat, lon, device_id, 15.0, simulated=True)
    sent = safety.drain_pending_notifications(_patient_name())
    await _push_fix(device_id)

    with db.connect() as conn:
        alert = conn.execute(
            "SELECT id, kind, message, created_at FROM alerts "
            "WHERE kind = 'exited_safe_zone' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "ok": True,
        "simulated": True,
        "zone": zone["name"],
        "lat": lat,
        "lon": lon,
        "alert": dict(alert) if alert else None,
        "notifications_sent": len(sent),
        # attempted is not delivered: say which it really was
        "delivered": any(bool(r.get("delivered")) for r in sent if isinstance(r, dict)),
        "delivery_detail": next((r.get("detail") for r in sent
                                 if isinstance(r, dict) and not r.get("delivered")), None),
        "note": "بيانات محاكاة — ليست موقعًا حقيقيًا",
    }


@app.post("/api/simulator/step")
async def simulator_step(device_id: int = 1, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Move the TEST device one step (~90 m). Test-only; never real data.

    If no fix exists yet, start from the centre of the first safe zone so the
    test has somewhere to begin. Requires ECHEOS_ALLOW_SIMULATOR=1.
    """
    if os.environ.get("ECHEOS_ALLOW_SIMULATOR", "0") != "1":
        raise HTTPException(
            status_code=403,
            detail="المحاكي معطّل. شغّلي التطبيق مع ECHEOS_ALLOW_SIMULATOR=1 للاختبار.",
        )
    with db.connect() as conn:
        dev = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        zone = conn.execute(
            "SELECT * FROM safe_zones WHERE enabled = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        last = conn.execute(
            "SELECT * FROM locations WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()

    if dev is None:
        # The simulator owns its own device row so it never collides with a
        # real device a caregiver paired.
        if device_id != 1:
            raise HTTPException(status_code=404, detail="لا يوجد جهاز بهذا المعرّف")
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO devices(id,name,kind,connected,simulated) "
                "VALUES (1,'جهاز المحاكاة','simulator',1,1)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO device_state(device_id,online) VALUES (1,1)"
            )
            dev = conn.execute("SELECT * FROM devices WHERE id = 1").fetchone()

    if last is None:
        if zone is None:
            raise HTTPException(
                status_code=400,
                detail="حدّدي النطاق الآمن أولًا لتكون للمحاكاة نقطة بداية",
            )
        lat, lon = zone["lat"], zone["lon"]
    else:
        # ~90 m per step so a zone of 300 m is exited in a few clicks.
        lat = last["lat"] + 0.00081
        lon = last["lon"] + 0.00081

    safety.record_location(lat, lon, device_id, 25.0, simulated=True)
    sent = safety.drain_pending_notifications(_patient_name())
    await _push_fix(device_id)
    return {"ok": True, "lat": lat, "lon": lon, "simulated": True,
            "notifications_sent": len(sent)}


class PositionFeed:
    """Tiny in-process broadcaster: every accepted fix is pushed to open
    caregiver screens so the dot moves immediately instead of on a poll."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


FEED = PositionFeed()


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket, session: str | None = Cookie(default=None)) -> None:
    """Caregiver screen: receives every new fix as it is stored."""
    if auth.user_for_token(session) is None:
        await ws.close(code=1008)
        return
    await FEED.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keepalive / ignore
    except WebSocketDisconnect:
        FEED.disconnect(ws)
    except Exception:
        FEED.disconnect(ws)


async def _push_fix(device_id: int) -> None:
    loc = safety.latest_location(device_id)
    if loc:
        await FEED.broadcast({"type": "fix", "location": loc})


# ------------------------------------------------------- face recognition ---

@app.get("/api/vision/status")
def vision_status(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM face_enrollments WHERE consent = 1").fetchone()["c"]
    return {"models_available": vision.available(), "enrolled_people": n}


@app.post("/api/vision/enroll", status_code=201)
async def vision_enroll(
    person_id: int = Form(...),
    consent: bool = Form(...),
    consented_by: str = Form(""),
    file: UploadFile = File(...), _user: dict = Depends(auth.require_user)) -> dict:
    """Enrol a consented person. Refuses without consent — no silent enrolment."""
    if not consent:
        raise HTTPException(status_code=400,
                            detail="الموافقة مطلوبة قبل تسجيل الوجه")
    with db.connect() as conn:
        person = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    if person is None:
        raise HTTPException(status_code=404, detail="unknown person")
    if not vision.available():
        raise HTTPException(status_code=503, detail="models not installed")

    raw = await file.read()
    try:
        emb = vision.embed(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="تعذّر قراءة الصورة")
    if emb is None:
        raise HTTPException(status_code=422, detail="لم أجد وجهًا واضحًا في الصورة")

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO face_enrollments(person_id,embedding,consent,consented_by) "
            "VALUES (?,?,?,?)",
            (person_id, json.dumps([float(x) for x in emb]), 1 if consent else 0, consented_by),
        )
    return {"ok": True, "person": person["name"], "enrolled": True}


@app.delete("/api/vision/enroll/{person_id}", status_code=204)
def vision_forget(person_id: int, _user: dict = Depends(auth.require_user)) -> None:
    """Deleting a person's face data — required by the brief's privacy section."""
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM face_enrollments WHERE person_id = ?", (person_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="no enrolment for that person")


@app.post("/api/vision/identify")
async def vision_identify(file: UploadFile = File(...), _user: dict = Depends(auth.require_user)) -> dict:
    """Identify the face in this frame, or refuse. Never guesses."""
    return _identify_face(await file.read())


def _identify_face(raw: bytes) -> dict:
    try:
        with db.connect() as conn:
            enrolled = conn.execute(
                "SELECT f.person_id, f.embedding, p.name, p.relation "
                "FROM face_enrollments f JOIN people p ON p.id = f.person_id "
                "WHERE f.consent = 1"
            ).fetchall()
            # Descriptors derived from uploaded photos, for people who have no
            # explicit enrollment.
            derived = conn.execute(
                "SELECT pe.person_id, pe.embedding, p.name, p.relation "
                "FROM photo_embeddings pe JOIN people p ON p.id = pe.person_id "
                "WHERE pe.person_id NOT IN "
                "(SELECT person_id FROM face_enrollments WHERE consent = 1)"
            ).fetchall()
        candidates = [
            {
                "person_id": r["person_id"],
                "name": r["name"],
                "relation": r["relation"],
                "embedding": json.loads(r["embedding"]),
            }
            for r in list(enrolled) + list(derived)
        ]
        result = vision.identify(raw, candidates)
    except ValueError:
        raise HTTPException(status_code=400, detail="تعذّر قراءة الصورة")

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO recognition_log(outcome,reason,person_id,similarity) VALUES (?,?,?,?)",
            (result["status"], result.get("reason"), result.get("person_id"),
             result.get("similarity")),
        )
        # If recognised, attach what the family wrote about this person.
        if result["status"] == "recognised":
            mems = conn.execute(
                "SELECT fact FROM memories WHERE subject = ? ORDER BY id LIMIT 2",
                (result["name"],),
            ).fetchall()
            result["memories"] = [m["fact"] for m in mems]
            # and any place memories, so it can "remind him of things"
            place = conn.execute(
                "SELECT fact FROM memories WHERE kind IN ('place','routine') ORDER BY id LIMIT 1"
            ).fetchone()
            if place:
                result["context"] = place["fact"]

            # If this person exists in the memory NETWORK, pull what is
            # connected to them — places, events, photos.
            node = conn.execute(
                "SELECT id FROM nodes WHERE kind='person' AND label = ? LIMIT 1",
                (result["name"],),
            ).fetchone()
            if node:
                recalled = network.recall_from(node["id"])
                result["network"] = [r.__dict__ for r in recalled]
                result["network_summary"] = network.describe_recall(recalled) or None

    return result


class SceneIn(BaseModel):
    """A frame to test against the registered places/objects."""


def _scene_facts(match: dict) -> list[dict]:
    """What the family wrote about a photographed place/object."""
    facts = []
    with db.connect() as conn:
        mem = conn.execute("SELECT subject, fact FROM memories WHERE id=?",
                           (match.get("memory_id"),)).fetchone()
        ann = conn.execute(
            "SELECT * FROM media_annotations WHERE media_type='photo' AND media_id=?",
            (match.get("photo_id"),)).fetchone()
    if mem and mem["subject"] != PATIENT_MEMORY_SUBJECT and mem["fact"]:
        facts.append({"source": f"memories:{match.get('memory_id')}", "text": mem["fact"]})
    if ann:
        for t in (ann["description"], ann["function_text"]):
            if t:
                facts.append({"source": f"media:photo:{match.get('photo_id')}", "text": t})
        if ann["related_to"]:
            facts.append({"source": "media:related",
                          "text": f"مرتبط بـ {ann['related_to']}"})
    label = match.get("label") or ""
    facts += companion.find_memories([label]) if label else []
    return facts


_FOCUS: dict[str, int] = {}   # consecutive frames each object stayed in view


@app.post("/api/vision/observe")
async def vision_observe(file: UploadFile = File(...), use_ai: bool = Form(True), _user: dict = Depends(auth.require_user)) -> dict:
    """One frame from the necklace camera -> what to say, and whom to alert.

    Order of trust: a recognised family face, then a place/object the family
    photographed, then everyday objects (local detector / AI vision). Each
    spoken reminder must be backed by something the family wrote.
    """
    raw = await file.read()
    try:
        img = vision._decode(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="تعذّر قراءة الصورة")
    out: dict = {"face": None, "scene": None, "objects": [], "alerts": [],
                 "speak": [], "reminder": None, "ai_used": False,
                 "detector": objects.available()}
    speak_warn, speak_face, speak_mem = [], [], []

    # 1) faces
    if vision.available():
        try:
            face = _identify_face(raw)
        except HTTPException:
            face = None
        out["face"] = face
        # A family member within 5 metres: remind him who it is (+ one memory),
        # once an hour at most. Someone farther away is not mentioned.
        if face and face.get("status") == "recognised":
            dist = face.get("distance_m")
            if dist is None or dist <= companion.PERSON_MAX_M:
                rem = companion.reminder_for(
                    face["name"], [face["name"]], f"person:{face['person_id']}",
                    cooldown=3600, mode="person",
                    facts_override=companion.person_facts(
                        face["person_id"], face["name"], face.get("relation") or ""))
                if rem:
                    speak_face.append(rem["text"])

    # 2) a place / object the family photographed
    with db.connect() as conn:
        scenes = [dict(r) for r in conn.execute(
            "SELECT photo_id, memory_id, label, descriptor FROM scene_embeddings")]
    if scenes:
        try:
            sc = vision.identify_scene(raw, scenes)
        except Exception:
            sc = {"status": "refused"}
        out["scene"] = sc
        if sc.get("status") == "recognised":
            with db.connect() as conn:
                cat = conn.execute(
                    "SELECT category FROM media_annotations WHERE media_type='photo' "
                    "AND media_id=?", (sc.get("photo_id"),)).fetchone()
            is_place = bool(cat and cat["category"] == "place")
            # a place is discussed even from far; a photographed object only
            # when it fills the view (a SIFT match needs it big and close)
            rem = companion.reminder_for(sc["label"], [sc["label"]],
                                         f"scene:{sc.get('photo_id')}", cooldown=7200,
                                         facts_override=_scene_facts(sc) or None,
                                         mode="place" if is_place else "seen")
            if rem:
                out["reminder"] = rem
                speak_mem.append(rem["text"])

    # 3) everyday objects
    dets = objects.detect(img) if objects.available() else []
    for d in dets:
        d["source"] = "local"
    ai_scan = None
    if use_ai and ai.configured():
        lists = companion.watch_lists()
        ai_scan = ai.vision_scan(raw, companion.memory_vocabulary(),
                                 lists["allergy"], lists["danger"])
        if ai_scan:
            out["ai_used"] = True
            for o in ai_scan.get("objects") or []:
                nm = str(o.get("name_ar", "")).strip()
                if nm:
                    dets.append({"en": "", "ar": nm, "synonyms": [nm], "score": None,
                                 "near_hand": bool(o.get("touching") or o.get("eating")),
                                 "eating": bool(o.get("eating")), "source": "ai",
                                 "distance_m": o.get("distance_m")})
    for d in dets:
        d["close"] = companion.is_close(d)
    out["objects"] = [{k: d.get(k) for k in ("en", "ar", "score", "near_hand", "area",
                                             "source", "box", "close", "distance_m")}
                      for d in dets]

    # a place the AI recognises (room, building, landmark) — talked about even
    # when it is far, if the family wrote memories about it
    place = ((ai_scan or {}).get("place") or {}) if isinstance((ai_scan or {}).get("place"), dict) else {}
    place_name = str(place.get("name_ar") or "").strip()
    if place_name and place_name.lower() != "null" and not out["reminder"]:
        hits = companion.place_memories(place_name)
        if hits:
            rem = companion.reminder_for(place_name, [place_name],
                                         f"place:{companion.norm(place_name)}",
                                         cooldown=7200, facts_override=hits, mode="place")
            if rem:
                out["reminder"] = rem
                speak_mem.append(rem["text"])

    # 4) safety first
    sent, warnings = companion.check_hazards([d for d in dets if d["source"] == "local"],
                                             ai_scan)
    out["alerts"] = sent
    speak_warn += warnings

    # remember what is in front of him, for "وش هذا؟" questions
    companion.remember_seen(
        [d["ar"] for d in dets if d["en"] != "person"][:8],
        out["face"]["name"] if out["face"] and out["face"].get("status") == "recognised" else None,
        out["scene"]["label"] if out["scene"] and out["scene"].get("status") == "recognised" else None)

    # 5) memory reminder — only for a thing he is really looking at (big in the
    #    frame for several frames in a row), at most once every few hours per
    #    thing, and never "this is a cup": only the memory itself.
    # only things within his reach count; far objects are never discussed
    current = {d["en"] for d in dets if d["source"] == "local" and d["close"]}
    for k in list(_FOCUS):
        if k not in current:
            _FOCUS.pop(k)
    for k in current:
        _FOCUS[k] = _FOCUS.get(k, 0) + 1
    if not out["reminder"] and not speak_warn:
        cands = [d for d in dets if d["source"] == "local" and d["en"] != "person"
                 and d["close"] and _FOCUS.get(d["en"], 0) >= 2]
        cands += [d for d in dets if d["source"] == "ai" and d["close"]]
        for m in (ai_scan or {}).get("memory_matches") or []:
            item = str(m.get("item") if isinstance(m, dict) else m).strip()
            dist = m.get("distance_m") if isinstance(m, dict) else None
            if item and companion.is_close({"distance_m": dist} if dist is not None
                                           else {"near_hand": False, "area": 0}):
                cands.insert(0, {"en": "", "ar": item, "synonyms": [item]})
        for d in cands:
            rem = companion.reminder_for(d["ar"], d["synonyms"], f"obj:{d['en'] or d['ar']}",
                                         cooldown=6 * 3600)
            if rem:
                out["reminder"] = rem
                speak_mem.append(rem["text"])
                break

    out["speak"] = speak_warn + speak_face + speak_mem
    return out


@app.post("/api/vision/identify-scene")
async def vision_identify_scene(file: UploadFile = File(...), _user: dict = Depends(auth.require_user)) -> dict:
    """Is this a place or object the family registered?

    Face recognition runs first: a familiar face is a stronger signal than a
    familiar room. Only if no face matches do we try the scene.
    """
    raw = await file.read()

    # 1) a recognised face wins
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT pe.person_id, pe.embedding, p.name, p.relation "
                "FROM photo_embeddings pe JOIN people p ON p.id = pe.person_id"
            ).fetchall()
        face_candidates = [
            {"person_id": r["person_id"], "name": r["name"],
             "relation": r["relation"], "embedding": json.loads(r["embedding"])}
            for r in rows
        ]
        face = vision.identify(raw, face_candidates)
    except ValueError:
        raise HTTPException(status_code=400, detail="تعذّر قراءة الصورة")

    if face.get("status") == "recognised":
        face["source"] = "face"
        return face

    # 2) otherwise try the registered places / objects
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT photo_id, memory_id, label, descriptor FROM scene_embeddings"
        ).fetchall()
    scenes = [dict(r) for r in rows]
    result = vision.identify_scene(raw, scenes)
    result["source"] = "scene"
    result["face_attempt"] = face.get("reason")

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO recognition_log(outcome,reason,person_id,similarity) "
            "VALUES (?,?,?,?)",
            (result["status"], result.get("reason"),
             None, result.get("similarity")),
        )
    return result


@app.get("/api/vision/scenes")
def vision_scenes(user: dict = Depends(auth.require_user)) -> dict:
    """What places/objects the camera has been taught."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT se.photo_id, se.memory_id, se.label, m.fact "
            "FROM scene_embeddings se LEFT JOIN memories m ON m.id = se.memory_id "
            "ORDER BY se.created_at DESC"
        ).fetchall()
    return {"scenes": [dict(r) for r in rows], "count": len(rows)}


@app.get("/api/vision/log")
def vision_log(limit: int = Query(20, ge=1, le=100), _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM recognition_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"log": [dict(r) for r in rows]}


# ---------------------------------------------------------------- places ----

class PlaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)


@app.get("/api/places")
def list_places(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM places ORDER BY id").fetchall()
    return {"places": [dict(r) for r in rows]}


@app.post("/api/places", status_code=201)
def add_place(p: PlaceIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO places(name,description) VALUES (?,?)",
                (p.name.strip(), p.description.strip()),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="place already exists")
        new_id = cur.lastrowid
    return {"id": new_id, **p.model_dump()}


@app.get("/api/places/recall")
def recall_place(q: str = Query(min_length=1, max_length=80), _user: dict = Depends(auth.require_user)) -> dict:
    """Word-based place recall. Explicitly not visual place recognition."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM places WHERE name LIKE ? OR description LIKE ? LIMIT 1",
            (f"%{q}%", f"%{q}%"),
        ).fetchone()
    if row is None:
        return {"found": False, "message": "ما عندي هالمكان. ما أبي أخمّن عليك."}
    return {"found": True, "name": row["name"], "description": row["description"]}



def _auto_build_memory_graph() -> dict:
    """Create graph nodes and evidence-based links from caregiver-entered data.
    The graph never invents a relationship: links are based on explicit names,
    media annotations, and profile fields.
    """
    with db.connect() as conn:
        p=conn.execute("SELECT * FROM patient_profile WHERE id=1").fetchone()
        extra=conn.execute("SELECT * FROM patient_profile_extra WHERE patient_id=1").fetchone()
        people=conn.execute("SELECT * FROM people").fetchall()
        mems=conn.execute("SELECT * FROM memories WHERE subject != ?", (PATIENT_MEMORY_SUBJECT,)).fetchall()
        assets=conn.execute("SELECT * FROM media_annotations").fetchall()
    added=0
    root=network.upsert_node("fact","ملف المريض","مصدره المعلومات التي أدخلتها الأسرة")
    fields=[]
    if p:
        for key,label in [("routine","الروتين اليومي"),("memories","الذكريات المهمة"),("important_info","معلومات مهمة"),("preferences","التفضيلات الشخصية")]:
            value=p[key] if key in p.keys() else ""
            if value and str(value).strip():
                nid=network.upsert_node("fact",label,str(value).strip())
                if network.link(root,"يتضمن",nid): added+=1
                fields.append((label,str(value)))
    if extra:
        for key,label in [("childhood","ذكريات الطفولة"),("life_events","أحداث الحياة"),("hobbies","الهوايات"),("favourite_places","الأماكن المفضلة")]:
            value=extra[key] if key in extra.keys() else ""
            if value and str(value).strip():
                nid=network.upsert_node("fact",label,str(value).strip())
                if network.link(root,"يتضمن",nid): added+=1
                fields.append((label,str(value)))
    people_nodes={}
    for person in people:
        nid=network.upsert_node("person",person["name"],person["relation"] or "")
        people_nodes[person["name"]]=nid
        if network.link(root,"شخص مهم في الملف",nid): added+=1
    for mem in mems:
        kind=mem["kind"] if mem["kind"] in ("person","place","event","object","fact","routine") else "fact"
        nid=network.upsert_node(kind,mem["subject"],mem["fact"])
        blob=f"{mem['subject']} {mem['fact']}"
        for name,pid in people_nodes.items():
            if name and name in blob and pid!=nid:
                if network.link(nid,"مرتبط بالشخص",pid): added+=1
        for label,value in fields:
            # Only exact, explicit phrase overlap can suggest a link.
            terms=[w for w in value.split() if len(w)>=4]
            if any(term in blob for term in terms):
                fid=network.upsert_node("fact",label,value)
                if network.link(nid,"مرتبط بمعلومة الملف",fid): added+=1
    for asset in assets:
        kind=asset["category"] if asset["category"] in ("person","place","event","object","fact","routine") else "fact"
        label=asset["title"] or f"مرفق {asset['media_type']} {asset['media_id']}"
        aid=network.upsert_node(kind,label,asset["description"] or "")
        if network.link(root,"مرفق في الملف",aid): added+=1
        target=(asset["related_to"] or "").strip()
        if target:
            found=network.find_node(None,target)
            if found and found["id"]!=aid:
                if network.link(aid,"مرتبط بـ",found["id"]): added+=1
    return {"ok":True,"new_links":added}

# ------------------------------------------------------- memory network ----

class NodeIn(BaseModel):
    kind: str = Field(pattern="^(person|place|event|object|fact)$")
    label: str = Field(min_length=1, max_length=80)
    detail: str = ""


class EdgeIn(BaseModel):
    src_id: int
    relation: str = Field(min_length=1, max_length=40)
    dst_id: int
    note: str = ""


@app.get("/api/network/nodes")
def net_nodes(kind: str | None = None, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        if kind:
            rows = conn.execute("SELECT * FROM nodes WHERE kind = ? ORDER BY label", (kind,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM nodes ORDER BY kind, label").fetchall()
    return {"nodes": [dict(r) for r in rows]}


@app.post("/api/network/nodes", status_code=201)
def net_add_node(n: NodeIn, _user: dict = Depends(auth.require_user)) -> dict:
    nid = network.upsert_node(n.kind, n.label, n.detail or None)
    return {"id": nid, **n.model_dump()}


@app.post("/api/network/edges", status_code=201)
def net_add_edge(e: EdgeIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        ok = conn.execute("SELECT 1 FROM nodes WHERE id IN (?,?)", (e.src_id, e.dst_id)).fetchall()
    if len(ok) != 2:
        raise HTTPException(status_code=404, detail="unknown node")
    created = network.link(e.src_id, e.relation, e.dst_id, e.note or None)
    return {"created": created, **e.model_dump()}


@app.get("/api/network/recall")
def net_recall(node_id: int, depth: int = Query(2, ge=1, le=3), _user: dict = Depends(auth.require_user)) -> dict:
    """Everything connected to a node — the core retrieval."""
    res = network.recall_from(node_id, depth)
    return {
        "node_id": node_id,
        "count": len(res),
        "recalled": [r.__dict__ for r in res],
        "spoken": network.describe_recall(res) or None,
    }


@app.get("/api/network/graph")
def net_graph(limit: int = Query(200, ge=1, le=1000), _user: dict = Depends(auth.require_user)) -> dict:
    _auto_build_memory_graph()
    with db.connect() as conn:
        nodes = conn.execute("SELECT * FROM nodes LIMIT ?", (limit,)).fetchall()
        edges = conn.execute("SELECT * FROM edges LIMIT ?", (limit,)).fetchall()
    return {"nodes": [dict(r) for r in nodes], "edges": [dict(r) for r in edges]}


@app.post("/api/network/investigate")
def net_investigate(web: bool = True, use_ai: bool = True,
                    user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Rebuild the investigator board: evidence, conversations, internet, AI."""
    _auto_build_memory_graph()
    return investigate.run(use_web=web, use_ai=use_ai)


@app.delete("/api/network/edges/{edge_id}", status_code=204)
def net_delete_edge(edge_id: int, user: dict = Depends(auth.require_role("caregiver"))) -> None:
    """Let the family cut a string they disagree with (e.g. an AI suggestion)."""
    with db.connect() as conn:
        conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))


# ------------------------------------------------------------- reminders ---

class ReminderIn(BaseModel):
    kind: str = Field(pattern="^(medication|appointment|routine|event)$")
    title: str = Field(min_length=1, max_length=120)
    detail: str = ""
    due_at: str = Field(min_length=8, max_length=40)


@app.get("/api/reminders")
def list_reminders(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders ORDER BY due_at LIMIT 100"
        ).fetchall()
    return {"reminders": [dict(r) for r in rows]}


@app.post("/api/reminders", status_code=201)
def add_reminder(r: ReminderIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO reminders(kind,title,detail,due_at) VALUES (?,?,?,?)",
            (r.kind, r.title.strip(), r.detail, r.due_at),
        )
        rid = cur.lastrowid
    return {"id": rid, **r.model_dump()}


@app.put("/api/reminders/{rid}/done")
def complete_reminder(rid: int, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE reminders SET done_at = datetime('now') WHERE id = ? AND done_at IS NULL",
            (rid,),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="not found or already done")
    return {"ok": True, "id": rid}


# -------------------------------------------------------- memory review ----

@app.post("/api/review/start", status_code=201)
def review_start(count: int = Query(3, ge=1, le=10), _user: dict = Depends(auth.require_user)) -> dict:
    """Ask a few questions generated FROM the user's own memory network."""
    with db.connect() as conn:
        people = conn.execute(
            "SELECT id,label FROM nodes WHERE kind='person' ORDER BY RANDOM() LIMIT ?", (count,)
        ).fetchall()
        sid = conn.execute("INSERT INTO review_sessions DEFAULT VALUES").lastrowid
        qs = []
        for p in people:
            q = f"من هو {p['label']}؟"
            expected = p["label"]
            conn.execute(
                "INSERT INTO review_answers(session_id,node_id,question,expected) VALUES (?,?,?,?)",
                (sid, p["id"], q, expected),
            )
            qs.append({"question": q, "expected": expected})
    return {"session_id": sid, "questions": qs,
            "note": "هذه أسئلة مراجعة من شبكة ذاكرتكم — ليست تشخيصًا طبيًا."}


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=120)
    hint_used: bool = False


@app.post("/api/review/{sid}/answer")
def review_answer(sid: int, body: AnswerIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_answers WHERE session_id = ? AND answered IS NULL LIMIT 1",
            (sid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no pending question")
        correct = 1 if body.answer.strip() == row["expected"].strip() else 0
        conn.execute(
            "UPDATE review_answers SET answered=?, is_correct=?, hint_used=? WHERE id=?",
            (body.answer, correct, 1 if body.hint_used else 0, row["id"]),
        )
        conn.execute(
            "UPDATE review_sessions SET asked = asked + 1, correct = correct + ?, "
            "hints = hints + ? WHERE id = ?",
            (correct, 1 if body.hint_used else 0, sid),
        )
    return {"correct": bool(correct), "expected": row["expected"]}


@app.get("/api/review/{sid}/report")
def review_report(sid: int, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        s = conn.execute("SELECT * FROM review_sessions WHERE id=?", (sid,)).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="unknown session")
        ans = conn.execute(
            "SELECT question, expected, answered, is_correct, hint_used "
            "FROM review_answers WHERE session_id=? ORDER BY id", (sid,)
        ).fetchall()
    return {
        "session": dict(s),
        "answers": [dict(a) for a in ans],
        "disclaimer": (
            "هذه نتائج جلسة مراجعة فقط. ليست تشخيصًا طبيًا ولا مقياسًا "
            "لتطور المرض، وتحسّن السؤال المتكرر لا يعني استرجاعًا حقيقيًا."
        ),
    }


# --------------------------------------------------- emergency card -------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    return (BASE / "templates" / "dashboard.html").read_text(encoding="utf-8")


@app.get("/profile", response_class=HTMLResponse)
def profile_page() -> str:
    return (BASE / "templates" / "profile.html").read_text(encoding="utf-8")


@app.get("/caregivers", response_class=HTMLResponse)
def caregivers_page() -> str:
    return (BASE / "templates" / "caregivers.html").read_text(encoding="utf-8")


@app.get("/network", response_class=HTMLResponse)
def network_page() -> str:
    return (BASE / "templates" / "network.html").read_text(encoding="utf-8")


@app.get("/device", response_class=HTMLResponse)
def device_page() -> str:
    return (BASE / "templates" / "device.html").read_text(encoding="utf-8")


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    return (BASE / "templates" / "settings.html").read_text(encoding="utf-8")


@app.get("/emergency-center", response_class=HTMLResponse)
def emergency_center_page() -> str:
    return (BASE / "templates" / "emergency-center.html").read_text(encoding="utf-8")


@app.get("/emergency", response_class=HTMLResponse)
def emergency_page() -> str:
    return (BASE / "templates" / "emergency.html").read_text(encoding="utf-8")


@app.get("/api/emergency/card")
def emergency_card() -> dict:
    with db.connect() as conn:
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
        contact = conn.execute(
            "SELECT name, relation FROM people ORDER BY id LIMIT 1"
        ).fetchone()
    return {
        "first_name": settings.get("first_name", "محمد"),
        "contact_name": (contact["name"] if contact else None),
        "contact_relation": (contact["relation"] if contact else None),
        "message": "أحتاج مساعدة. من فضلك تواصل مع عائلتي.",
        "note": "تظهر فقط المعلومات التي وافقت عليها الأسرة.",
    }


# --------------------------------------------------------- patient profile --

class PatientExtraIn(BaseModel):
    nickname: str = ""
    date_of_birth: str = ""
    gender: str = ""
    language: str = "ar"
    dialect: str = ""
    phone: str = ""
    birthplace: str = ""
    childhood: str = ""
    occupation: str = ""
    education: str = ""
    life_events: str = ""
    hobbies: str = ""
    favourite_activities: str = ""
    favourite_foods: str = ""
    favourite_drinks: str = ""
    favourite_music: str = ""
    favourite_places: str = ""
    favourite_topics: str = ""
    comfort_items: str = ""
    confusion_triggers: str = ""
    medications: str = ""
    medication_schedule: str = ""
    medical_instructions: str = ""
    mobility: str = ""
    allergy_items: str = ""
    danger_items: str = ""
    private_topics: str = ""
    home_lat: float | None = None
    home_lon: float | None = None


class PatientIn(BaseModel):
    full_name: str = ""
    age: int | None = None
    photo_path: str | None = None
    home_address: str = ""
    medical_info: str = ""
    allergies: str = ""
    emergency_notes: str = ""
    important_info: str = ""
    routine: str = ""
    preferences: str = ""
    memories: str = ""
    reminder_scope: str = ""


EXTRA_FIELDS = [
    "nickname", "date_of_birth", "gender", "language", "dialect",
    "phone", "birthplace", "childhood", "occupation", "education",
    "life_events", "hobbies", "favourite_activities", "favourite_foods",
    "favourite_drinks", "favourite_music", "favourite_places",
    "favourite_topics", "comfort_items", "confusion_triggers",
    "medications", "medication_schedule", "medical_instructions",
    "mobility",
]

# Required for the completion indicator. Name/age/address are the minimum a
# useful assistant needs; the rest improve personalisation.
COMPLETION_REQUIRED = [
    "full_name", "age", "home_address", "medical_info", "emergency_notes",
    "routine", "nickname", "date_of_birth", "occupation", "hobbies",
    "favourite_foods", "medications", "comfort_items", "confusion_triggers",
]

PATIENT_FIELDS = [
    "full_name", "age", "photo_path", "home_address", "medical_info",
    "allergies", "emergency_notes", "important_info", "routine",
    "preferences", "memories", "reminder_scope",
]


def _ensure_patient() -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO patient_profile(id) VALUES (1)")


@app.get("/api/patient")
def get_patient(user: dict = Depends(auth.require_user)) -> dict:
    _ensure_patient()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM patient_profile WHERE id = 1").fetchone()
    return dict(row)


@app.put("/api/patient")
def update_patient(p: PatientIn, user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Every field editable from the dashboard — no code change required."""
    _ensure_patient()
    data = p.model_dump()
    sets = ", ".join(f"{f} = ?" for f in PATIENT_FIELDS)
    vals = [data[f] for f in PATIENT_FIELDS]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE patient_profile SET {sets}, updated_at = datetime('now') WHERE id = 1",
            vals,
        )
        row = conn.execute("SELECT * FROM patient_profile WHERE id = 1").fetchone()
    _auto_build_memory_graph()
    return dict(row)


@app.get("/api/patient/reminder-scope")
def get_scope(_user: dict = Depends(auth.require_user)) -> dict:
    _ensure_patient()
    with db.connect() as conn:
        row = conn.execute("SELECT reminder_scope FROM patient_profile WHERE id = 1").fetchone()
    return {"reminder_scope": row["reminder_scope"] or ""}


# ------------------------------------------------------------- caregivers ---

class CaregiverIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=80)
    relation: str = ""
    phone: str = ""
    email: str = ""
    emergency_contact: str = ""
    is_primary: bool = False


@app.get("/api/caregivers")
def list_caregivers(user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM caregivers ORDER BY is_primary DESC, id"
        ).fetchall()
    return {"caregivers": [dict(r) for r in rows]}


@app.post("/api/caregivers", status_code=201)
def add_caregiver(c: CaregiverIn, user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    with db.connect() as conn:
        if c.is_primary:
            conn.execute("UPDATE caregivers SET is_primary = 0")
        cur = conn.execute(
            "INSERT INTO caregivers(full_name,relation,phone,email,emergency_contact,is_primary) "
            "VALUES (?,?,?,?,?,?)",
            (c.full_name.strip(), c.relation, c.phone, c.email,
             c.emergency_contact, 1 if c.is_primary else 0),
        )
        cid = cur.lastrowid
    return {"id": cid, **c.model_dump()}


@app.put("/api/caregivers/{cid}")
def update_caregiver(cid: int, c: CaregiverIn, _user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        if c.is_primary:
            conn.execute("UPDATE caregivers SET is_primary = 0")
        cur = conn.execute(
            "UPDATE caregivers SET full_name=?, relation=?, phone=?, email=?, "
            "emergency_contact=?, is_primary=? WHERE id=?",
            (c.full_name.strip(), c.relation, c.phone, c.email,
             c.emergency_contact, 1 if c.is_primary else 0, cid),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="caregiver not found")
    return {"id": cid, **c.model_dump()}


@app.delete("/api/caregivers/{cid}", status_code=204)
def delete_caregiver(cid: int, _user: dict = Depends(auth.require_user)) -> None:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM caregivers WHERE id = ?", (cid,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="caregiver not found")


# -------------------------------------------------------------- dashboard ---

def _patient_name() -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT full_name FROM patient_profile WHERE id = 1").fetchone()
    return (row["full_name"] if row and row["full_name"] else "")


# ---------------------------------------------------- notification config --

class NotifIn(BaseModel):
    channel: str = Field(default="none", pattern="^(none|telegram|whatsapp|email|both)$")
    telegram_token: str = ""
    telegram_chat_id: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_to: str = ""
    smtp_host: str = ""
    smtp_port: str = "587"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    email_to: str = ""


@app.get("/api/notify/settings")
def get_notif_settings(user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Secrets are masked on read — a token is never echoed back in full."""
    with db.connect() as conn:
        s = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM notif_settings")}
    # Env vars override the saved settings, so report what will actually be used.
    eff = notify._settings()
    token = (eff.get("telegram_token") or "").strip()
    chat = (eff.get("telegram_chat_id") or "").strip()
    channel = eff.get("channel", "none")
    masked = (token[:6] + "…" + token[-4:]) if len(token) > 12 else ("*" * len(token))

    wa_token = (eff.get("whatsapp_token") or "").strip()
    wa_phone = (eff.get("whatsapp_phone_id") or "").strip()
    wa_to = (eff.get("whatsapp_to") or "").strip()

    smtp_host = (eff.get("smtp_host") or "").strip()
    smtp_user = (eff.get("smtp_user") or "").strip()
    email_to = (eff.get("email_to") or "").strip()

    if channel in ("email", "both") and smtp_host.isdigit():
        reason = "smtp_host_is_port"
    elif channel in ("email", "both") and not smtp_host:
        reason = "missing_smtp_host"
    elif channel == "email" and not email_to:
        reason = "missing_email_to"
    elif channel in ("telegram", "both") and not token:
        reason = "missing_token"
    elif channel in ("telegram", "both") and not chat:
        reason = "missing_chat_id"
    elif channel == "whatsapp" and not wa_token:
        reason = "missing_wa_token"
    elif channel == "whatsapp" and not wa_phone:
        reason = "missing_wa_phone_id"
    elif channel == "whatsapp" and not wa_to:
        reason = "missing_wa_to"
    elif channel == "none":
        reason = "no_channel"
    else:
        reason = "ready"

    return {
        "channel": channel,
        "credential_source": eff.get("_credential_source", "settings"),
        "telegram_token_masked": masked,
        "telegram_token_set": bool(token),
        "telegram_chat_id": chat,
        "whatsapp_token_masked": (("*" * 8) if wa_token else ""),
        "whatsapp_token_set": bool(wa_token),
        "whatsapp_phone_id": wa_phone,
        "whatsapp_to": wa_to,
        "smtp_host": smtp_host,
        "smtp_port": (eff.get("smtp_port") or "587"),
        "smtp_user": smtp_user,
        "smtp_from": (eff.get("smtp_from") or ""),
        "smtp_password_set": bool((eff.get("smtp_password") or "").strip()),
        "email_to": email_to,
        "ready": reason == "ready",
        "reason": reason,
    }


@app.put("/api/notify/settings")
def set_notif_settings(n: NotifIn, user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    pairs = {
        "channel": n.channel,
        "telegram_chat_id": n.telegram_chat_id,
        "whatsapp_phone_id": n.whatsapp_phone_id,
        "whatsapp_to": n.whatsapp_to,
    }
    if n.whatsapp_token:
        pairs["whatsapp_token"] = secrets_mod.encrypt(n.whatsapp_token)
    pairs.update({
        "smtp_host": n.smtp_host,
        "smtp_port": n.smtp_port or "587",
        "smtp_user": n.smtp_user,
        "smtp_from": n.smtp_from,
        "email_to": n.email_to,
    })
    if n.smtp_password:
        pairs["smtp_password"] = secrets_mod.encrypt(n.smtp_password)
    # Only overwrite the token when a new one is supplied, so a masked
    # placeholder can never wipe the real secret.
    if n.telegram_token:
        # Never persist a credential in plaintext.
        pairs["telegram_token"] = secrets_mod.encrypt(n.telegram_token)
    with db.connect() as conn:
        for k, v in pairs.items():
            conn.execute(
                "INSERT INTO notif_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v)
            )
    return {"ok": True, "channel": n.channel}


@app.get("/api/notify/outbox")
def get_outbox(limit: int = Query(50, ge=1, le=200), user: dict = Depends(auth.require_user)) -> dict:
    return {"outbox": notify.outbox(limit)}


class TgLinkIn(BaseModel):
    token: str = ""


@app.post("/api/telegram/link/start")
def tg_link_start(body: TgLinkIn, user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Paste the bot token once -> a t.me link + QR for family members."""
    from . import telegram_link
    return telegram_link.start(body.token)


@app.post("/api/telegram/link/check")
def tg_link_check(user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    from . import telegram_link
    return telegram_link.check()


@app.get("/api/telegram/status")
def tg_status(user: dict = Depends(auth.require_user)) -> dict:
    from . import telegram_link
    return telegram_link.status()


@app.post("/api/telegram/link/clear")
def tg_link_clear(user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    from . import telegram_link
    telegram_link.unlink_all()
    return {"ok": True}


@app.post("/api/notify/test")
def test_notification(_user: dict = Depends(auth.require_user)) -> dict:
    """Send a test message. Reports the real outcome, including failure."""
    with db.connect() as conn:
        s = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM notif_settings")}
    name = _patient_name()
    # Same format as a real exit, so the caregiver sees exactly what will arrive.
    live_url = notify.create_temporary_live_share(hours=1, wait_seconds=15)
    msg = notify.compose_exit(name, 24.7136, 46.6753, live_url)
    msg["text"] += "\n\n🧪 رسالة تجريبية — ليست حالة حقيقية"
    r = notify.deliver(0, msg, name)
    r["public_link"] = bool(live_url)
    r["tunnel"] = tunnel.status()
    return r


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(auth.require_user)) -> dict:
    """One call for the overview screen."""
    _ensure_patient()
    with db.connect() as conn:
        patient = dict(conn.execute("SELECT * FROM patient_profile WHERE id = 1").fetchone())
        dev = conn.execute("SELECT * FROM devices ORDER BY id LIMIT 1").fetchone()
        last = conn.execute(
            "SELECT * FROM locations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        alerts = conn.execute(
            "SELECT * FROM alerts WHERE read_at IS NULL ORDER BY id DESC LIMIT 3"
        ).fetchall()
        caregivers = conn.execute(
            "SELECT full_name, relation, phone FROM caregivers "
            "ORDER BY is_primary DESC, id LIMIT 3"
        ).fetchall()
    loc = safety.latest_location(dev["id"]) if dev else None
    inside = None
    if loc:
        with db.connect() as conn:
            zones = conn.execute("SELECT * FROM safe_zones WHERE enabled = 1").fetchall()
        inside = all(
            safety.haversine_m(loc["lat"], loc["lon"], z["lat"], z["lon"]) <= z["radius_m"]
            for z in zones
        ) if zones else None
    return {
        "patient_name": patient["full_name"] or "المريض",
        "inside_safe_zone": inside,
        "battery": dev["battery"] if dev else None,
        "device_connected": bool(dev["connected"]) if dev else False,
        "last_location": loc,
        "open_alerts": [dict(a) for a in alerts],
        "caregivers": [dict(c) for c in caregivers],
        "reminder_scope": patient["reminder_scope"] or "",
    }


# ------------------------------------------------------- assistant config ---

class SettingsIn(BaseModel):
    assistant_name: str = "ECHOES"
    wake_phrase: str = "يا إيكوس"
    language: str = "ar"
    voice_enabled: bool = True
    proactive_reminders: bool = True


@app.get("/api/assistant/settings")
def get_assistant_settings(_user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM assistant_settings")}
    return {
        "assistant_name": rows.get("assistant_name", "ECHOES"),
        "wake_phrase": rows.get("wake_phrase", "يا إيكوس"),
        "language": rows.get("language", "ar"),
        "voice_enabled": rows.get("voice_enabled", "1") == "1",
        "proactive_reminders": rows.get("proactive_reminders", "1") == "1",
    }


@app.put("/api/assistant/settings")
def set_assistant_settings(s: SettingsIn, _user: dict = Depends(auth.require_user)) -> dict:
    pairs = {
        "assistant_name": s.assistant_name,
        "wake_phrase": s.wake_phrase,
        "language": s.language,
        "voice_enabled": "1" if s.voice_enabled else "0",
        "proactive_reminders": "1" if s.proactive_reminders else "0",
    }
    with db.connect() as conn:
        for k, v in pairs.items():
            conn.execute(
                "INSERT INTO assistant_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, v),
            )
    return s.model_dump()


class AISettingsIn(BaseModel):
    ai_key: str = ""                 # empty = keep the stored key
    clear_key: bool = False
    ai_model: str = ai.DEFAULT_MODEL
    ai_web: bool = True
    ai_vision: bool = True
    ai_interval: float = Field(default=6, ge=2, le=120)
    reply_delay: int = Field(default=13, ge=3, le=120)


@app.get("/api/ai/settings")
def get_ai_settings(user: dict = Depends(auth.require_user)) -> dict:
    s = ai.settings()
    k = s["key"]
    return {"key_set": bool(k), "key_masked": (k[:7] + "…" + k[-4:]) if len(k) > 12 else "",
            "ai_model": s["model"], "ai_web": s["web"], "ai_vision": s["vision"],
            "ai_interval": s["interval"], "reply_delay": s["reply_delay"],
            "object_detector": objects.available()}


@app.put("/api/ai/settings")
def set_ai_settings(b: AISettingsIn, user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    pairs = {"ai_model": b.ai_model.strip() or ai.DEFAULT_MODEL,
             "ai_web": "1" if b.ai_web else "0", "ai_vision": "1" if b.ai_vision else "0",
             "ai_interval": str(b.ai_interval), "reply_delay": str(b.reply_delay)}
    if b.ai_key.strip():
        pairs["ai_key"] = secrets_mod.encrypt(b.ai_key.strip())
    if b.clear_key:
        pairs["ai_key"] = ""
    with db.connect() as conn:
        for k, v in pairs.items():
            conn.execute("INSERT INTO assistant_settings(key,value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
    return get_ai_settings(user)


@app.get("/api/companion/config")
def companion_config(_user: dict = Depends(_patient_link.require_patient_or_caregiver)) -> dict:
    """What the camera/voice pages need to know (no secrets)."""
    s = ai.settings()
    return {"reply_delay": s["reply_delay"], "ai": bool(s["key"]),
            "object_detector": objects.available(), "face_models": vision.available(),
            "wake_phrase": get_assistant_settings().get("wake_phrase", "")}


# ------------------------------------------------------------------- auth ---

class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=1, max_length=80)
    role: str = Field(default="caregiver", pattern="^(viewer|caregiver|owner)$")


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return (BASE / "templates" / "login.html").read_text(encoding="utf-8")


@app.get("/api/auth/status")
def auth_status(session: str | None = Cookie(default=None)) -> dict:
    u = auth.user_for_token(session)
    return {"authenticated": bool(u), "user": u,
            "needs_setup": auth.count_users() == 0}


@app.post("/api/auth/register")
def register(body: RegisterIn, response: Response) -> dict:
    """The first account is always an owner; later accounts need an owner."""
    first = auth.count_users() == 0
    if first and _cloud():
        raise HTTPException(status_code=403,
                            detail="على الخادم يُنشأ حساب المسؤول من إعدادات Render (ECHOES_OWNER_EMAIL و ECHOES_OWNER_PASSWORD)")
    if not first:
        raise HTTPException(status_code=403,
                            detail="التسجيل مفتوح للاستخدام الأول فقط — أضف الحسابات من الإعدادات")
    role = "owner" if first else body.role
    try:
        uid = auth.create_user(body.email, body.password, body.full_name, role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=409, detail="البريد مستخدم مسبقًا")
    token = auth.new_session(uid)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=12 * 3600)
    tunnel.start_async()   # owner exists now — safe to open the public link
    return {"ok": True, "user": {"id": uid, "email": body.email,
                                 "full_name": body.full_name, "role": role}}


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response) -> dict:
    u = auth.authenticate(body.email, body.password)
    if not u:
        raise HTTPException(status_code=401, detail="البريد أو كلمة المرور غير صحيحة")
    token = auth.new_session(u["id"])
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=12 * 3600)
    return {"ok": True, "user": {"id": u["id"], "email": u["email"],
                                 "full_name": u["full_name"], "role": u["role"]}}


@app.post("/api/auth/logout")
def logout(response: Response, session: str | None = Cookie(default=None)) -> dict:
    if session:
        auth.end_session(session)
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/auth/users")
def list_users(user: dict = Depends(auth.require_role("owner"))) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id,email,full_name,role,created_at FROM users ORDER BY id"
        ).fetchall()
    return {"users": [dict(r) for r in rows]}


@app.post("/api/auth/users", status_code=201)
def add_user(body: RegisterIn, user: dict = Depends(auth.require_role("owner"))) -> dict:
    try:
        uid = auth.create_user(body.email, body.password, body.full_name, body.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=409, detail="البريد مستخدم مسبقًا")
    return {"ok": True, "id": uid}


# ------------------------------------------------------- connection events --

@app.post("/api/alerts/check-battery")
def check_battery(_user: dict = Depends(auth.require_user)) -> dict:
    """Raise a low-battery alert once per threshold band."""
    return {"raised": safety.check_battery_alerts(_patient_name())}


@app.post("/api/alerts/check-connection")
def check_connection(_user: dict = Depends(auth.require_user)) -> dict:
    """Detect devices that went quiet and alert on the transition only."""
    return safety.check_connection_events(_patient_name())


@app.post("/api/bot/poll")
def bot_poll(_user: dict = Depends(auth.require_user)) -> dict:
    """Answer any pending Telegram commands (/where, /status)."""
    n = bot.poll_once()
    return {"handled": n}


@app.get("/api/bot/preview/where")
def bot_preview_where(_user: dict = Depends(auth.require_user)) -> dict:
    return {"text": bot.build_where()}


@app.get("/api/bot/preview/status")
def bot_preview_status(_user: dict = Depends(auth.require_user)) -> dict:
    return {"text": bot.build_status()}


# ------------------------------------------------------------ photographs --

@app.post("/api/patient/photo")
async def upload_patient_photo(file: UploadFile = File(...),
                               user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    _ensure_patient()
    data = await file.read()
    try:
        info = media.save_photo("patient", 1, data)
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with db.connect() as conn:
        conn.execute("UPDATE patient_profile SET photo_path = ? WHERE id = 1",
                     (info["filename"],))
    return {"ok": True, **info}


@app.post("/api/family/{person_id}/photo")
async def upload_family_photo(person_id: int, file: UploadFile = File(...),
                              user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="unknown person")
    data = await file.read()
    try:
        info = media.save_photo("person", person_id, data)
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Derive a face descriptor so this photo can be used for recognition
    # without a separate enrolment step.
    recognised = False
    if vision.available():
        try:
            emb = vision.embed(data)
        except Exception:
            emb = None
        if emb is not None:
            with db.connect() as conn:
                pid = conn.execute(
                    "SELECT id FROM photos WHERE owner_type='person' AND owner_id=? "
                    "ORDER BY id DESC LIMIT 1", (person_id,)
                ).fetchone()["id"]
                conn.execute(
                    "INSERT OR REPLACE INTO photo_embeddings(photo_id,person_id,embedding) "
                    "VALUES (?,?,?)",
                    (pid, person_id, json.dumps([float(x) for x in emb])),
                )
            recognised = True

    return {"ok": True, **info, "face_descriptor_created": recognised}


@app.get("/api/patient/photo")
def get_patient_photo(user: dict = Depends(auth.require_user)):
    got = media.get_photo("patient", 1)
    if got is None:
        raise HTTPException(status_code=404, detail="no photo")
    return FileResponse(got["path"], media_type=got["mime"])


@app.get("/api/family/{person_id}/photo")
def get_family_photo(person_id: int, user: dict = Depends(auth.require_user)):
    got = media.get_photo("person", person_id)
    if got is None:
        raise HTTPException(status_code=404, detail="no photo")
    return FileResponse(got["path"], media_type=got["mime"])


@app.delete("/api/family/{person_id}", status_code=204)
def delete_person(person_id: int,
                  user: dict = Depends(auth.require_role("caregiver"))) -> None:
    """Remove a family member, their photo, and their face descriptor."""
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM people WHERE id = ?", (person_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown person")
    media.delete_photo("person", person_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM photo_embeddings WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM face_enrollments WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM people WHERE id = ?", (person_id,))


@app.delete("/api/family/{person_id}/photo", status_code=204)
def delete_family_photo(person_id: int,
                        user: dict = Depends(auth.require_role("caregiver"))) -> None:
    if not media.delete_photo("person", person_id):
        raise HTTPException(status_code=404, detail="no photo")


# ---------------------------------------------------------- real GPS device --

class DeviceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="wearable", pattern="^(wearable|phone)$")


class DeviceReportIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None
    battery: int | None = Field(default=None, ge=0, le=100)


@app.post("/api/devices/pair", status_code=201)
def pair_device(d: DeviceCreateIn, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Create a real device. The token is shown ONCE."""
    try:
        created = dev_mod.create_device(d.name, d.kind)
    except Exception:
        raise HTTPException(status_code=409, detail="اسم الجهاز مستخدم")
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO device_state(device_id,online) VALUES (?,0)",
                     (created["id"],))
    return {"ok": True, **created,
            "note": "احفظي هذا الرمز الآن — لن يُعرض مرة أخرى."}


@app.post("/api/devices/{device_id}/rotate-token")
def rotate_device_token(device_id: int,
                        user: dict = Depends(auth.require_role("owner"))) -> dict:
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="unknown device")
    return {"ok": True, "token": dev_mod.rotate_token(device_id)}


# ------------------------------------------------ Wear OS watch pairing ---

@app.post("/api/devices/watch-code")
def watch_code(user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Short code typed once into the ECHOES app on the patient's watch."""
    from . import watch_relay
    base = tunnel.public_base(wait_seconds=20)
    if not base:
        return {"ok": False, "public": False, "tunnel": tunnel.status()}
    return {"ok": True, "public": True, "url": base, **watch_relay.new_code(base)}


class ScanIn(BaseModel):
    qr: str = Field(min_length=10, max_length=80)


@app.post("/api/devices/watch-scan")
def watch_scan(body: ScanIn, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """QR shown on the watch -> pair it (the watch completes it by itself)."""
    from . import watch_relay
    text = body.qr.strip()
    if not text.upper().startswith("ECHOES:"):
        raise HTTPException(status_code=400, detail="هذا ليس رمز ساعة ECHOES")
    base = tunnel.public_base(wait_seconds=20)
    if not base:
        return {"ok": False, "public": False, "tunnel": tunnel.status()}
    out = watch_relay.scan(text.split(":", 1)[1], base)
    if not out:
        raise HTTPException(status_code=400, detail="رمز الساعة غير صالح")
    return {"ok": True, "public": True, **out}


class ClaimIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@app.post("/api/devices/claim")
def watch_claim(body: ClaimIn) -> dict:
    """Called by the watch app. Single-use, expires after 15 minutes."""
    from . import watch_relay
    out = watch_relay.claim(body.code)
    if not out:
        raise HTTPException(status_code=400, detail="الرمز غير صحيح أو انتهت صلاحيته")
    return {"ok": True, **out}


@app.post("/api/device/sos", status_code=201)
async def device_sos(authorization: str | None = Header(default=None)) -> dict:
    """The patient pressed «أحتاج مساعدة» on the watch."""
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    dev = dev_mod.resolve_token(token)
    if dev is None:
        raise HTTPException(status_code=401, detail="رمز الجهاز غير صالح")
    res = safety.request_help(dev["id"])
    sent = safety.drain_pending_notifications(_patient_name())
    return {**res, "notifications_sent": len(sent)}


def _device_from_auth(authorization: str | None) -> dict:
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    dev = dev_mod.resolve_token(token)
    if dev is None:
        raise HTTPException(status_code=401, detail="رمز الجهاز غير صالح")
    return dev


@app.post("/api/device/ask")
def device_ask(body: HearIn, authorization: str | None = Header(default=None)) -> dict:
    """The patient's WATCH asks the assistant (voice question, optional photo).
    Authenticated with the watch's own device token — same rules as the
    patient screen: button → answer now; someone else's question → the watch
    waits wait_seconds (13 s) and answers only if the patient stays silent;
    very private questions get no answer."""
    _device_from_auth(authorization)
    return companion_hear(body, _user={"id": 0, "role": "patient"})


@app.get("/api/device/zones")
def device_zones(authorization: str | None = Header(default=None)) -> dict:
    """Safe zones for a watch that reports only when the patient leaves them."""
    _device_from_auth(authorization)
    with db.connect() as conn:
        zones = [dict(r) for r in conn.execute(
            "SELECT name, lat, lon, radius_m FROM safe_zones WHERE enabled = 1")]
    return {"zones": zones, "heartbeat_minutes": 15}


class HeartbeatIn(BaseModel):
    battery: int | None = Field(default=None, ge=0, le=100)
    inside: bool | None = None
    zone: str | None = Field(default=None, max_length=80)


@app.post("/api/device/heartbeat")
def device_heartbeat(body: HeartbeatIn,
                     authorization: str | None = Header(default=None)) -> dict:
    """«I'm on and inside the safe zone» — no coordinates are sent."""
    dev = _device_from_auth(authorization)
    status = None if body.inside is None else ("inside" if body.inside else "outside")
    with db.connect() as conn:
        conn.execute(
            "UPDATE devices SET last_seen_at = datetime('now'), connected = 1, "
            "report_mode = 'on_exit', zone_status = COALESCE(?, zone_status), "
            "zone_checked_at = datetime('now'), battery = COALESCE(?, battery) WHERE id = ?",
            (status if status is None else (status + (":" + body.zone if body.zone else "")),
             body.battery, dev["id"]))
    safety.mark_online(dev["id"])
    return {"ok": True}


from .tracker_link import PHONE_TRACKER_NAME  # noqa: E402


@app.post("/api/tracker/pair/new")
def tracker_pair_new() -> dict:
    """Patient's phone asks for a pairing QR to show on its own screen."""
    from . import tracker_link
    return tracker_link.pair_new()


@app.get("/api/tracker/pair/{code}")
def tracker_pair_status(code: str) -> dict:
    from . import tracker_link
    return tracker_link.pair_status(code)


class PhoneScanIn(BaseModel):
    qr: str = Field(min_length=4, max_length=80)


@app.post("/api/devices/phone-scan")
def phone_scan(body: PhoneScanIn, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Caregiver scanned the QR shown on the patient's phone → link it."""
    from . import tracker_link
    r = tracker_link.pair_claim(body.qr)
    if not r["ok"]:
        raise HTTPException(status_code=404,
                            detail="انتهت صلاحية الرمز أو غير صحيح — حدّثي الصفحة على جوال المريض وامسحي الرمز الجديد.")
    return r


@app.get("/p")
def tracker_short() -> RedirectResponse:
    return RedirectResponse("/tracker", status_code=302)


@app.post("/api/devices/phone-link")
def phone_link(new: bool = False, user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Link + QR for the patient's phone. Stays the same unless `new=1`
    (a new code cancels the previous phone)."""
    from . import tracker_link
    return tracker_link.get(rotate=new)


@app.post("/api/device/report", status_code=201)
async def device_report(body: DeviceReportIn,
                        authorization: str | None = Header(default=None)) -> dict:
    """Endpoint a physical device posts to. Authenticated by device token."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    dev = dev_mod.resolve_token(token)
    if dev is None:
        raise HTTPException(status_code=401, detail="رمز الجهاز غير صالح")
    if dev["simulated"]:
        raise HTTPException(
            status_code=403,
            detail="هذا جهاز محاكاة — استخدمي /api/location لوضع الاختبار",
        )

    safety.record_location(body.lat, body.lon, dev["id"], body.accuracy_m,
                           simulated=False)
    if body.battery is not None:
        with db.connect() as conn:
            conn.execute("UPDATE devices SET battery = ? WHERE id = ?",
                         (body.battery, dev["id"]))
    sent = safety.drain_pending_notifications(_patient_name())
    await _push_fix(dev["id"])
    return {"ok": True, "device": dev["name"], "simulated": False,
            "notifications_sent": len(sent)}


class PhoneFixIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: float | None = None
    timestamp: str | None = None
    device_id: int | None = None


@app.post("/api/phone/location", status_code=201)
async def phone_location(body: PhoneFixIn,
                         user: dict = Depends(auth.require_user)) -> dict:
    """A caregiver's phone reporting its own GPS.

    Same pipeline as a wearable: stored, geofenced, alerted. Authenticated by
    the caregiver session rather than a device token, because a browser on a
    phone cannot hold a bearer token safely.
    """
    dev_id = body.device_id
    if dev_id is None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM devices ORDER BY simulated ASC, id LIMIT 1"
            ).fetchone()
        dev_id = row["id"] if row else None
    if dev_id is None:
        # First fix from the patient's phone: register that phone as his
        # tracking device automatically instead of refusing.
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO devices(name,kind,simulated,connected) "
                "VALUES ('جوال المريض','phone',0,1)")
            dev_id = cur.lastrowid or conn.execute(
                "SELECT id FROM devices WHERE name='جوال المريض'").fetchone()["id"]

    with db.connect() as conn:
        dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    if dev is None:
        raise HTTPException(status_code=404, detail="unknown device")

    safety.record_location(body.lat, body.lon, dev_id, body.accuracy,
                           simulated=False, reported_at=body.timestamp)
    if not dev["simulated"]:
        with db.connect() as conn:
            conn.execute("UPDATE devices SET connected = 1 WHERE id = ?", (dev_id,))
    sent = safety.drain_pending_notifications(_patient_name())
    await _push_fix(dev_id)

    return {"ok": True, "device_id": dev_id,
            "accuracy": body.accuracy,
            "notifications_sent": len(sent)}


@app.get("/tracker", response_class=HTMLResponse)
def tracker_page() -> str:
    """The phone that carries the patient opens this page and shares its GPS."""
    return (BASE / "templates" / "tracker.html").read_text(encoding="utf-8")


@app.get("/api/device/status")
def device_status() -> dict:
    return dev_mod.status()


@app.post("/api/devices/simulator", status_code=201,
          responses={403: {"description": "simulation disabled"}})
def add_simulator(user: dict = Depends(auth.require_role("owner"))) -> dict:
    """Optional test device. Refused unless ECHEOS_ALLOW_SIMULATOR=1."""
    if os.environ.get("ECHEOS_ALLOW_SIMULATOR", "0") != "1":
        raise HTTPException(
            status_code=403,
            detail="المحاكي معطّل. شغّلي التطبيق مع ECHEOS_ALLOW_SIMULATOR=1 للاختبار.",
        )
    return {"ok": True, **dev_mod.create_simulator()}


# ------------------------------------------------- memory album + audio ----

@app.post("/api/memories/{memory_id}/photos", status_code=201)
async def add_memory_photo(memory_id: int, file: UploadFile = File(...),
                           user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Append a numbered photo to a memory. No limit on how many."""
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="الذكرى غير موجودة")
    data = await file.read()
    try:
        info = media.save_album_photo(memory_id, data)
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Learn this place/object visually so the camera can match it later.
    learned = False
    if vision.available():
        try:
            desc = vision.scene_descriptor(data)
        except Exception:
            desc = None
        if desc:
            with db.connect() as conn:
                mem = conn.execute("SELECT subject FROM memories WHERE id=?",
                                   (memory_id,)).fetchone()
                label = mem["subject"] if mem else "مكان"
                conn.execute(
                    "INSERT OR REPLACE INTO scene_embeddings"
                    "(photo_id,memory_id,label,descriptor) VALUES (?,?,?,?)",
                    (info["id"], memory_id, label, json.dumps(desc)),
                )
            learned = True
    return {**info, "scene_learned": learned}


@app.get("/api/memories/{memory_id}/photos")
def list_memory_photos(memory_id: int, user: dict = Depends(auth.require_user)) -> dict:
    return {"photos": media.list_album_photos(memory_id)}


@app.get("/api/memory-photo/{photo_id}")
def get_memory_photo(photo_id: int, user: dict = Depends(auth.require_user)):
    got = media.get_album_photo(photo_id)
    if got is None:
        raise HTTPException(status_code=404, detail="no photo")
    return FileResponse(got["path"], media_type=got["mime"])


@app.delete("/api/memory-photo/{photo_id}", status_code=204)
def del_memory_photo(photo_id: int, user: dict = Depends(auth.require_role("caregiver"))) -> None:
    if not media.delete_album_photo(photo_id):
        raise HTTPException(status_code=404, detail="no photo")


@app.post("/api/memories/{memory_id}/audio", status_code=201)
async def add_memory_audio(memory_id: int, file: UploadFile = File(...),
                           user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Append a numbered voice note. Labelled «صوت رقم N» automatically."""
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="الذكرى غير موجودة")
    try:
        return media.save_audio(memory_id, await file.read())
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/memories/{memory_id}/audio")
def list_memory_audio(memory_id: int, user: dict = Depends(auth.require_user)) -> dict:
    return {"audio": media.list_audio(memory_id)}


@app.get("/api/audio/{clip_id}")
def get_audio_clip(clip_id: int, user: dict = Depends(auth.require_user)):
    got = media.get_audio(clip_id)
    if got is None:
        raise HTTPException(status_code=404, detail="no audio")
    return FileResponse(got["path"], media_type=got["mime"])


@app.delete("/api/audio/{clip_id}", status_code=204)
def del_audio_clip(clip_id: int, user: dict = Depends(auth.require_role("caregiver"))) -> None:
    if not media.delete_audio(clip_id):
        raise HTTPException(status_code=404, detail="no audio")


# ------------------------------------------------- live position feed ------

# ------------------------------------------------- websocket telemetry ------

@app.websocket("/ws/device")
async def ws_device(ws: WebSocket) -> None:
    """Live telemetry socket for a real device.

    The device connects with ?token=<device token> and streams JSON fixes:
        {"lat": 24.7, "lon": 46.6, "altitude": 612, "battery": 74}
    Each message is stored, geofenced and (if needed) alerted exactly like the
    REST endpoint. Unauthenticated sockets are closed immediately.
    """
    token = ws.query_params.get("token", "")
    dev = dev_mod.resolve_token(token)
    if dev is None or dev["simulated"]:
        await ws.close(code=1008)
        return
    await ws.accept()
    stored = 0
    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = json.loads(raw)
                lat = float(body["lat"])
                lon = float(body["lon"])
            except Exception:
                await ws.send_json({"ok": False, "error": "expected {lat, lon}"})
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                await ws.send_json({"ok": False, "error": "coordinates out of range"})
                continue

            safety.record_location(
                lat, lon, dev["id"],
                body.get("accuracy"),
                simulated=False,
                altitude_m=body.get("altitude"),
                reported_at=body.get("timestamp"),
            )
            if body.get("battery") is not None:
                with db.connect() as conn:
                    conn.execute("UPDATE devices SET battery = ? WHERE id = ?",
                                 (int(body["battery"]), dev["id"]))
            sent = safety.drain_pending_notifications(_patient_name())
            stored += 1
            await _push_fix(dev["id"])
            await ws.send_json({"ok": True, "stored": stored,
                                "notifications_sent": len(sent)})
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


# ------------------------------------- patient memory album (profile tab) --

PATIENT_MEMORY_SUBJECT = "__patient_memories__"


def _patient_memory_id() -> int:
    """A hidden anchor row that holds the patient's own photo/audio album."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM memories WHERE subject = ? AND kind = 'fact' ORDER BY id LIMIT 1",
            (PATIENT_MEMORY_SUBJECT,),
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO memories(kind,subject,fact) VALUES ('fact',?,'')",
            (PATIENT_MEMORY_SUBJECT,),
        )
        return cur.lastrowid


@app.post("/api/patient/memories/photos", status_code=201)
async def add_patient_memory_photo(file: UploadFile = File(...), category: str = Form("fact"), title: str = Form(""), description: str = Form(""), function_text: str = Form(""), related_to: str = Form(""),
                                   user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Photo for the profile's «الذكريات المهمة» section."""
    try:
        data = await file.read()
        info = media.save_album_photo(_patient_memory_id(), data)
        with db.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO media_annotations(media_type,media_id,category,title,description,related_to,function_text) VALUES ('photo',?,?,?,?,?,?)", (info["id"],category,title,description,related_to,function_text))
        # Teach the camera this exact place/object so it can remind him later
        # ("هل رأيت تلك الأريكة؟ ...").
        label = (title or description[:30] or "").strip()
        if label:
            try:
                desc = vision.scene_descriptor(data)
            except Exception:
                desc = None
            if desc:
                with db.connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO scene_embeddings"
                        "(photo_id,memory_id,label,descriptor) VALUES (?,?,?,?)",
                        (info["id"], _patient_memory_id(), label, json.dumps(desc)))
                info["scene_learned"] = True
        _auto_build_memory_graph()
        return info
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/patient/memories/photos")
def list_patient_memory_photos(user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM memories WHERE subject = ? ORDER BY id LIMIT 1",
            (PATIENT_MEMORY_SUBJECT,),
        ).fetchone()
    items = media.list_album_photos(row["id"]) if row else []
    with db.connect() as conn:
        for item in items:
            a = conn.execute("SELECT * FROM media_annotations WHERE media_type='photo' AND media_id=?", (item['id'],)).fetchone()
            if a:
                item.update(dict(a))
    labels = {"person":"شخص", "place":"مكان", "object":"شيء", "event":"حدث", "fact":"معلومة / ذكرى", "other":"ملف آخر"}
    for item in items: item['category_label'] = labels.get(item.get('category'), '')
    return {"photos": items}


@app.post("/api/patient/memories/audio", status_code=201)
async def add_patient_memory_audio(file: UploadFile = File(...), category: str = Form("fact"), title: str = Form(""), description: str = Form(""), function_text: str = Form(""), related_to: str = Form(""),
                                   user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    try:
        info = media.save_audio(_patient_memory_id(), await file.read())
        with db.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO media_annotations(media_type,media_id,category,title,description,related_to,function_text) VALUES ('audio',?,?,?,?,?,?)", (info["id"],category,title,description,related_to,function_text))
        _auto_build_memory_graph()
        return info
    except media.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/patient/memories/audio")
def list_patient_memory_audio(user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM memories WHERE subject = ? ORDER BY id LIMIT 1",
            (PATIENT_MEMORY_SUBJECT,),
        ).fetchone()
    items = media.list_audio(row["id"]) if row else []
    with db.connect() as conn:
        for item in items:
            a = conn.execute("SELECT * FROM media_annotations WHERE media_type='audio' AND media_id=?", (item['id'],)).fetchone()
            if a:
                item.update(dict(a))
    labels = {"person":"شخص", "place":"مكان", "object":"شيء", "event":"حدث", "fact":"معلومة / ذكرى", "other":"ملف آخر"}
    for item in items: item['category_label'] = labels.get(item.get('category'), '')
    return {"audio": items}


@app.get("/api/memories")
def list_memories(user: dict = Depends(auth.require_user)) -> dict:
    """Caregiver-facing list. The hidden patient-album anchor is excluded."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM memories WHERE subject != ? ORDER BY id DESC",
            (PATIENT_MEMORY_SUBJECT,),
        ).fetchall()
    return {"memories": [dict(r) for r in rows]}


# ------------------------------------------------ shareable live link -----

class ShareIn(BaseModel):
    hours: int = Field(default=24, ge=1, le=72)


@app.post("/api/share/live", status_code=201)
def create_live_link(body: ShareIn,
                     user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    """Mint a temporary public link the caregiver can send to family.

    Read-only, location only, and it expires. No account needed on the other
    side — which is the point: a daughter must be able to open a link on
    WhatsApp and see where her father is.
    """
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(hours=body.hours)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO share_links(token,created_by,expires_at) VALUES (?,?,?)",
            (token, user["id"], exp),
        )
    path = f"/live/{token}"
    public_base = tunnel.public_base(wait_seconds=15)
    public_url = f"{public_base}{path}" if public_base else None
    return {"ok": True, "token": token, "path": path, "url": public_url,
            "public": bool(public_url), "tunnel": tunnel.status(),
            "expires_at": exp, "hours": body.hours,
            "note": "أرسلي هذا الرابط للمسؤول المصرح له فقط. ينتهي تلقائيًا."}


@app.get("/api/public-url")
def public_url_status(user: dict = Depends(auth.require_user)) -> dict:
    """Is there a public https address for live links right now?"""
    tunnel.start_async()
    return tunnel.status()


@app.get("/api/share/live")
def list_live_links(user: dict = Depends(auth.require_user)) -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT token, expires_at, revoked_at, created_at FROM share_links "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = not d["revoked_at"] and d["expires_at"] > now
        out.append(d)
    return {"links": out}


@app.delete("/api/share/live/{token}", status_code=204)
def revoke_live_link(token: str,
                     user: dict = Depends(auth.require_role("caregiver"))) -> None:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE share_links SET revoked_at = datetime('now') "
            "WHERE token = ? AND revoked_at IS NULL", (token,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/live/{token}", response_class=HTMLResponse)
def public_live_page(token: str) -> HTMLResponse:
    """Public, read-only page. No login, shows only location and freshness."""
    html = (BASE / "templates" / "live.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-store, private",
                                      "Referrer-Policy": "no-referrer"})


@app.get("/api/public/live/{token}")
def public_live_data(token: str, response: Response) -> dict:
    """The only unauthenticated data endpoint. Location only, nothing else."""
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM share_links WHERE token = ?", (token,)
        ).fetchone()
    if row is None or row["revoked_at"]:
        raise HTTPException(status_code=404, detail="انتهت صلاحية الرابط")
    if row["expires_at"] <= datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=410, detail="انتهت صلاحية الرابط")

    with db.connect() as conn:
        dev = conn.execute(
            "SELECT d.id, d.name, d.simulated, MAX(l.id) AS last_id "
            "FROM devices d LEFT JOIN locations l ON l.device_id = d.id "
            "GROUP BY d.id HAVING last_id IS NOT NULL "
            "ORDER BY last_id DESC LIMIT 1"
        ).fetchone()
        if dev is None:
            dev = conn.execute(
                "SELECT id, name, simulated FROM devices "
                "ORDER BY simulated ASC, id ASC LIMIT 1"
            ).fetchone()
    if dev is None:
        return {"ok": False, "message": "لم يبدأ جوال المريض أو قلادته بمشاركة الموقع بعد. "
                                        "ستظهر الخريطة هنا تلقائيًا أول ما يصل موقعه."}

    loc = safety.latest_location(dev["id"])
    # A watch that reports only on leaving the safe zone, and says it is inside
    with db.connect() as conn:
        z = conn.execute("SELECT report_mode, zone_status, zone_checked_at FROM devices "
                         "WHERE id = ?", (dev["id"],)).fetchone()
    if z and z["report_mode"] == "on_exit" and (z["zone_status"] or "").startswith("inside") \
            and z["zone_checked_at"]:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(
            z["zone_checked_at"].replace(" ", "T")).replace(tzinfo=timezone.utc)).total_seconds()
        # a location newer than the last «inside» heartbeat wins (he left)
        fresh_fix = loc is not None and loc.get("is_fresh") and \
            (loc.get("age_seconds") or 0) + 2 < age
        if age <= 35 * 60 and not fresh_fix:
            zone = (z["zone_status"].split(":", 1) + [""])[1] or "النطاق الآمن"
            return {"ok": True, "state": "inside_zone", "location": None,
                    "zone": zone, "checked_minutes": int(age // 60),
                    "message": f"المريض داخل {zone} — آخر تأكيد قبل {int(age // 60)} دقيقة. "
                               "يظهر موقعه هنا تلقائيًا إذا خرج من النطاق الآمن.",
                    "expires_at": row["expires_at"]}
    if loc is None:
        return {"ok": True, "state": "no_fix",
                "message": "لا يوجد موقع مسجّل بعد", "location": None}

    return {
        "ok": True,
        "state": "live" if loc["is_fresh"] else "last_known",
        "location": {
            "lat": loc["lat"], "lon": loc["lon"],
            "reported_at": loc["reported_at"],
            "freshness_note": loc["freshness_note"],
            "is_fresh": loc["is_fresh"],
            "age_seconds": loc["age_seconds"],
            "simulated": bool(loc.get("simulated", False)),
            "map_link": notify.map_link(loc["lat"], loc["lon"]),
        },
        "expires_at": row["expires_at"],
    }


# ------------------------------------------- phone-only alert contacts -----

class ContactIn(BaseModel):
    name: str = Field(default="", max_length=80)
    phone: str = Field(min_length=5, max_length=30)
    channel: str = Field(default="sms", pattern="^(sms|whatsapp_link)$")


@app.get("/api/alert-contacts")
def get_contacts(user: dict = Depends(auth.require_user)) -> dict:
    """Caregivers alerted by phone number only — no token, no business account."""
    return {"contacts": alerts.list_contacts(), **alerts.status()}


@app.post("/api/alert-contacts", status_code=201)
def new_contact(c: ContactIn,
                user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    try:
        return alerts.add_contact(c.name, c.phone, c.channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/alert-contacts/{contact_id}", status_code=204)
def del_contact(contact_id: int,
                user: dict = Depends(auth.require_role("caregiver"))) -> None:
    if not alerts.remove_contact(contact_id):
        raise HTTPException(status_code=404, detail="not found")


@app.get("/api/alerts/{alert_id}/share")
def share_alert(alert_id: int, user: dict = Depends(auth.require_user)) -> dict:
    """Ready-made SMS / WhatsApp links for this alert. Nothing is sent here."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    a = dict(row)
    name = _patient_name()
    msg = notify.compose(a["kind"], name, a["lat"], a["lon"],
                         a["created_at"], extra=a["message"])
    return {"text": msg["text"], "links": alerts.build_links(msg["text"])}


# ------------------------------------------------------------ code viewer --

VIEWABLE = [
    "app/main.py", "app/agent.py", "app/safety.py", "app/notify.py",
    "app/db.py", "app/media.py", "app/vision.py", "app/network.py",
    "app/devices.py", "app/auth.py", "app/secrets.py", "app/bot.py",
    "app/alerts.py", "app/fetch_models.py",
    "app/templates/patient.html", "app/templates/camera.html",
    "app/templates/safety.html", "app/templates/profile.html",
    "app/templates/settings.html", "app/templates/network.html",
    "app/templates/live.html",
    "app/static/shell.js", "app/static/style.css",
    "tests/test_echeos.py",
    "run.py", "requirements.txt", "README.md", "START_HERE.md",
]

PROJECT_ROOT = BASE.parent


@app.get("/code", response_class=HTMLResponse)
def code_page() -> str:
    """Read-only source browser, so the whole project can be inspected."""
    return (BASE / "templates" / "code.html").read_text(encoding="utf-8")


@app.get("/api/code/files")
def code_files(user: dict = Depends(auth.require_user)) -> dict:
    out = []
    for rel in VIEWABLE:
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        out.append({
            "path": rel,
            "lines": path.read_text(encoding="utf-8", errors="replace").count("\n") + 1,
            "bytes": path.stat().st_size,
        })
    return {"files": out, "root": str(PROJECT_ROOT)}


@app.get("/api/code/file")
def code_file(path: str, user: dict = Depends(auth.require_user)) -> dict:
    """Return one file's text.

    Only files on the allow-list can be read — a path outside it is refused,
    so this endpoint cannot be used to wander the filesystem.
    """
    if path not in VIEWABLE:
        raise HTTPException(status_code=403, detail="هذا الملف غير متاح للعرض")
    full = PROJECT_ROOT / path
    if not full.exists():
        raise HTTPException(status_code=404, detail="not found")
    text = full.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "text": text, "lines": text.count("\n") + 1,
            "bytes": len(text.encode())}


# ------------------------------------------------ extended profile fields --

def _ensure_extra() -> None:
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO patient_profile_extra(patient_id) VALUES (1)")


@app.get("/api/patient/extra")
def get_patient_extra(user: dict = Depends(auth.require_user)) -> dict:
    _ensure_extra()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM patient_profile_extra WHERE patient_id = 1"
        ).fetchone()
    return dict(row)


@app.put("/api/patient/extra")
def set_patient_extra(body: PatientExtraIn,
                      user: dict = Depends(auth.require_role("caregiver"))) -> dict:
    _ensure_extra()
    data = body.model_dump()
    cols = list(data.keys())
    sets = ", ".join(f"{c} = ?" for c in cols)
    vals = [data[c] for c in cols]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE patient_profile_extra SET {sets}, updated_at = datetime('now') "
            "WHERE patient_id = 1", vals)
        row = conn.execute(
            "SELECT * FROM patient_profile_extra WHERE patient_id = 1").fetchone()
    return dict(row)


@app.get("/api/patient/completion")
def patient_completion(user: dict = Depends(auth.require_user)) -> dict:
    """How complete is the profile? Lists exactly what is still missing."""
    _ensure_patient()
    _ensure_extra()
    with db.connect() as conn:
        p = dict(conn.execute("SELECT * FROM patient_profile WHERE id = 1").fetchone())
        e = dict(conn.execute(
            "SELECT * FROM patient_profile_extra WHERE patient_id = 1").fetchone())

    merged = {**p, **e}
    missing = []
    for f in COMPLETION_REQUIRED:
        v = merged.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(f)
    total = len(COMPLETION_REQUIRED)
    done = total - len(missing)
    return {
        "percent": round(done * 100 / total),
        "done": done,
        "total": total,
        "missing": missing,
        "missing_labels": [_FIELD_LABEL.get(f, f) for f in missing],
    }


_FIELD_LABEL = {
    "full_name": "الاسم الكامل",
    "age": "العمر",
    "home_address": "عنوان المنزل",
    "medical_info": "المعلومات الطبية",
    "emergency_notes": "ملاحظات الطوارئ",
    "routine": "الروتين اليومي",
    "nickname": "الاسم المفضل",
    "date_of_birth": "تاريخ الميلاد",
    "occupation": "المهنة السابقة",
    "hobbies": "الهوايات",
    "favourite_foods": "الأطعمة المفضلة",
    "medications": "الأدوية الحالية",
    "comfort_items": "ما يريحه",
    "confusion_triggers": "ما يسبب له الارتباك",
}
