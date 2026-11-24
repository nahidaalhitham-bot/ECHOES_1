"""Investigator board: turn the profile into a people–places–events web.

Works like the string board detectives use: every card is a person, place,
event or object, and every red string is backed by evidence — the sentence
the family wrote that mentions both ends. On top of that:

  - conversations heard by the assistant become "conversation" cards that are
    pinned to whatever they mentioned;
  - places / hobbies / events get an "internet" card (Wikipedia, or Claude web
    search when configured) — never for family members' names;
  - when an AI key is configured, Claude proposes extra strings, each with the
    fact that justifies it, shown dashed so the family can review them.
"""

from __future__ import annotations

from . import ai, network, objects
from .companion import (PATIENT_MEMORY_SUBJECT, corpus, mentions, norm, sentences,
                        split_items)
from .db import connect

FIELD_RELATION = {
    "favourite_places": ("place", "يحب المكان"),
    "birthplace": ("place", "وُلد في"),
    "hobbies": ("event", "هوايته"),
    "favourite_activities": ("event", "يحب"),
    "occupation": ("fact", "عمل"),
    "life_events": ("event", "عاش"),
    "childhood": ("event", "من طفولته"),
    "comfort_items": ("object", "يرتاح مع"),
    "favourite_foods": ("object", "يحب أكل"),
    "favourite_drinks": ("object", "يحب شرب"),
    "favourite_music": ("fact", "يحب سماع"),
}

PAIR_RELATION = {
    ("person", "place"): "في / زار", ("person", "event"): "شارك في",
    ("place", "event"): "حدث في", ("person", "object"): "مرتبط بـ",
    ("person", "person"): "مع", ("place", "object"): "موجود في",
    ("event", "object"): "مرتبط بـ",
}


def _short(s: str, words: int = 5) -> str:
    w = s.split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def _patient_node() -> int:
    with connect() as conn:
        p = conn.execute("SELECT full_name FROM patient_profile WHERE id=1").fetchone()
    name = (p["full_name"] if p and p["full_name"] else "").strip() or "المريض"
    return network.upsert_node("person", name, "صاحب الذكريات", source="evidence")


def run(use_web: bool = True, use_ai: bool = True, web_limit: int = 8) -> dict:
    stats = {"entities": 0, "evidence_links": 0, "conversation_links": 0,
             "web_cards": 0, "ai_links": 0}
    me = _patient_node()
    entities: dict[int, tuple[str, str]] = {}   # node_id -> (kind, label)

    def ent(kind: str, label: str, detail: str = "") -> int | None:
        label = (label or "").strip(" .،,")
        if len(label) < 2 or len(label) > 60 or label == PATIENT_MEMORY_SUBJECT:
            return None
        nid = network.upsert_node(kind, label, detail or None, source="evidence")
        entities[nid] = (kind, label)
        return nid

    with connect() as conn:
        p = conn.execute("SELECT * FROM patient_profile WHERE id=1").fetchone()
        e = conn.execute("SELECT * FROM patient_profile_extra WHERE patient_id=1").fetchone()
        people = conn.execute("SELECT * FROM people").fetchall()
        mems = conn.execute("SELECT * FROM memories WHERE subject != ?",
                            (PATIENT_MEMORY_SUBJECT,)).fetchall()
        assets = conn.execute("SELECT * FROM media_annotations").fetchall()
        places = conn.execute("SELECT * FROM places").fetchall()
    p = dict(p) if p else {}
    e = dict(e) if e else {}

    # 1) cards -------------------------------------------------------------
    family_ids = set()
    for pe in people:
        nid = ent("person", pe["name"], pe["relation"] or "")
        if nid:
            family_ids.add(nid)
            if network.link(me, pe["relation"] or "من أهله", nid,
                            "مسجّل في قائمة الأشخاص المهمين", source="evidence"):
                stats["evidence_links"] += 1
    for pl in places:
        ent("place", pl["name"], pl["description"])
    for m in mems:
        kind = m["kind"] if m["kind"] in ("person", "place", "event", "object") else None
        if kind:
            ent(kind, m["subject"], m["fact"])
    for a in assets:
        if a["category"] in ("person", "place", "event", "object") and a["title"]:
            ent(a["category"], a["title"], a["description"] or "")

    for field, (kind, rel) in FIELD_RELATION.items():
        raw = e.get(field) or ""
        items = sentences(raw) if field in ("life_events", "childhood") else split_items(raw)
        for it in items:
            label = _short(it) if kind == "event" else it
            nid = ent(kind, label, it)
            if nid and network.link(me, rel, nid, f"من الملف: {it}", source="evidence"):
                stats["evidence_links"] += 1

    # everyday objects named in memories (sofa, cup, car…) become cards too,
    # so the camera can reach them
    rows = corpus()
    for row in rows:
        for en, names in objects.ARABIC.items():
            if en == "person":
                continue
            for n in names:
                if mentions(row["text"], [n]):
                    # skip if a richer card already covers it
                    # («الكنبة الخضراء في الصالة» already covers «كنبة»)
                    if not any(mentions(lab, [n]) for _, lab in entities.values()):
                        ent("object", n, row["text"])
                    break

    stats["entities"] = len(entities)

    # 2) evidence strings: two cards mentioned in the same sentence -----------
    labels = list(entities.items())
    for row in rows:
        found = [(nid, k, lab) for nid, (k, lab) in labels
                 if mentions(row["text"], [lab]) or row.get("subject") == lab]
        for i in range(len(found)):
            for j in range(i + 1, len(found)):
                a, b = found[i], found[j]
                if a[0] == b[0]:
                    continue
                rel = PAIR_RELATION.get((a[1], b[1])) or PAIR_RELATION.get((b[1], a[1])) \
                    or "مرتبط بـ"
                src, dst = (a, b) if (a[1], b[1]) in PAIR_RELATION else (b, a)
                if network.link(src[0], rel, dst[0], f"دليل: {row['text']}", source="evidence"):
                    stats["evidence_links"] += 1
        # the patient is implicitly in every profile sentence
        if row["source"].startswith(("profile:", "extra:")):
            for nid, k, lab in found:
                if network.link(me, "يتذكر", nid, f"دليل: {row['text']}", source="evidence"):
                    stats["evidence_links"] += 1

    # 3) conversations the assistant heard ---------------------------------
    with connect() as conn:
        chats = conn.execute(
            "SELECT id, content, date(created_at) AS d FROM chat_log "
            "WHERE role='user' ORDER BY id DESC LIMIT 300").fetchall()
    for c in chats:
        hit = [(nid, lab) for nid, (k, lab) in labels if mentions(c["content"], [lab])]
        if not hit:
            continue
        conv = network.upsert_node("event", f"محادثة {c['d']}", _short(c["content"], 12),
                                   source="conversation")
        for nid, lab in hit:
            if network.link(conv, "ذُكر في المحادثة", nid, f"«{c['content'][:120]}»",
                            source="conversation"):
                stats["conversation_links"] += 1

    # 4) internet cards (places / hobbies / events / objects — not family) ---
    if use_web and ai.settings()["web"]:
        with connect() as conn:
            have_web = {r["dst_id"] for r in conn.execute(
                "SELECT dst_id FROM edges WHERE source='web'")} | {r["src_id"] for r in conn.execute(
                "SELECT src_id FROM edges WHERE source='web'")}
        done = 0
        for nid, (kind, lab) in labels:
            if done >= web_limit:
                break
            if kind not in ("place", "event", "fact") or nid in family_ids or nid in have_web:
                continue
            if kind == "event" and len(lab.split()) > 3:
                continue
            w = ai.wiki_summary(lab.rstrip("…"))
            done += 1
            if not w:
                continue
            detail = w["extract"] + (f"\n{w['url']}" if w.get("url") else "")
            wid = network.upsert_node("web", f"🌐 {w['title']}", detail, source="web")
            if network.link(nid, "معلومة من الإنترنت", wid, w.get("url") or "ويكيبيديا",
                            source="web"):
                stats["web_cards"] += 1

    # 5) AI-proposed strings ----------------------------------------------
    if use_ai and ai.configured():
        with connect() as conn:
            nodes = [dict(r) for r in conn.execute(
                "SELECT id, kind, label FROM nodes WHERE kind != 'web'")]
        by_label = {norm(n["label"]): n["id"] for n in nodes}
        facts = [r["text"] for r in rows][:60]
        for s in ai.suggest_links(nodes, facts):
            a = by_label.get(norm(str(s.get("a", "")).split(":", 1)[-1]))
            b = by_label.get(norm(str(s.get("b", "")).split(":", 1)[-1]))
            if a and b and a != b:
                if network.link(a, str(s.get("relation") or "مرتبط بـ")[:40], b,
                                f"اقتراح الذكاء الاصطناعي: {s.get('reason', '')}"[:300],
                                source="ai"):
                    stats["ai_links"] += 1
    stats["ai_enabled"] = ai.configured()
    return stats
