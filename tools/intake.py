"""Belegeingang: Watchfolder und IMAP-Polling mit Plus-Addressing-Routing."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from tools.config import IMAP_HOST, IMAP_PASSWORD, IMAP_USER, INBOX_DIR, ROOT

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}


def _resolve_mandant_from_plus_address(to_header: str) -> str | None:
    """
    Liest das Plus-Tag aus der Empfänger-Adresse und gibt die Mandanten-ID zurück.
    belege+muster@gmail.com  →  "MUSTER"
    belege@gmail.com        →  None (global)
    """
    match = re.search(r"\+([a-zA-Z0-9_-]+)@", to_header or "")
    if not match:
        return None
    tag = match.group(1).upper()
    # Prüfen ob ein Mandant mit dieser ID existiert
    try:
        from tools.config import get_mandant
        if get_mandant(tag):
            return tag
    except Exception:
        pass
    logger.info("Plus-Tag '%s' keinem Mandanten zugeordnet — global", tag)
    return None


def _mandant_inbox(mandant_id: str | None) -> Path:
    """Gibt den Inbox-Pfad für einen Mandanten zurück (oder global)."""
    if not mandant_id:
        return INBOX_DIR
    try:
        from tools.config import get_mandant, mandant_dirs
        m = get_mandant(mandant_id)
        if m:
            return mandant_dirs(m)["inbox"]
    except Exception:
        pass
    return INBOX_DIR


def _today_dir() -> Path:
    d = INBOX_DIR / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def scan_folder(folder: Path | None = None) -> list[Path]:
    """Findet neue Belege im Watchfolder (nicht-rekursiv in inbox/)."""
    folder = Path(folder) if folder else INBOX_DIR
    if not folder.exists():
        logger.warning("scan_folder: Ordner existiert nicht: %s", folder)
        return []
    found = []
    skipped = 0
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            # Leere Dateien überspringen
            if f.stat().st_size == 0:
                logger.warning("Überspringe leere Datei: %s", f.name)
                skipped += 1
                continue
            found.append(f)
    if skipped:
        logger.info("scan_folder: %d Belege in %s (%d leere übersprungen)", len(found), folder, skipped)
    else:
        logger.info("scan_folder: %d Belege in %s", len(found), folder)
    return found


def poll_imap(max_messages: int = 50) -> list[Path]:
    """
    Pollt IMAP-Mailbox, speichert PDF/Bild-Anhänge.
    Unterstützt Plus-Addressing: belege+muster@gmail.com → inbox/MUSTER/
    """
    if not IMAP_USER or not IMAP_PASSWORD:
        logger.warning("IMAP nicht konfiguriert — skip")
        return []

    saved: list[Path] = []
    date_suffix = datetime.now().strftime("%Y-%m-%d")

    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST)
        conn.login(IMAP_USER, IMAP_PASSWORD)
        conn.select("INBOX")

        _, data = conn.search(None, "UNSEEN")
        msg_ids = data[0].split()[:max_messages]
        logger.info("IMAP: %d ungelesene Mails", len(msg_ids))

        for mid in msg_ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Plus-Addressing: Empfänger-Adresse auswerten
            to_header = msg.get("To", "") or msg.get("Delivered-To", "")
            mandant_id = _resolve_mandant_from_plus_address(to_header)

            inbox = _mandant_inbox(mandant_id)
            target_dir = inbox / date_suffix
            target_dir.mkdir(parents=True, exist_ok=True)

            found_attachment = False
            for part in msg.walk():
                filename = part.get_filename()
                if not filename:
                    continue
                ext = Path(filename).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                # Duplikat-Schutz
                target = target_dir / filename
                counter = 1
                while target.exists():
                    target = target_dir / f"{Path(filename).stem}_{counter}{ext}"
                    counter += 1

                target.write_bytes(part.get_payload(decode=True))
                saved.append(target)
                found_attachment = True
                logger.info("IMAP: %s → %s%s",
                            filename,
                            f"Mandant {mandant_id}/" if mandant_id else "global/",
                            target.name)

            if not found_attachment:
                logger.debug("IMAP: Mail ohne unterstützten Anhang übersprungen")

        conn.logout()
    except Exception as exc:
        logger.exception("IMAP-Fehler: %s", exc)

    return saved


def move_to_archiv(path: Path, ziel_dir: Path | None = None) -> Path:
    """Verschiebt einen verarbeiteten Beleg ins Archiv."""
    from tools.config import ARCHIV_DIR
    base = ziel_dir if ziel_dir else ARCHIV_DIR
    dest_dir = base / datetime.now().strftime("%Y-%m-%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), str(dest))
    logger.info("Archiviert: %s → %s", path.name, dest)
    return dest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mode = sys.argv[1] if len(sys.argv) > 1 else "folder"
    if mode == "imap":
        files = poll_imap()
    else:
        files = scan_folder()
    for f in files:
        print(f"  {f}")
    print(f"\n{len(files)} Belege gefunden")
