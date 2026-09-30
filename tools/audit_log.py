"""GoBD-konformes Audit-Log: lückenloser, manipulationssicherer Änderungsverlauf.

Jede Aktion am Beleg wird als Event gespeichert. Events sind append-only —
einmal geschrieben, nie geändert oder gelöscht. Jeder Eintrag enthält einen
SHA-256-Hash des vorherigen Eintrags (Blockchain-Prinzip), sodass nachträgliche
Manipulation erkennbar ist.

GoBD-Anforderungen die hierdurch erfüllt werden:
- Nachvollziehbarkeit (jede Änderung ist dokumentiert)
- Unveränderbarkeit (Hash-Kette erkennt Manipulation)
- Zeitstempel (jedes Event hat ISO-Timestamp)
- Vollständigkeit (jeder Statusübergang wird erfasst)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tools.config import OUTBOX_DIR

logger = logging.getLogger(__name__)

AUDIT_DIR = OUTBOX_DIR / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _hash_entry(entry: dict) -> str:
    """SHA-256 über den gesamten Eintrag (deterministisch sortiert)."""
    raw = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_log_path(beleg_id: str) -> Path:
    """Ein Audit-Log pro Beleg: audit/<beleg_id>.jsonl"""
    safe_id = beleg_id.replace("/", "_").replace(" ", "_")
    return AUDIT_DIR / f"{safe_id}.jsonl"


def _last_hash(log_path: Path) -> str:
    """Liest den Hash des letzten Eintrags (oder '0' für den ersten)."""
    if not log_path.exists():
        return "0" * 64
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    if not lines or not lines[-1].strip():
        return "0" * 64
    last = json.loads(lines[-1])
    return last.get("hash", "0" * 64)


def log_event(
    beleg_id: str,
    event_type: str,
    details: dict | None = None,
    beleg_snapshot: dict | None = None,
    akteur: str = "fibu_agent",
) -> dict:
    """Schreibt ein unveränderliches Audit-Event.

    event_type: z.B. 'eingang', 'ocr_extraktion', 'kontierung', 'validierung',
                'export', 'rueckfrage', 'manuelle_korrektur', 'archivierung'
    """
    log_path = _get_log_path(beleg_id)
    prev_hash = _last_hash(log_path)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "beleg_id": beleg_id,
        "event_type": event_type,
        "akteur": akteur,
        "details": details or {},
        "prev_hash": prev_hash,
    }

    # Beleg-Snapshot nur bei Statusübergängen (für Nachvollziehbarkeit)
    if beleg_snapshot:
        # Sensible Daten reduzieren — nur buchhalterisch relevante Felder
        entry["beleg_snapshot"] = {
            k: beleg_snapshot.get(k)
            for k in [
                "id", "status", "lieferant", "rechnungsnummer", "belegdatum",
                "bruttobetrag", "nettobetrag", "mwst_betrag", "mwst_satz",
                "soll_konto", "haben_konto", "steuerschluessel",
                "kontierung_methode", "konfidenz", "ocr_konfidenz",
                "buchungstext", "rueckfrage",
            ]
        }

    entry["hash"] = _hash_entry(entry)

    # Append-only: nur anhängen, nie überschreiben
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("audit [%s] %s: %s", beleg_id, event_type, entry["hash"][:12])
    return entry


def verify_log(beleg_id: str) -> dict:
    """Prüft die Integrität eines Beleg-Audit-Logs.

    Returns: {valid: bool, entries: int, fehler: [...]}
    """
    log_path = _get_log_path(beleg_id)
    if not log_path.exists():
        return {"valid": False, "entries": 0, "fehler": ["Kein Audit-Log gefunden"]}

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    fehler = []
    prev_hash = "0" * 64

    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            fehler.append(f"Zeile {i + 1}: Ungültiges JSON")
            continue

        # Hash-Kette prüfen
        if entry.get("prev_hash") != prev_hash:
            fehler.append(
                f"Zeile {i + 1}: Hash-Kette unterbrochen "
                f"(erwartet {prev_hash[:12]}..., gefunden {entry.get('prev_hash', '?')[:12]}...)"
            )

        # Eigenen Hash verifizieren
        stored_hash = entry.pop("hash", "")
        computed = _hash_entry(entry)
        entry["hash"] = stored_hash  # wiederherstellen
        if stored_hash != computed:
            fehler.append(f"Zeile {i + 1}: Hash-Manipulation erkannt")

        prev_hash = stored_hash

    return {
        "valid": len(fehler) == 0,
        "entries": len(lines),
        "fehler": fehler,
    }


def get_history(beleg_id: str) -> list[dict]:
    """Liest die vollständige Änderungshistorie eines Belegs."""
    log_path = _get_log_path(beleg_id)
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").strip().split("\n") if line.strip()]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        bid = sys.argv[1]
        result = verify_log(bid)
        print(f"Audit-Log {bid}: {result['entries']} Einträge, valid={result['valid']}")
        if result["fehler"]:
            for f in result["fehler"]:
                print(f"  ✗ {f}")
        else:
            print("  ✓ Hash-Kette intakt")
    else:
        print("Usage: python -m tools.audit_log <beleg_id>")
