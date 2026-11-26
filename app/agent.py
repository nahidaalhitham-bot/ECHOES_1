"""Retrieval + response generation.

The single most important rule in this module: the advisor answers ONLY from
rows that exist in the database. If nothing matches, it says it does not know.
There is no language model call here, so it cannot invent a name, a relation,
or a place. That is a deliberate design choice, not a missing feature.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import connect

I_DONT_KNOW = "ما عندي هالمعلومة. ما أبي أخمّن عليك."

# Arabic question scaffolding removed before matching a stored subject.
_STOPWORDS = {
    "من", "هذا", "هذه", "هو", "هي", "ما", "ماذا", "ايش", "وش", "منو", "اللي",
    "اسم", "أسماء", "ابنتي", "ابني", "حفيدي", "زوجي", "زوجتي", "امي", "أمي",
    "ابوي", "أبوي", "اين", "أين", "وين", "اعيش", "أعيش", "افعل", "أفعل",
    "اليوم", "سيزورني", "يزورني", "تعرف", "تعرفين", "تقول", "لي", "عن", "في",
    "هل", "و", "؟", "?", "!", ".", "،", "مين",
}

# The assistant is the patient's companion, not a locator. These are questions
# a stranger could ask a found device; none of them may reveal a position.
# Only *live whereabouts* questions are blocked. "أين أعيش؟" (where do I live)
# is a stored memory the patient is entitled to ask for; "وين هو الحين؟" is
# a tracking request that could be asked by a stranger holding the device.
_LOCATION_PROBES = (
    "مكانه", "مكانها", "موقعك", "موقع الحين", "الموقع الحالي", "موقع المريض",
    "خريطة", "coordinates", "gps", "live location", "where is he",
    "where is she", "where is the patient", "أين هو الآن", "وين هو الآن",
    "وينه الحين", "أين المريض", "وين المريض",
    "وين هو", "أين هو", "where is", "مكان أحمد", "مكان أبوي", "مكان ابوي",
)

_LOCATION_DEFLECTION = (
    "ما أقدر أعطيك معلومة عن الموقع. "
    "لو تحتاج تعرف مكان أحد، تواصل مع الأسرة مباشرة."
)

_PERSON_TRIGGERS = ("ابن", "ابنت", "حفيد", "زوج", "أخ", "اخ", "أخت", "اخت", "ام", "أم", "اب", "أب", "قريب")


@dataclass
class Answer:
    text: str
    basis: list[str]         # provenance, e.g. "people:1", "memories:3"
    kind: str                # answered | refused

    @property
    def refused(self) -> bool:
        return self.kind == "refused"


def _tokens(text: str) -> list[str]:
    text = text.strip()
    for ch in "؟?!.،,":
        text = text.replace(ch, " ")
    parts = re.split(r"\s+", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # strip leading "ال" so "الاسم" matches "اسم"
        bare = p[2:] if p.startswith("ال") and len(p) > 3 else p
        if bare and bare not in _STOPWORDS and p not in _STOPWORDS:
            out.append(bare)
    return out


def _all_subjects() -> list[str]:
    with connect() as conn:
        people = [r["name"] for r in conn.execute("SELECT name FROM people")]
        mems = [r["subject"] for r in conn.execute("SELECT DISTINCT subject FROM memories")]
    seen, out = set(), []
    for s in people + mems:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


_WHERE_WORDS = ("وين", "أين", "اين", "where")
# "أين أعيش" / "where do I live" are stored memories, not tracking requests.
_SELF_PLACE = ("أعيش", "اعيش", "أسكن", "اسكن", "بيتي", "do i live", "home")


def _is_location_probe(q: str) -> bool:
    """True when the question asks where someone is *right now*.

    The assistant cannot verify who is speaking, so live whereabouts are never
    disclosed. Questions about the patient's own remembered home are not
    tracking requests and are allowed through.
    """
    if any(p in q for p in _LOCATION_PROBES):
        return True
    if not any(w in q for w in _WHERE_WORDS):
        return False
    # A "where" question that is not the patient asking about his own home
    # is treated as a whereabouts probe.
    if any(sp in q for sp in _SELF_PLACE):
        return False
    return True


# Questions about the patient themselves. These read the profile, which the
# caregiver filled in — never an assumption.
_SELF_QUESTIONS = {
    "name": ("اسمي", "وش اسمي", "ما اسمي", "مين أنا", "مين انا", "my name"),
    "family": ("عيالي", "أولادي", "اولادي", "عائلتي", "أهلي", "اهلي", "my children"),
    "routine": ("وش أسوي", "وش اسوي", "ماذا أفعل", "ماذا افعل", "وش أعمل",
                "وش اسوي الحين", "my routine"),
    "age": ("كم عمري", "عمري كم", "كم سنة عمري", "my age", "how old am i"),
    "birth": ("متى ولدت", "تاريخ ميلادي", "وين ولدت", "birthday"),
    "occupation": ("وش كنت أشتغل", "وش كانت شغلتي", "مهنتي", "وظيفتي",
                   "my job", "my occupation"),
    "hobbies": ("هواياتي", "وش أحب أسوي", "وش احب اسوي", "my hobbies"),
    "foods": ("وش أحب آكل", "وش احب اكل", "أكلي المفضل", "الاكل المفضل"),
    "drinks": ("وش أحب أشرب", "وش احب اشرب", "شرابي المفضل"),
    "places": ("أماكني المفضلة", "الاماكن المفضلة", "وين أحب أروح"),
}

_SELF_NO_INFO = {
    "age": "ما عندي عمرك مسجَّل. خلّ أهلك يضيفونه لي.",
    "birth": "ما عندي تاريخ ميلادك مسجَّل.",
    "occupation": "ما عندي معلومات عن مهنتك. خلّ أهلك يضيفونها لي.",
    "hobbies": "ما عندي هواياتك مسجّلة. خلّ أهلك يضيفونها لي.",
    "foods": "ما عندي أطعمتك المفضلة مسجّلة.",
    "drinks": "ما عندي شرابك المفضل مسجّل.",
    "places": "ما عندي أماكنك المفضلة مسجّلة.",
    "name": "ما عندي اسمك مسجَّل. خلّ أهلك يضيفونه لي.",
    "family": "ما عندي معلومات عن عيالك مسجّلة. خلّ أهلك يضيفونها لي.",
    "routine": "ما عندي روتينك اليومي مسجَّل. خلّ أهلك يضيفونه لي.",
}


def _patient_row():
    with connect() as conn:
        try:
            return conn.execute("SELECT * FROM patient_profile WHERE id = 1").fetchone()
        except Exception:
            return None


def _extra_row():
    with connect() as conn:
        try:
            return conn.execute(
                "SELECT * FROM patient_profile_extra WHERE patient_id = 1").fetchone()
        except Exception:
            return None


def _answer_about_self(q: str) -> Answer | None:
    """Name / family / routine answers drawn from the caregiver-filled profile."""
    ql = q.lower()
    for kind, probes in _SELF_QUESTIONS.items():
        if not any(p in ql for p in probes):
            continue
        row = _patient_row()
        extra = _extra_row()

        def x(field: str):
            if extra is None:
                return ""
            try:
                return (extra[field] or "").strip()
            except (KeyError, IndexError):
                return ""

        if kind == "family":
            # Family comes from the people table, not the profile row, so it
            # works even before the profile has been filled in.
            with connect() as conn:
                people = conn.execute(
                    "SELECT name, relation FROM people ORDER BY id LIMIT 6"
                ).fetchall()
            if not people:
                return Answer(_SELF_NO_INFO["family"], [], "refused")
            parts = [f"{p['name']} {p['relation']}".strip() for p in people]
            return Answer("أهلك: " + "، ".join(parts) + ".",
                          [f"people:{p['name']}" for p in people], "answered")

        # Branches that read from the extra table must not be blocked by a
        # missing base patient row; each branch decides for itself.
        if kind == "name":
            name = ((row["full_name"] if row is not None else "") or "").strip()
            if not name:
                return Answer(_SELF_NO_INFO["name"], [], "refused")
            return Answer(f"اسمك {name}.", ["patient_profile:name"], "answered")
        if kind == "age":
            age = row["age"] if row is not None else None
            if not age:
                return Answer(_SELF_NO_INFO["age"], [], "refused")
            return Answer(f"عمرك {age} سنة.", ["patient_profile:age"], "answered")
        if kind == "birth":
            dob, pob = x("date_of_birth"), x("birthplace")
            parts = []
            if dob:
                parts.append(f"تاريخ ميلادك {dob}")
            if pob:
                parts.append(f"ولدت في {pob}")
            if not parts:
                return Answer(_SELF_NO_INFO["birth"], [], "refused")
            return Answer("، ".join(parts) + ".", ["patient_profile_extra:birth"], "answered")
        if kind == "occupation":
            occ = x("occupation")
            if not occ:
                return Answer(_SELF_NO_INFO["occupation"], [], "refused")
            return Answer(f"كنت تعمل {occ}.", ["patient_profile_extra:occupation"], "answered")
        if kind == "hobbies":
            h = x("hobbies") or x("favourite_activities")
            if not h:
                return Answer(_SELF_NO_INFO["hobbies"], [], "refused")
            return Answer(f"هواياتك: {h}", ["patient_profile_extra:hobbies"], "answered")
        if kind == "foods":
            f = x("favourite_foods")
            if not f:
                return Answer(_SELF_NO_INFO["foods"], [], "refused")
            return Answer(f"أطعمتك المفضلة: {f}", ["patient_profile_extra:foods"], "answered")
        if kind == "drinks":
            d = x("favourite_drinks")
            if not d:
                return Answer(_SELF_NO_INFO["drinks"], [], "refused")
            return Answer(f"شرابك المفضل: {d}", ["patient_profile_extra:drinks"], "answered")
        if kind == "places":
            pl = x("favourite_places")
            if not pl:
                return Answer(_SELF_NO_INFO["places"], [], "refused")
            return Answer(f"أماكنك المفضلة: {pl}", ["patient_profile_extra:places"], "answered")

        if kind == "routine":
            routine = ((row["routine"] if row is not None else "") or "").strip()
            if not routine:
                return Answer(_SELF_NO_INFO["routine"], [], "refused")
            return Answer(f"روتينك: {routine}", ["patient_profile:routine"], "answered")
    return None


def answer(question: str) -> Answer:
    """Return an answer grounded in stored rows, or an explicit refusal.

    Location questions are refused unconditionally: the assistant cannot verify
    who is speaking, so it must never disclose where the patient is. This is a
    hard privacy rule, not a retrieval decision.
    """
    q = question.strip()
    if not q:
        return Answer(I_DONT_KNOW, [], "refused")

    ql = q.lower()
    if _is_location_probe(ql):
        return Answer(_LOCATION_DEFLECTION, [], "refused")

    # Questions about the patient themselves come from the profile.
    about_self = _answer_about_self(q)
    if about_self is not None:
        return about_self

    toks = _tokens(q)
    subjects = _all_subjects()

    # 1) Does the question mention a person/place we actually know?
    hit_subject = None
    for subj in subjects:
        if subj in q or subj in toks:
            hit_subject = subj
            break

    if hit_subject:
        with connect() as conn:
            person = conn.execute(
                "SELECT id, name, relation, preferred, notes FROM people WHERE name = ?",
                (hit_subject,),
            ).fetchone()
            mems = conn.execute(
                "SELECT id, fact FROM memories WHERE subject = ? ORDER BY id",
                (hit_subject,),
            ).fetchall()

        if person:
            asked_relation = any(t.startswith(t_) for t in toks for t_ in _PERSON_TRIGGERS)
            # "من أحمد؟" / "من هذا؟" -> state the relation plainly
            lead = f"{person['name']} {person['relation']}."
            if person["preferred"]:
                lead = f"{person['name']} {person['relation']}. {person['preferred']}."
            extra = [m["fact"] for m in mems]
            basis = [f"people:{person['id']}"] + [f"memories:{m['id']}" for m in mems]
            if extra:
                return Answer(" ".join([lead] + extra[:2]), basis, "answered")
            return Answer(lead, basis, "answered")

        if mems:
            return Answer(mems[0]["fact"], [f"memories:{mems[0]['id']}"], "answered")

    # 2) Place / routine / home questions -> look at those memory kinds
    place_words = ("اعيش", "أعيش", "بيت", "منزل", "مكان", "وين")
    routine_words = ("اليوم", "افعل", "أفعل", "روتين", "نشاط")
    if any(w in q for w in place_words):
        with connect() as conn:
            row = conn.execute(
                "SELECT id, fact FROM memories WHERE kind IN ('place','fact') ORDER BY id LIMIT 1"
            ).fetchone()
        if row:
            return Answer(row["fact"], [f"memories:{row['id']}"], "answered")
    if any(w in q for w in routine_words):
        with connect() as conn:
            row = conn.execute(
                "SELECT id, fact FROM memories WHERE kind = 'routine' ORDER BY id LIMIT 1"
            ).fetchone()
        if row:
            return Answer(row["fact"], [f"memories:{row['id']}"], "answered")

    # 3) No subject match -> try a plain keyword search over facts
    if toks:
        with connect() as conn:
            rows = conn.execute("SELECT id, fact FROM memories").fetchall()
        for r in rows:
            if all(t in r["fact"] for t in toks if len(t) > 2):
                return Answer(r["fact"], [f"memories:{r['id']}"], "answered")

    # 4) Nothing grounded -> refuse. Never guess.
    return Answer(I_DONT_KNOW, [], "refused")
