"""Optional AI + internet helpers for the companion and the memory network.

Two layers, so the app never breaks when one is missing:

1. **Claude (Anthropic API)** — used only when the caregiver pastes an API key
   in Settings. It phrases reminders warmly, looks at camera frames (objects,
   whether the patient is touching / eating something, dangerous actions),
   proposes links between memories, and answers general questions with web
   search. Every prompt tells it to use ONLY the facts we pass in, so it
   cannot invent a son, a house, or an event.

2. **Wikipedia (no key)** — free fallback for "information from the internet"
   about a place, a hobby, or a general question.

Nothing personal is sent to Wikipedia: only the name of a place / topic.
"""

from __future__ import annotations

import base64
import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

from . import secrets as secrets_mod
from .db import connect

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
UA = "ECHOES-memory-companion/1.0 (Alzheimer care prototype)"

_last_vision = 0.0
_vision_lock = threading.Lock()


# ------------------------------------------------------------- settings ----

def _rows() -> dict:
    with connect() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT * FROM assistant_settings")}


def settings() -> dict:
    s = _rows()
    key = s.get("ai_key", "")
    if key:
        try:
            key = secrets_mod.decrypt(key)
        except Exception:
            key = ""
    return {
        "key": key,
        "model": s.get("ai_model") or DEFAULT_MODEL,
        "web": s.get("ai_web", "1") == "1",
        "vision": s.get("ai_vision", "1") == "1",
        "interval": float(s.get("ai_interval", "6") or 6),
        "reply_delay": int(s.get("reply_delay", "13") or 13),
    }


def configured() -> bool:
    return bool(settings()["key"])


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


# ---------------------------------------------------------------- Claude ---

def _call(system: str, content, max_tokens: int = 400, tools=None,
          timeout: int = 25) -> str | None:
    s = settings()
    if not s["key"]:
        return None
    body = {
        "model": s["model"],
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"content-type": "application/json", "x-api-key": s["key"],
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or None


def _json(text: str | None):
    if not text:
        return None
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


GROUNDING = (
    "You are ECHOES, a gentle memory companion worn by an Alzheimer's patient. "
    "Speak Arabic (Saudi-friendly, simple, warm, short). NEVER invent people, "
    "places, relations or events: use only the facts given. If the facts are "
    "not enough, answer with exactly: NONE"
)


def phrase_reminder(thing: str, facts: list[str], mode: str = "seen") -> str | None:
    """One warm spoken line: 'هل رأيت تلك الأريكة؟ اعتدت أن تجلس هناك مع أطفالك'."""
    if not facts:
        return None
    situation = {
        "seen": f"The patient is right next to / holding: {thing}.",
        "place": f"The patient is at, or looking at, the place: {thing}.",
        "person": f"This person is near the patient (within a few metres): {thing}.",
        "heard": f"Someone near the patient just mentioned: {thing}.",
    }.get(mode, f"Context: {thing}.")
    rule = ("Do NOT name, describe or point at the object itself (he can see it)."
            if mode == "seen" else "You may say the name once, then the memory.")
    prompt = (f"{situation}\nFacts written by the family:\n- "
              + "\n- ".join(facts[:3])
              + "\n\nWrite ONE short sentence (max 14 words), to the patient in "
                f"second person, recalling the memory. {rule} Return only the sentence.")
    out = _call(GROUNDING, prompt, max_tokens=150, timeout=12)
    if not out or "NONE" in out:
        return None
    return brief(out.strip().strip('"'), 16)


def vision_scan(image_bytes: bytes, memory_items: list[str], allergy: list[str],
                danger: list[str], force: bool = False) -> dict | None:
    """Ask the vision model what is in front of the wearer. Throttled."""
    global _last_vision
    s = settings()
    if not s["key"] or not s["vision"]:
        return None
    with _vision_lock:
        now = time.time()
        if not force and now - _last_vision < s["interval"]:
            return None
        _last_vision = now
    b64 = base64.b64encode(image_bytes).decode("ascii")
    instr = (
        "This frame comes from a camera worn on the chest of an Alzheimer's patient "
        "(the wearer). Estimate each distance from the wearer in metres. JSON only:\n"
        '{"objects":[{"name_ar":"...","distance_m":0.6,"touching":true|false,"eating":true|false}],'
        '"place":{"name_ar":"the room / building / landmark he is in or looking at, or null",'
        '"kind":"room|building|outdoor|landmark|null"},'
        '"memory_matches":[{"item":"exact item from MEMORY list that is clearly visible",'
        '"distance_m":1.0}],'
        '"allergen_contact":["item from ALLERGY list the wearer is touching/eating"],'
        '"danger":["short Arabic description of a dangerous thing the wearer is doing '
        'or about to do, e.g. يلمس الفرن وهو مشتعل / يمسك سكين / يتناول دواء"]}\n'
        f"MEMORY: {memory_items[:40]}\nALLERGY: {allergy[:30]}\nDANGER LIST: {danger[:30]}\n"
        "Only report what is clearly visible, nearest first, at most 6 objects. "
        "Empty lists / null if nothing."
    )
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": instr},
    ]
    return _json(_call("You are a careful visual safety assistant. JSON only.",
                       content, max_tokens=500, timeout=20))


def suggest_links(nodes: list[dict], facts: list[str]) -> list[dict]:
    """Detective-style link proposals between EXISTING node labels."""
    if not nodes:
        return []
    labels = [f"{n['kind']}:{n['label']}" for n in nodes[:80]]
    prompt = (
        "You help a family build an investigator-style evidence board of an "
        "Alzheimer patient's memories (people, places, events, objects).\n"
        f"NODES: {labels}\nFACTS:\n- " + "\n- ".join(facts[:60]) +
        '\n\nPropose links ONLY between the given node labels, ONLY if a fact '
        'supports it. JSON only: [{"a":"label","b":"label","relation":"Arabic '
        'verb, e.g. زار / عاش في / حدث في / يملك / مع","reason":"the supporting '
        'fact, Arabic"}]. Max 25.')
    data = _json(_call("You are a meticulous investigator. Never invent.", prompt,
                       max_tokens=1500, timeout=40))
    return data if isinstance(data, list) else []


def web_answer(question: str) -> str | None:
    """General-knowledge answer with live web search (Claude), short and spoken."""
    s = settings()
    if not s["key"] or not s["web"]:
        return None
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}]
    out = _call(
        "Answer in simple Arabic, ONE short spoken sentence (max 15 words), for an "
        "elderly person. If it asks about private details of a non-public person, "
        "answer exactly: NONE",
        question, max_tokens=300, tools=tools, timeout=30)
    if not out or "NONE" in out:
        return None
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------- Wikipedia ---

def _get(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return json.loads(r.read().decode("utf-8"))


def wiki_summary(term: str, lang: str = "ar") -> dict | None:
    """{"title","extract","url"} for the best Wikipedia match, or None."""
    term = (term or "").strip()
    if len(term) < 2:
        return None
    try:
        q = urllib.parse.urlencode({"action": "query", "list": "search",
                                    "srsearch": term, "format": "json",
                                    "srlimit": 1, "utf8": 1})
        res = _get(f"https://{lang}.wikipedia.org/w/api.php?{q}")
        hits = res.get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        summ = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(title.replace(" ", "_")))
        extract = (summ.get("extract") or "").strip()
        if not extract:
            return None
        sentences = re.split(r"(?<=[.!؟])\s+", extract)
        return {"title": title, "extract": " ".join(sentences[:2])[:400],
                "url": summ.get("content_urls", {}).get("desktop", {}).get("page", "")}
    except Exception:
        return None


def brief(text: str | None, max_words: int = 18) -> str | None:
    """One short spoken sentence. Elderly listeners lose long answers."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text)).strip()
    t = re.split(r"(?<=[.!؟?])\s+", t)[0]
    w = t.split()
    if len(w) > max_words:
        t = " ".join(w[:max_words]).rstrip("،,؛") + "."
    return t or None


EYES = (
    "You are the eyes of an Alzheimer's patient: the image comes from a camera "
    "worn on his chest, so his own hands appear at the bottom of the frame. "
    "Answer the question about what is actually visible. Rules: Saudi Arabic, "
    "ONE very short sentence (max 10 words), no introductions, no explanations, "
    "never describe things that were not asked about. Count carefully when asked "
    "to count. If it is not clearly visible, say exactly: ما أقدر أشوفه بوضوح."
)


def look_and_answer(question: str, image_bytes: bytes, facts: list[str] | None = None) -> str | None:
    """Answer 'what is this / how many fingers / what colour' from the frame."""
    if not configured():
        return None
    b64 = base64.b64encode(image_bytes).decode("ascii")
    txt = f"السؤال: {question}"
    if facts:
        txt += ("\nمعلومات من العائلة (استعملها فقط إذا الشيء الظاهر هو نفسه):\n- "
                + "\n- ".join(facts[:5]))
    out = _call(EYES, [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": txt}], max_tokens=80, timeout=15)
    return brief(out, 14)


SMART = (
    "You are ECHOES, a calm companion worn by an Alzheimer's patient. Reply in "
    "simple Saudi Arabic with ONE short sentence (max 15 words), no greeting, no "
    "lecture, no lists. Questions about the patient's own life, family, home or "
    "past: answer ONLY from FAMILY FACTS; if the facts do not contain the answer, "
    "reply exactly NONE. General knowledge (prayer, dates, simple facts): answer "
    "correctly and briefly. Never invent. Never mention medicine, money, addresses "
    "or phone numbers."
)


def smart_answer(question: str, facts: list[str], seen: list[str] | None = None) -> str | None:
    """Grounded, brief answer using Claude (with web search for current facts)."""
    s = settings()
    if not s["key"]:
        return None
    ctx = f"QUESTION: {question}\nFAMILY FACTS:\n- " + ("\n- ".join(facts[:12]) or "(none)")
    if seen:
        ctx += f"\nCURRENTLY IN FRONT OF HIM (camera): {', '.join(seen[:8])}"
    tools = ([{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
             if s["web"] else None)
    out = _call(SMART, ctx, max_tokens=200, tools=tools, timeout=25)
    if not out or "NONE" in out:
        return None
    return brief(out, 18)


_DEFINE = re.compile(r"^(?:وش|ايش|إيش|شو|ما|من|مين|منو)\s+(?:هو|هي|هوا|يكون|تكون|معنى|يعني)?\s*(.{2,40}?)[؟?]?$")


def internet_answer(question: str) -> tuple[str | None, str]:
    """Internet answer only when it can be short and on-topic.

    With a Claude key: live web search. Without it: Wikipedia, but only for a
    clear "what/who is X" question whose article title really is X — otherwise
    silence is better than a random article.
    """
    a = web_answer(question)
    if a:
        return brief(a, 18), "ai_web"
    if not settings()["web"]:
        return None, ""
    m = _DEFINE.match(question.strip())
    if not m:
        return None, ""
    topic = m.group(1).strip()
    w = wiki_summary(topic)
    if not w:
        return None, ""
    def _n(x):
        x = re.sub("[أإآ]", "ا", x).replace("ة", "ه").replace("ى", "ي")
        return re.sub(r"^ال", "", x.strip())
    if _n(topic) not in _n(w["title"]) and _n(w["title"]) not in _n(topic):
        return None, ""
    return brief(w["extract"], 18), "wikipedia"
