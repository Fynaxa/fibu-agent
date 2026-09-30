"""Auto-Scheduler: startet die Pipeline täglich zur konfigurierten Uhrzeit."""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_scheduler = None
_last_run: str | None = None
_last_result: dict | None = None


def _settings():
    from tools.settings_store import get
    return {
        "active": get("scheduler_active").lower() == "true",
        "time":   get("scheduler_time") or "18:00",
    }


def _run_all_mandanten():
    global _last_run, _last_result
    from agents.fibu_agent import run
    from tools.config import load_mandanten
    from tools.report_email import send_report
    from pathlib import Path

    _last_run = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info("Scheduler: Automatischer Pipeline-Run um %s", _last_run)

    mandanten = load_mandanten()
    if not mandanten:
        result = run(imap=True)
        export = result.get("export_datei")
        send_report(result, export_path=Path(export) if export else None)
        _last_result = result
        return

    combined = {"belege": 0, "exportiert": 0, "rueckfragen": 0, "fehler": 0}
    for m in mandanten:
        try:
            result = run(imap=True, mandant_id=m["id"])
            export = result.get("export_datei")
            to = m.get("report_email") or ""
            send_report(result,
                        export_path=Path(export) if export else None,
                        mandant_name=m["name"],
                        to_email=to or None)
            for k in combined:
                combined[k] += result.get(k, 0)
        except Exception as exc:
            logger.exception("Scheduler: Fehler bei Mandant %s: %s", m["id"], exc)
    _last_result = combined


def _schedule_time() -> tuple[int, int]:
    t = _settings()["time"]
    try:
        h, m = map(int, t.split(":"))
        return h, m
    except ValueError:
        return 18, 0


def start(app=None):
    """Startet oder aktualisiert den Hintergrund-Scheduler."""
    global _scheduler

    cfg = _settings()
    if not cfg["active"]:
        logger.info("Scheduler deaktiviert.")
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    hour, minute = _schedule_time()

    if _scheduler and _scheduler.running:
        # Bestehenden Job aktualisieren
        _scheduler.reschedule_job(
            "fibu_daily",
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Europe/Berlin"),
        )
        logger.info("Scheduler aktualisiert: täglich um %02d:%02d", hour, minute)
        return

    _scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    _scheduler.add_job(
        _run_all_mandanten,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="Europe/Berlin"),
        id="fibu_daily",
        name=f"FiBu-Pipeline täglich {hour:02d}:{minute:02d}",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler gestartet: täglich um %02d:%02d (Europe/Berlin)", hour, minute)


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler gestoppt.")


def status() -> dict:
    cfg = _settings()
    running = _scheduler is not None and _scheduler.running
    next_run = "–"
    if running and _scheduler:
        job = _scheduler.get_job("fibu_daily")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M")
    return {
        "active":       cfg["active"],
        "time":         cfg["time"],
        "running":      running,
        "next_run":     next_run,
        "last_run":     _last_run or "–",
        "last_result":  _last_result,
    }
