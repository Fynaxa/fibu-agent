"""IMAP-Poller: Liest ungesehene E-Mails und speichert Anhänge mandantenspezifisch.

Plus-Addressing-Routing: belege+mueller@gmail.com → Mandant MUELLER
Unterstützte Anhänge: PDF, PNG, JPG, JPEG, TIFF, TIF
"""
from __future__ import annotations

import email
import email.header
import imaplib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SUPPORTED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}


def _decode_header(value: str) -> str:
    parts = email.header.decode_header(value or "")
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _extract_plus_part(address: str, base_user: str) -> str | None:
    """Gibt den Mandanten-Teil aus einer Plus-Adresse zurück.

    'belege+mueller@gmail.com', base='belege@gmail.com' → 'MUELLER'
    """
    match = re.search(r"[\w.+%-]+@[\w.-]+", address.lower())
    if not match:
        return None
    addr = match.group(0)
    if "+" not in addr:
        return None
    base_local = base_user.split("@")[0].lower() if "@" in base_user else base_user.lower()
    local = addr.split("@")[0]
    prefix = base_local + "+"
    if not local.startswith(prefix):
        return None
    return local[len(prefix):].upper()


def _find_mandant_id(msg: email.message.Message, imap_user: str) -> str | None:
    """Sucht in To/Delivered-To/X-Original-To nach einer passenden Plus-Adresse."""
    for header in ("To", "Delivered-To", "X-Original-To", "CC"):
        value = msg.get(header, "")
        for part in value.split(","):
            mid = _extract_plus_part(part.strip(), imap_user)
            if mid:
                return mid
    return None


def poll(
    imap_host: str,
    imap_user: str,
    imap_password: str,
    inbox_dir: Path,
    get_mandant_fn: Callable,
    mandant_dirs_fn: Callable,
    imap_port: int = 993,
    mark_seen: bool = True,
) -> dict:
    """Pollt die IMAP-Inbox und speichert unterstützte Anhänge in die richtigen Mandanten-Ordner.

    Returns dict: {saved, skipped, errors, emails_processed, details}
    """
    result: dict = {"saved": 0, "skipped": 0, "errors": 0, "emails_processed": 0, "details": []}

    if not imap_user or not imap_password:
        result["errors"] += 1
        result["details"].append({"error": "IMAP_USER oder IMAP_PASSWORD nicht konfiguriert"})
        return result

    try:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port)
        conn.login(imap_user, imap_password)
        conn.select("INBOX")
    except Exception as exc:
        logger.exception("IMAP-Login fehlgeschlagen: %s", exc)
        result["errors"] += 1
        result["details"].append({"error": f"IMAP-Login fehlgeschlagen: {exc}"})
        return result

    try:
        _, msg_nums = conn.search(None, "UNSEEN")
        ids = msg_nums[0].split() if msg_nums[0] else []
        logger.info("IMAP-Poll: %d ungesehene E-Mail(s) gefunden", len(ids))

        for num in ids:
            result["emails_processed"] += 1
            try:
                _, data = conn.fetch(num, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                mandant_id = _find_mandant_id(msg, imap_user)
                m = get_mandant_fn(mandant_id) if mandant_id else None
                target_dir = mandant_dirs_fn(m)["inbox"] if m else inbox_dir

                date_suffix = datetime.now().strftime("%Y-%m-%d")
                target_day = target_dir / date_suffix
                target_day.mkdir(parents=True, exist_ok=True)

                saved_this_mail = 0
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    disposition = part.get("Content-Disposition", "")
                    if not disposition:
                        continue
                    raw_filename = part.get_filename()
                    if not raw_filename:
                        continue
                    filename = _decode_header(raw_filename)
                    ext = Path(filename).suffix.lower()
                    if ext not in SUPPORTED_EXT:
                        result["skipped"] += 1
                        continue

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    target = target_day / filename
                    counter = 1
                    while target.exists():
                        target = target_day / f"{Path(filename).stem}_{counter}{ext}"
                        counter += 1

                    target.write_bytes(payload)
                    result["saved"] += 1
                    saved_this_mail += 1
                    result["details"].append({
                        "file": target.name,
                        "mandant": mandant_id or "global",
                        "path": str(target),
                    })
                    logger.info("Gespeichert: %s → Mandant %s", target.name, mandant_id or "global")

                if mark_seen and saved_this_mail > 0:
                    conn.store(num, "+FLAGS", "\\Seen")

            except Exception as exc:
                logger.exception("Fehler beim Verarbeiten von Mail %s: %s", num, exc)
                result["errors"] += 1
                result["details"].append({"error": str(exc)})

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return result
