"""Verschlüsselung für sensible Belegdaten (DSGVO Art. 32).

Nutzt Fernet (AES-128-CBC) aus der cryptography-Bibliothek.
Der Schlüssel wird aus einem Umgebungsvariable ENCRYPTION_KEY geladen
oder beim ersten Start automatisch generiert und in .env geschrieben.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY: bytes | None = None


def _get_or_create_key() -> bytes:
    """Lädt oder erstellt den Verschlüsselungsschlüssel."""
    global _KEY
    if _KEY:
        return _KEY

    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        _KEY = env_key.encode()
        return _KEY

    # Schlüssel generieren
    from cryptography.fernet import Fernet
    _KEY = Fernet.generate_key()

    # In .env persistieren
    from tools.config import ROOT
    env_path = ROOT / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "ENCRYPTION_KEY" not in content:
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nENCRYPTION_KEY={_KEY.decode()}\n")
            logger.info("Verschlüsselungsschlüssel generiert und in .env gespeichert")
    else:
        logger.warning("Kein .env gefunden — Schlüssel nur im Speicher")

    return _KEY


def encrypt(data: str) -> str:
    """Verschlüsselt einen String. Gibt Base64-encoded Ciphertext zurück."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_or_create_key())
    return f.encrypt(data.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Entschlüsselt einen Fernet-Token zurück zum Klartext."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_or_create_key())
    return f.decrypt(token.encode("ascii")).decode("utf-8")


def encrypt_file(path: Path) -> Path:
    """Verschlüsselt eine Datei in-place. Fügt .enc Suffix hinzu."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_or_create_key())
    data = Path(path).read_bytes()
    encrypted = f.encrypt(data)
    enc_path = Path(str(path) + ".enc")
    enc_path.write_bytes(encrypted)
    Path(path).unlink()  # Original löschen
    logger.info("Verschlüsselt: %s → %s", path.name, enc_path.name)
    return enc_path


def decrypt_file(enc_path: Path) -> Path:
    """Entschlüsselt eine .enc Datei."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_or_create_key())
    data = Path(enc_path).read_bytes()
    decrypted = f.decrypt(data)
    orig_path = Path(str(enc_path).removesuffix(".enc"))
    orig_path.write_bytes(decrypted)
    return orig_path


# Sensible Felder die in der DB verschlüsselt werden sollten
SENSITIVE_FIELDS = {"iban", "email", "telefon", "ansprechpartner"}


def encrypt_sensitive(beleg: dict) -> dict:
    """Verschlüsselt sensible Felder in einem Beleg-Dict."""
    result = dict(beleg)
    for field in SENSITIVE_FIELDS:
        value = result.get(field)
        if value and isinstance(value, str) and not value.startswith("gAAAAA"):  # Bereits verschlüsselt
            result[field] = encrypt(value)
    return result


def decrypt_sensitive(beleg: dict) -> dict:
    """Entschlüsselt sensible Felder in einem Beleg-Dict."""
    result = dict(beleg)
    for field in SENSITIVE_FIELDS:
        value = result.get(field)
        if value and isinstance(value, str) and value.startswith("gAAAAA"):
            try:
                result[field] = decrypt(value)
            except Exception:
                pass  # Kann nicht entschlüsselt werden — behalten
    return result
