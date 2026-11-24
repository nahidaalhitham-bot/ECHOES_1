"""Photo uploads for the patient portrait and family members.

Storage: files land in app/uploads/<uuid>.<ext> on disk; the database keeps the
mapping. Serving is authenticated — a stranger cannot fetch a family photo by
guessing a URL, which matters because these are pictures of real people.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from .db import connect

UPLOAD_DIR = Path(os.environ.get(
    "ECHEOS_UPLOADS",
    str(Path(__file__).resolve().parent / "uploads"),
))

# Conservative allow-list. We do not trust the filename or the client's
# content-type; the extension is derived from the detected signature.
SIGNATURES = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}
MAX_BYTES = 8 * 1024 * 1024  # 8 MB

_MIME = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
         "webp": "image/webp"}


class PhotoError(Exception):
    pass


def _detect_ext(data: bytes) -> str | None:
    for sig, ext in SIGNATURES.items():
        if data.startswith(sig):
            return ext
    # WEBP: RIFF....WEBP
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_photo(owner_type: str, owner_id: int, data: bytes) -> dict:
    """Store one image for a patient or family member, replacing the old one."""
    if owner_type not in ("patient", "person", "memory"):
        raise PhotoError("unknown owner type")
    if not data:
        raise PhotoError("الملف فارغ")
    if len(data) > MAX_BYTES:
        raise PhotoError("الصورة أكبر من ٨ ميجابايت")

    ext = _detect_ext(data)
    if ext is None:
        raise PhotoError("الملف ليس صورة صالحة (JPG أو PNG أو GIF أو WEBP)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{owner_type}_{owner_id}_{secrets.token_hex(8)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)

    with connect() as conn:
        old = conn.execute(
            "SELECT filename FROM photos WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id),
        ).fetchall()
        conn.execute(
            "DELETE FROM photos WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id),
        )
        conn.execute(
            "INSERT INTO photos(owner_type,owner_id,filename,mime,bytes) VALUES (?,?,?,?,?)",
            (owner_type, owner_id, name, _MIME[ext], len(data)),
        )
    # Remove superseded files (best effort; a missing file is not an error).
    for row in old:
        try:
            (UPLOAD_DIR / row["filename"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"filename": name, "mime": _MIME[ext], "bytes": len(data)}


def save_album_photo(memory_id: int, data: bytes) -> dict:
    """Append (not replace) a photo to a memory's album."""
    if not data:
        raise PhotoError("الملف فارغ")
    if len(data) > MAX_BYTES:
        raise PhotoError("الصورة أكبر من ٨ ميجابايت")
    ext = _detect_ext(data)
    if ext is None:
        raise PhotoError("الملف ليس صورة صالحة (JPG أو PNG أو GIF أو WEBP)")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"memory_{memory_id}_{secrets.token_hex(8)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO photos(owner_type,owner_id,filename,mime,bytes) VALUES ('memory',?,?,?,?)",
            (memory_id, name, _MIME[ext], len(data)),
        )
        pid = cur.lastrowid
        n = conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE owner_type='memory' AND owner_id=?",
            (memory_id,),
        ).fetchone()["c"]
    return {"id": pid, "filename": name, "mime": _MIME[ext],
            "bytes": len(data), "index": n, "label": f"صورة رقم {n}"}


def list_album_photos(memory_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM photos WHERE owner_type='memory' AND owner_id=? ORDER BY id",
            (memory_id,),
        ).fetchall()
    out = []
    for i, r in enumerate(rows, start=1):
        out.append({"id": r["id"], "index": i, "label": f"صورة رقم {i}",
                    "mime": r["mime"], "uploaded_at": r["uploaded_at"]})
    return out


def get_album_photo(photo_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE id = ? AND owner_type='memory'", (photo_id,)
        ).fetchone()
    if row is None:
        return None
    path = UPLOAD_DIR / row["filename"]
    if not path.exists():
        return None
    return {"path": path, "mime": row["mime"], "filename": row["filename"]}


def delete_album_photo(photo_id: int) -> bool:
    got = get_album_photo(photo_id)
    if got is None:
        return False
    got["path"].unlink(missing_ok=True)
    with connect() as conn:
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    return True


# ------------------------------------------------------------------ audio --

AUDIO_SIGS = {
    b"ID3": "mp3",
    b"OggS": "ogg",
    b"fLaC": "flac",
    b"RIFF": "wav",
}
MAX_AUDIO = 25 * 1024 * 1024


def _detect_audio(data: bytes) -> str | None:
    for sig, ext in AUDIO_SIGS.items():
        if data.startswith(sig):
            return ext
    # MP4/M4A container
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "m4a"
    # Some MP3 files start with a frame sync
    if len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "mp3"
    return None


AUDIO_MIME = {"mp3": "audio/mpeg", "ogg": "audio/ogg", "flac": "audio/flac",
              "wav": "audio/wav", "m4a": "audio/mp4"}


def save_audio(memory_id: int, data: bytes) -> dict:
    if not data:
        raise PhotoError("الملف الصوتي فارغ")
    if len(data) > MAX_AUDIO:
        raise PhotoError("الملف الصوتي أكبر من ٢٥ ميجابايت")
    ext = _detect_audio(data)
    if ext is None:
        raise PhotoError("الملف ليس صوتًا صالحًا (MP3 أو M4A أو WAV أو OGG)")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"audio_{memory_id}_{secrets.token_hex(8)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO audio_clips(memory_id,filename,mime,bytes) VALUES (?,?,?,?)",
            (memory_id, name, AUDIO_MIME[ext], len(data)),
        )
        aid = cur.lastrowid
        n = conn.execute(
            "SELECT COUNT(*) c FROM audio_clips WHERE memory_id=?", (memory_id,)
        ).fetchone()["c"]
        label = f"صوت رقم {n}"
        conn.execute("UPDATE audio_clips SET label = ? WHERE id = ?", (label, aid))
    return {"id": aid, "index": n, "label": label,
            "mime": AUDIO_MIME[ext], "bytes": len(data)}


def list_audio(memory_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audio_clips WHERE memory_id=? ORDER BY id", (memory_id,)
        ).fetchall()
    return [{"id": r["id"], "index": i, "label": r["label"] or f"صوت رقم {i}",
             "mime": r["mime"], "uploaded_at": r["uploaded_at"]}
            for i, r in enumerate(rows, start=1)]


def get_audio(clip_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM audio_clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        return None
    path = UPLOAD_DIR / row["filename"]
    if not path.exists():
        return None
    return {"path": path, "mime": row["mime"]}


def delete_audio(clip_id: int) -> bool:
    got = get_audio(clip_id)
    if got is None:
        return False
    got["path"].unlink(missing_ok=True)
    with connect() as conn:
        conn.execute("DELETE FROM audio_clips WHERE id = ?", (clip_id,))
    return True


def get_photo(owner_type: str, owner_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM photos WHERE owner_type = ? AND owner_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (owner_type, owner_id),
        ).fetchone()
    if row is None:
        return None
    path = UPLOAD_DIR / row["filename"]
    if not path.exists():
        return None
    return {"path": path, "mime": row["mime"], "filename": row["filename"],
            "bytes": row["bytes"]}


def delete_photo(owner_type: str, owner_id: int) -> bool:
    got = get_photo(owner_type, owner_id)
    if got is None:
        return False
    try:
        got["path"].unlink(missing_ok=True)
    except OSError:
        pass
    with connect() as conn:
        conn.execute(
            "DELETE FROM photos WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id),
        )
    return True


def safe_name(name: str) -> str:
    """Only used for download headers."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "photo"
