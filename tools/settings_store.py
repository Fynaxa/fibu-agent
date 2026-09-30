"""Persistente Einstellungen in SQLite — ersetzt .env für Laufzeit-Konfiguration."""
from __future__ import annotations

import logging
import os
from tools.db import get_db

logger = logging.getLogger(__name__)

# Standardwerte (Fallback wenn nichts in der DB steht)
DEFAULTS: dict[str, str] = {
    "scheduler_active":       "false",
    "scheduler_time":         "18:00",
    "report_email_to":        "",
    "konfidenz_schwelle":     "0.7",
    "daily_budget_eur":       "10.00",
    "monthly_budget_eur":     "100.00",
    "imap_host":              "imap.gmail.com",
    "imap_user":              "",
    "imap_password":          "",
    "smtp_host":              "smtp.gmail.com",
    "smtp_port":              "587",
    "public_url":             "",
    "vapi_secret":            "",
    "vapi_phone_number":      "",
}


def _ensure_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)


def get(key: str) -> str:
    """Liest einen Wert — DB hat Vorrang vor .env, .env vor Default."""
    _ensure_table()
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row["value"] != "":
                return row["value"]
    except Exception as exc:
        logger.warning("settings_store.get(%s) fehlgeschlagen: %s", key, exc)
    # Fallback: Umgebungsvariable
    env_map = {
        "scheduler_active":   "PIPELINE_SCHEDULE_ACTIVE",
        "scheduler_time":     "PIPELINE_SCHEDULE_TIME",
        "report_email_to":    "REPORT_EMAIL_TO",
        "konfidenz_schwelle": "KONFIDENZ_SCHWELLE",
        "daily_budget_eur":   "DAILY_BUDGET_EUR",
        "monthly_budget_eur": "MONTHLY_BUDGET_EUR",
        "imap_host":          "IMAP_HOST",
        "imap_user":          "IMAP_USER",
        "imap_password":      "IMAP_PASSWORD",
        "smtp_host":          "SMTP_HOST",
        "smtp_port":          "SMTP_PORT",
        "public_url":         "PUBLIC_URL",
    }
    if key in env_map:
        val = os.getenv(env_map[key], "")
        if val:
            return val
    return DEFAULTS.get(key, "")


def set(key: str, value: str) -> None:
    """Speichert einen Wert in der DB."""
    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_all() -> dict[str, str]:
    """Gibt alle gespeicherten Einstellungen zurück (inkl. Defaults)."""
    result = dict(DEFAULTS)
    _ensure_table()
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT key, value FROM settings"):
                result[row["key"]] = row["value"]
    except Exception:
        pass
    # Umgebungsvariablen als Fallback für leere DB-Werte
    for key in DEFAULTS:
        if not result.get(key):
            result[key] = get(key)
    return result
