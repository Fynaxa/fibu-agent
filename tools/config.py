"""Zentrale Konfiguration: .env laden, Pfade und Konstanten."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
INBOX_DIR = Path(os.getenv("INBOX_WATCH_DIR", str(ROOT / "inbox")))
OUTBOX_DIR = ROOT / "outbox"
ARCHIV_DIR = ROOT / "archiv"
DATEV_BERATER_NR = os.getenv("DATEV_BERATER_NR", "")
DATEV_MANDANT_NR = os.getenv("DATEV_MANDANT_NR", "")
KONTENRAHMEN = os.getenv("KONTENRAHMEN", "SKR03")
KONFIDENZ_SCHWELLE = float(os.getenv("KONFIDENZ_SCHWELLE", "0.7"))

MAILGUN_SIGNING_KEY = os.getenv("MAILGUN_SIGNING_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "inbox.fynaxa.de")

WORKFLOWS_DIR = ROOT / "workflows"
SKR03_RULES_PATH = WORKFLOWS_DIR / "skr03_rules.json"
SKR04_RULES_PATH = WORKFLOWS_DIR / "skr04_rules.json"

for d in (INBOX_DIR, OUTBOX_DIR, ARCHIV_DIR):
    d.mkdir(parents=True, exist_ok=True)


def load_skr03_rules() -> list[dict]:
    if SKR03_RULES_PATH.exists():
        return json.loads(SKR03_RULES_PATH.read_text(encoding="utf-8"))
    return []


def load_skr04_rules() -> list[dict]:
    if SKR04_RULES_PATH.exists():
        return json.loads(SKR04_RULES_PATH.read_text(encoding="utf-8"))
    return []


def load_rules(kontenrahmen: str = "SKR03") -> list[dict]:
    """Lädt Kontierungsregeln für den angegebenen Kontenrahmen."""
    if kontenrahmen.upper() == "SKR04":
        return load_skr04_rules()
    return load_skr03_rules()


MANDANTEN_PATH = WORKFLOWS_DIR / "mandanten.json"


def load_mandanten() -> list[dict]:
    if MANDANTEN_PATH.exists():
        data = json.loads(MANDANTEN_PATH.read_text(encoding="utf-8"))
        return data.get("mandanten", [])
    return []


def get_mandant(mandant_id: str) -> dict | None:
    for m in load_mandanten():
        if m["id"] == mandant_id:
            return m
    return None


def save_mandanten(mandanten: list[dict]) -> None:
    """Speichert die Mandantenliste zurück in die JSON-Datei."""
    MANDANTEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"mandanten": mandanten}
    MANDANTEN_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_mandant(mandant: dict) -> bool:
    """Fügt einen neuen Mandanten hinzu. Returns False wenn ID schon existiert."""
    mandanten = load_mandanten()
    if any(m["id"] == mandant["id"] for m in mandanten):
        return False
    mandanten.append(mandant)
    save_mandanten(mandanten)
    return True


def update_mandant(mandant_id: str, updates: dict) -> bool:
    """Aktualisiert einen bestehenden Mandanten."""
    mandanten = load_mandanten()
    for i, m in enumerate(mandanten):
        if m["id"] == mandant_id:
            mandanten[i].update(updates)
            save_mandanten(mandanten)
            return True
    return False


def delete_mandant(mandant_id: str) -> bool:
    """Entfernt einen Mandanten aus der Konfiguration."""
    mandanten = load_mandanten()
    new_list = [m for m in mandanten if m["id"] != mandant_id]
    if len(new_list) == len(mandanten):
        return False
    save_mandanten(new_list)
    return True


def mandant_dirs(mandant: dict) -> dict:
    """Gibt die Pfade für inbox/outbox/archiv eines Mandanten zurück und legt sie an."""
    dirs = {
        "inbox": ROOT / mandant.get("inbox", f"inbox/{mandant['id']}"),
        "outbox": ROOT / mandant.get("outbox", f"outbox/{mandant['id']}"),
        "archiv": ROOT / mandant.get("archiv", f"archiv/{mandant['id']}"),
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs
