"""Monitoring: Systemstatus, Health-Check und optionale Alerts.

Stellt Metriken bereit für:
- Anzahl Belege nach Status
- API-Budget-Status
- Datenbankgröße
- Letzte Runs und Fehlerrate
- Disk-Usage der Inbox/Outbox/Archiv
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from tools.config import ROOT

logger = logging.getLogger(__name__)

ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
SMTP_HOST = os.environ.get("ALERT_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ALERT_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ALERT_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("ALERT_SMTP_PASSWORD", "")


def health_check() -> dict:
    """Führt einen umfassenden Health-Check durch."""
    checks: dict[str, dict] = {}

    # 1. Datenbank erreichbar?
    try:
        from tools.db import get_stats
        stats = get_stats()
        checks["database"] = {"status": "ok", "belege_total": stats.get("total", 0)}
    except Exception as exc:
        checks["database"] = {"status": "error", "message": str(exc)}

    # 2. API-Budget
    try:
        from tools.cost_tracker import get_costs
        daily = get_costs("today")
        monthly = get_costs("month")
        budget_ok = not daily.get("budget_exceeded", False) and not monthly.get("budget_exceeded", False)
        checks["api_budget"] = {
            "status": "ok" if budget_ok else "warning",
            "daily_eur": daily.get("total_eur", 0),
            "monthly_eur": monthly.get("total_eur", 0),
            "budget_exceeded": not budget_ok,
        }
    except Exception as exc:
        checks["api_budget"] = {"status": "error", "message": str(exc)}

    # 3. Disk-Space
    try:
        dirs_info = {}
        for name, path in [("inbox", ROOT / "inbox"), ("outbox", ROOT / "outbox"), ("archiv", ROOT / "archiv")]:
            if path.exists():
                total_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                file_count = sum(1 for f in path.rglob("*") if f.is_file())
                dirs_info[name] = {"size_mb": round(total_size / 1024 / 1024, 2), "files": file_count}
            else:
                dirs_info[name] = {"size_mb": 0, "files": 0}
        checks["storage"] = {"status": "ok", "directories": dirs_info}
    except Exception as exc:
        checks["storage"] = {"status": "error", "message": str(exc)}

    # 4. DB-Datei
    try:
        from tools.db import DB_PATH
        if DB_PATH.exists():
            db_size_mb = round(DB_PATH.stat().st_size / 1024 / 1024, 2)
            checks["db_file"] = {"status": "ok", "size_mb": db_size_mb}
        else:
            checks["db_file"] = {"status": "warning", "message": "DB-Datei nicht gefunden"}
    except Exception as exc:
        checks["db_file"] = {"status": "error", "message": str(exc)}

    # 5. Letzte Runs
    try:
        from tools.db import get_runs
        recent = get_runs(limit=5)
        fehler_runs = sum(1 for r in recent if r.get("belege_fehler", 0) > 0)
        checks["recent_runs"] = {
            "status": "ok" if fehler_runs == 0 else "warning",
            "total_recent": len(recent),
            "with_errors": fehler_runs,
        }
    except Exception as exc:
        checks["recent_runs"] = {"status": "error", "message": str(exc)}

    # Gesamtstatus
    all_ok = all(c.get("status") == "ok" for c in checks.values())
    has_error = any(c.get("status") == "error" for c in checks.values())

    return {
        "healthy": all_ok,
        "status": "error" if has_error else ("warning" if not all_ok else "ok"),
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }


def send_alert(subject: str, body: str) -> bool:
    """Sendet eine Alert-E-Mail (falls konfiguriert)."""
    if not ALERT_EMAIL or not SMTP_HOST:
        logger.debug("Alerting nicht konfiguriert — überspringe")
        return False

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[FiBu-Agent] {subject}"
        msg["From"] = SMTP_USER or "fibu-agent@localhost"
        msg["To"] = ALERT_EMAIL

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Alert gesendet: %s → %s", subject, ALERT_EMAIL)
        return True
    except Exception as exc:
        logger.error("Alert-Versand fehlgeschlagen: %s", exc)
        return False


def check_and_alert() -> None:
    """Prüft Health und sendet Alerts bei Problemen."""
    result = health_check()

    if result["status"] == "error":
        errors = [f"  {k}: {v.get('message', v.get('status'))}"
                  for k, v in result["checks"].items() if v.get("status") == "error"]
        send_alert(
            "FEHLER im System",
            f"Health-Check fehlgeschlagen:\n\n" + "\n".join(errors)
        )

    # Budget-Warnung bei > 80%
    budget = result["checks"].get("api_budget", {})
    if budget.get("budget_exceeded"):
        send_alert(
            "API-Budget erschöpft",
            f"Tageskosten: {budget.get('daily_eur', 0):.2f} EUR\n"
            f"Monatskosten: {budget.get('monthly_eur', 0):.2f} EUR"
        )
