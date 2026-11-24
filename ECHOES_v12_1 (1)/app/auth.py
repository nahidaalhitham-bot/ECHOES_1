"""Authentication and authorisation.

What this is: password hashing, session tokens, roles, and access guards.
What this is NOT: a claim that a virus-level threat model is covered. It is a
prototype-grade gate — enough that a location feed is not public, and honest
about the rest.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib, no dependency). Sessions
are random tokens stored server-side and carried in an HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException

from .db import connect

PBKDF2_ROUNDS = 120_000
SESSION_HOURS = 12

ROLE_ORDER = {"viewer": 1, "caregiver": 2, "owner": 3}


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        # constant-time comparison
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def create_user(email: str, password: str, full_name: str, role: str = "caregiver") -> int:
    if role not in ROLE_ORDER:
        raise ValueError("unknown role")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users(email,password_hash,full_name,role) VALUES (?,?,?,?)",
            (email.strip().lower(), hash_password(password), full_name, role),
        )
        return cur.lastrowid


def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def authenticate(email: str, password: str) -> dict | None:
    with connect() as conn:
        u = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    if not u or not verify_password(password, u["password_hash"]):
        return None
    return dict(u)


def new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token,user_id,expires_at) VALUES (?,?,?)",
            (token, user_id, expires),
        )
        conn.execute(
            "INSERT INTO audit(actor,action,detail) VALUES (?,?,?)",
            (str(user_id), "login", None),
        )
    return token


def end_session(token: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT s.expires_at, u.id, u.email, u.full_name, u.role "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        end_session(token)
        return None
    return {"id": row["id"], "email": row["email"],
            "full_name": row["full_name"], "role": row["role"]}


# --------------------------------------------------------------- guards ----

def current_user(session: str | None = Cookie(default=None)) -> dict | None:
    return user_for_token(session)


def require_user(session: str | None = Cookie(default=None)) -> dict:
    u = user_for_token(session)
    if not u:
        raise HTTPException(status_code=401, detail="يجب تسجيل الدخول")
    return u


def require_role(min_role: str):
    """Dependency factory: require at least this role."""
    def _dep(user: dict = Depends(require_user)) -> dict:
        if ROLE_ORDER.get(user["role"], 0) < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=403, detail="لا تملك صلاحية لهذا الإجراء")
        return user
    return _dep
