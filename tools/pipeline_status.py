"""Pipeline-Status-Tracking für die Web-UI.

Speichert den aktuellen Zustand laufender und abgeschlossener Runs
in-memory, abrufbar per API für Live-Status-Updates.
"""
from __future__ import annotations

import threading
from datetime import datetime

_lock = threading.Lock()
_runs: dict[str, dict] = {}


def start_run(run_id: str, mandant_id: str | None = None, total_belege: int = 0) -> None:
    with _lock:
        _runs[run_id] = {
            "run_id": run_id,
            "mandant_id": mandant_id,
            "status": "laufend",
            "gestartet": datetime.now().isoformat(),
            "beendet": None,
            "total": total_belege,
            "verarbeitet": 0,
            "exportiert": 0,
            "fehler": 0,
            "rueckfragen": 0,
            "aktueller_beleg": None,
            "log": [],
        }


def update_progress(run_id: str, beleg_name: str, beleg_status: str) -> None:
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        run["verarbeitet"] += 1
        run["aktueller_beleg"] = beleg_name
        if beleg_status == "exportiert" or beleg_status == "validiert":
            run["exportiert"] += 1
        elif beleg_status == "fehler":
            run["fehler"] += 1
        elif beleg_status == "rueckfrage":
            run["rueckfragen"] += 1
        run["log"].append({
            "zeit": datetime.now().strftime("%H:%M:%S"),
            "beleg": beleg_name,
            "status": beleg_status,
        })
        # Log auf 100 Einträge begrenzen
        if len(run["log"]) > 100:
            run["log"] = run["log"][-100:]


def finish_run(run_id: str, error: str | None = None) -> None:
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        run["status"] = "fehler" if error else "abgeschlossen"
        run["beendet"] = datetime.now().isoformat()
        run["aktueller_beleg"] = None
        if error:
            run["log"].append({"zeit": datetime.now().strftime("%H:%M:%S"), "beleg": "-", "status": f"FEHLER: {error}"})


def get_status(run_id: str | None = None) -> dict | list[dict]:
    """Gibt Status eines Runs oder aller Runs zurück."""
    with _lock:
        if run_id:
            return dict(_runs.get(run_id, {}))
        # Letzte 10 Runs
        return sorted(_runs.values(), key=lambda r: r.get("gestartet", ""), reverse=True)[:10]


def get_active_runs() -> list[dict]:
    """Gibt nur laufende Runs zurück."""
    with _lock:
        return [dict(r) for r in _runs.values() if r["status"] == "laufend"]
