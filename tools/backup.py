"""SQLite-Backup mit Rotation.

Erstellt tägliche Backups der Datenbank und rotiert alte Backups.
Kann per Cron oder manuell ausgeführt werden.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from tools.config import ROOT
from tools.db import DB_PATH

logger = logging.getLogger(__name__)

BACKUP_DIR = ROOT / "backups"


def create_backup(tag: str | None = None) -> Path:
    """Erstellt ein Backup der SQLite-Datenbank.

    Nutzt SQLite Online-Backup-API (konsistent, auch bei laufendem Betrieb).
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"fibu_agent_{tag}.db"

    if not DB_PATH.exists():
        logger.warning("Keine Datenbank zum Sichern: %s", DB_PATH)
        return backup_path

    # SQLite Online-Backup (sicher bei laufendem Betrieb)
    source = sqlite3.connect(str(DB_PATH))
    dest = sqlite3.connect(str(backup_path))
    source.backup(dest)
    dest.close()
    source.close()

    size_kb = backup_path.stat().st_size / 1024
    logger.info("Backup erstellt: %s (%.1f KB)", backup_path.name, size_kb)
    return backup_path


def rotate_backups(keep: int = 30) -> int:
    """Löscht alte Backups, behält die neuesten `keep` Stück."""
    if not BACKUP_DIR.exists():
        return 0

    backups = sorted(BACKUP_DIR.glob("fibu_agent_*.db"), reverse=True)
    deleted = 0
    for old in backups[keep:]:
        old.unlink()
        deleted += 1
        logger.info("Altes Backup gelöscht: %s", old.name)

    return deleted


def list_backups() -> list[dict]:
    """Listet alle vorhandenen Backups."""
    if not BACKUP_DIR.exists():
        return []
    backups = []
    for f in sorted(BACKUP_DIR.glob("fibu_agent_*.db"), reverse=True):
        backups.append({
            "datei": f.name,
            "pfad": str(f),
            "groesse_kb": round(f.stat().st_size / 1024, 1),
            "erstellt": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups


def restore_backup(backup_path: Path) -> bool:
    """Stellt ein Backup wieder her (überschreibt aktuelle DB)."""
    backup_path = Path(backup_path)
    if not backup_path.exists():
        logger.error("Backup nicht gefunden: %s", backup_path)
        return False

    # Sicherheitskopie der aktuellen DB
    if DB_PATH.exists():
        safety = BACKUP_DIR / f"fibu_agent_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(DB_PATH), str(safety))
        logger.info("Sicherheitskopie vor Restore: %s", safety.name)

    shutil.copy2(str(backup_path), str(DB_PATH))
    logger.info("Datenbank wiederhergestellt aus: %s", backup_path.name)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backup"
    if cmd == "backup":
        path = create_backup()
        deleted = rotate_backups()
        print(f"Backup: {path}")
        if deleted:
            print(f"{deleted} alte Backups gelöscht")
    elif cmd == "list":
        for b in list_backups():
            print(f"  {b['datei']:40s} {b['groesse_kb']:8.1f} KB  {b['erstellt']}")
    elif cmd == "restore" and len(sys.argv) > 2:
        restore_backup(Path(sys.argv[2]))
    else:
        print("Verwendung: python -m tools.backup [backup|list|restore <datei>]")
