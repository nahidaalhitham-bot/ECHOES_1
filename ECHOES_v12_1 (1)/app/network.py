"""The memory network: typed nodes, typed edges, and traversal.

This is the core of ECHOES. The difference from a list of facts is that a
memory is reachable *through* what the person is looking at. If the camera
recognises the garden, the graph yields: the garden → who went there → what
event happened → what else relates to that event.

Design rules:
- Traversal is bounded (depth and node budget) so it always terminates.
- Every recalled item keeps the path that produced it, so the family can see
  *why* the advisor said something.
- Nothing is invented: if the graph has no path, the result is empty and the
  caller must say so.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .db import connect

MAX_DEPTH = 2
MAX_NODES = 12


@dataclass
class Recalled:
    node_id: int
    kind: str
    label: str
    detail: str | None
    depth: int
    via: str            # human-readable path, e.g. "الحديقة → مع → محمد"
    score: float = 0.0


def upsert_node(kind: str, label: str, detail: str | None = None,
                source: str = "manual") -> int:
    """Insert or fetch a node by (kind, label). Idempotent."""
    label = label.strip()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM nodes WHERE kind = ? AND label = ?", (kind, label)
        ).fetchone()
        if row:
            if detail:
                conn.execute("UPDATE nodes SET detail = COALESCE(NULLIF(detail,''), ?) WHERE id = ?",
                             (detail, row["id"]))
            return row["id"]
        cur = conn.execute(
            "INSERT INTO nodes(kind,label,detail,source) VALUES (?,?,?,?)",
            (kind, label, detail, source)
        )
        return cur.lastrowid


def link(src_id: int, relation: str, dst_id: int, note: str | None = None,
         source: str = "manual") -> bool:
    """Create a typed edge. Returns False if it already existed (either way)."""
    if src_id == dst_id:
        return False
    with connect() as conn:
        dup = conn.execute(
            "SELECT 1 FROM edges WHERE (src_id=? AND dst_id=?) OR (src_id=? AND dst_id=?)",
            (src_id, dst_id, dst_id, src_id)).fetchone()
        if dup and source != "manual":
            return False
        try:
            conn.execute(
                "INSERT INTO edges(src_id,relation,dst_id,note,source) VALUES (?,?,?,?,?)",
                (src_id, relation, dst_id, note, source),
            )
            return True
        except Exception:
            return False


def neighbours(node_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.relation, e.note, n.id, n.kind, n.label, n.detail, 'out' AS dir
              FROM edges e JOIN nodes n ON n.id = e.dst_id WHERE e.src_id = ?
            UNION ALL
            SELECT e.relation, e.note, n.id, n.kind, n.label, n.detail, 'in' AS dir
              FROM edges e JOIN nodes n ON n.id = e.src_id WHERE e.dst_id = ?
            """,
            (node_id, node_id),
        ).fetchall()
    return [dict(r) for r in rows]


def find_node(kind: str | None, label: str) -> dict | None:
    with connect() as conn:
        if kind:
            row = conn.execute(
                "SELECT * FROM nodes WHERE kind = ? AND label LIKE ? LIMIT 1",
                (kind, f"%{label}%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM nodes WHERE label LIKE ? LIMIT 1", (f"%{label}%",)
            ).fetchone()
    return dict(row) if row else None


def recall_from(node_id: int, max_depth: int = MAX_DEPTH) -> list[Recalled]:
    """Breadth-first traversal outward from a recognised node.

    Returns connected nodes ordered by closeness, then by how much they add.
    """
    origin = None
    with connect() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            origin = dict(row)
    if origin is None:
        return []

    seen = {node_id}
    out: list[Recalled] = []
    q = deque([(node_id, 0, origin["label"])])

    while q and len(out) < MAX_NODES:
        cur_id, depth, path = q.popleft()
        if depth >= max_depth:
            continue
        for nb in neighbours(cur_id):
            if nb["id"] in seen:
                continue
            seen.add(nb["id"])
            via = f"{path} → {nb['relation']} → {nb['label']}"
            out.append(
                Recalled(
                    node_id=nb["id"],
                    kind=nb["kind"],
                    label=nb["label"],
                    detail=nb["detail"],
                    depth=depth + 1,
                    via=via,
                    score=1.0 / (depth + 1),
                )
            )
            q.append((nb["id"], depth + 1, nb["label"]))

    out.sort(key=lambda r: (-r.score, r.node_id))
    return out


def describe_recall(result: list[Recalled]) -> str:
    """Turn a traversal into one short spoken line. Empty if nothing found."""
    if not result:
        return ""
    parts = []
    for r in result[:3]:
        if r.kind == "person" and r.via.count("→") >= 2:
            parts.append(r.label)
        elif r.detail:
            parts.append(r.detail)
        else:
            parts.append(r.label)
    return "، ".join(dict.fromkeys(parts))


def seed_network() -> None:
    """A small demonstrative network, matching the brief's garden example."""
    garden = upsert_node("place", "الحديقة", "الحديقة التي كنتم تجلسون فيها كل جمعة")
    muhammad = upsert_node("person", "محمد", "أب الأسرة")
    kids = upsert_node("person", "الأبناء", "أبناء محمد")
    friday = upsert_node("event", "نزهة الجمعة", "لقاء عائلي كل جمعة في الحديقة")
    photo = upsert_node("fact", "صورة عائلية", "صورة للعائلة في الحديقة")

    link(muhammad, "زار", garden)
    link(garden, "مع", kids)
    link(kids, "شاركوا في", friday)
    link(friday, "حدثت في", garden)
    link(friday, "لها", photo)
    link(photo, "التُقطت في", garden)
