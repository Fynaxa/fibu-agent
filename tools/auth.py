"""Authentifizierung: Benutzerverwaltung mit bcrypt-Hashing.

Benutzer werden in einer SQLite-Tabelle gespeichert.
Passwörter werden mit bcrypt gehasht (nie im Klartext).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime

from tools.db import get_db

logger = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    """Hasht ein Passwort mit bcrypt."""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify_password(password: str, hashed: str) -> bool:
    """Prüft ein Passwort gegen den Hash."""
    import bcrypt
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))


def init_auth_tables():
    """Erstellt die Auth-Tabellen falls nicht vorhanden."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                role TEXT DEFAULT 'user',
                mandant_ids TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT,
                last_login TEXT
            );
        """)


def create_user(username: str, password: str, display_name: str = "",
                role: str = "user", mandant_ids: list[str] | None = None) -> bool:
    """Erstellt einen neuen Benutzer. Returns True bei Erfolg."""
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO users (username, password_hash, display_name, role, mandant_ids, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (username, _hash_password(password), display_name or username,
                 role, ",".join(mandant_ids) if mandant_ids else "",
                 datetime.now().isoformat())
            )
        logger.info("Benutzer erstellt: %s (Rolle: %s)", username, role)
        return True
    except Exception as exc:
        logger.error("Benutzer konnte nicht erstellt werden: %s", exc)
        return False


def authenticate(username: str, password: str) -> dict | None:
    """Authentifiziert einen Benutzer. Returns User-Dict oder None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
        ).fetchone()

    if not row:
        return None

    user = dict(row)
    if not _verify_password(password, user["password_hash"]):
        return None

    # Last login aktualisieren
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().isoformat(), user["id"])
        )

    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "mandant_ids": user["mandant_ids"].split(",") if user["mandant_ids"] else [],
    }


def get_user(user_id: int) -> dict | None:
    """Holt einen Benutzer anhand der ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
    if not row:
        return None
    user = dict(row)
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "mandant_ids": user["mandant_ids"].split(",") if user["mandant_ids"] else [],
    }


def list_users() -> list[dict]:
    """Listet alle aktiven Benutzer."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, role, mandant_ids, created_at, last_login FROM users WHERE active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def change_password(user_id: int, new_password: str) -> bool:
    """Ändert das Passwort eines Benutzers."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(new_password), user_id)
        )
    return True


def deactivate_user(user_id: int) -> bool:
    """Deaktiviert einen Benutzer (kein echtes Löschen)."""
    with get_db() as conn:
        conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
    return True


def ensure_admin_exists():
    """Erstellt einen Admin-Benutzer, falls noch keiner existiert."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin' AND active = 1").fetchone()
    if row["cnt"] == 0:
        default_pw = os.environ.get("ADMIN_PASSWORD", "admin")
        create_user("admin", default_pw, display_name="Administrator", role="admin")
        if default_pw == "admin":
            logger.warning("Standard-Admin erstellt mit Passwort 'admin' — BITTE SOFORT ÄNDERN!")
        else:
            logger.info("Admin-Benutzer erstellt mit Passwort aus ADMIN_PASSWORD")
