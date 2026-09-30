"""
Startet FiBu-Agent auf einem Cloud-Server (Hetzner VPS etc.).
Kein Tunnel nötig — der Server ist direkt öffentlich erreichbar.

Ausführen (wird vom systemd-Service automatisch gestartet):
  python start_server.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# .env laden
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

PORT       = int(os.environ.get("FLASK_PORT", "5001"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))


if __name__ == "__main__":
    log.info("FiBu-Agent startet auf Port %d …", PORT)
    if PUBLIC_URL:
        log.info("Öffentliche URL: %s", PUBLIC_URL)

    # PUBLIC_URL in settings_store persistieren (für Report-E-Mail-Links)
    if PUBLIC_URL:
        try:
            from tools.settings_store import get, set as settings_set
            if not get("public_url"):
                settings_set("public_url", PUBLIC_URL)
        except Exception:
            pass

    # Auto-Scheduler starten
    try:
        from tools.scheduler import start as start_scheduler
        start_scheduler()
        log.info("Scheduler gestartet.")
    except Exception as exc:
        log.warning("Scheduler konnte nicht gestartet werden: %s", exc)

    # Flask starten (blockierend)
    from web.app import app
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
