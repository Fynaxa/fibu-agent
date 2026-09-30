"""DATEV Buchungsstapel CSV-Validierung.

Prüft, ob eine exportierte CSV-Datei den DATEV-EXTF-Spezifikationen entspricht,
bevor sie an eine Steuerkanzlei / DATEV-Software übergeben wird.
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Gültige Soll/Haben-Kennzeichen
VALID_SH_KZ = {"S", "H"}

# Gültige Währungscodes (häufigste)
VALID_WKZ = {"EUR", "USD", "GBP", "CHF"}

# DATEV-Kontonummern: 4-stellig (SKR03/04) oder 5-stellig (erweitert)
KONTO_PATTERN = re.compile(r"^\d{4,5}$")

# Belegdatum: TTMM (4 Ziffern)
DATUM_PATTERN = re.compile(r"^\d{4}$")

# BU-Schlüssel: 1-2 Ziffern oder leer
BU_PATTERN = re.compile(r"^(\d{1,2})?$")

# Betrag: deutsches Format mit Komma (z.B. "1.234,56" oder "47,50")
BETRAG_PATTERN = re.compile(r"^[\d.]+,\d{2}$")


def validate_datev_csv(path: Path) -> dict:
    """Validiert eine DATEV-EXTF-CSV-Datei.

    Returns:
        dict mit {valid: bool, fehler: list[str], warnungen: list[str], zeilen: int}
    """
    path = Path(path)
    fehler: list[str] = []
    warnungen: list[str] = []
    zeilen = 0

    if not path.exists():
        return {"valid": False, "fehler": ["Datei nicht gefunden"], "warnungen": [], "zeilen": 0}

    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return {"valid": False, "fehler": ["Encoding-Fehler: Datei ist nicht UTF-8-sig"], "warnungen": [], "zeilen": 0}

    lines = content.strip().split("\n")
    if len(lines) < 3:
        fehler.append("Datei hat weniger als 3 Zeilen (Header + Spaltenzeile + Daten erwartet)")
        return {"valid": False, "fehler": fehler, "warnungen": [], "zeilen": 0}

    # --- Zeile 1: EXTF-Headerzeile prüfen ---
    header_line = lines[0]
    if not header_line.startswith('"EXTF"'):
        fehler.append(f"Zeile 1: Muss mit '\"EXTF\"' beginnen, gefunden: {header_line[:30]}")

    header_parts = header_line.split(";")
    # Versionsnummer prüfen (700 = aktuelles Format)
    if len(header_parts) >= 2:
        version = header_parts[1].strip()
        if version != "700":
            warnungen.append(f"EXTF-Version {version} statt erwartet 700")
    # Format-Kategorie 21 = Buchungsstapel
    if len(header_parts) >= 3 and header_parts[2].strip() != "21":
        warnungen.append(f"EXTF-Format-Kategorie {header_parts[2]} statt erwartet 21 (Buchungsstapel)")
    # Header muss mindestens 22 Felder haben (DATEV v700-Spezifikation)
    if len(header_parts) < 22:
        fehler.append(f"EXTF-Header hat nur {len(header_parts)} Felder, mindestens 22 erwartet (DATEV v700)")

    # --- Zeile 2: Leerzeile (Trenner) ---
    if lines[1].strip():
        warnungen.append("Zeile 2 sollte leer sein (DATEV-Trenner)")

    # --- Zeile 3: Spaltenüberschriften ---
    expected_first_col = "Umsatz (ohne Soll/Haben-Kz)"
    if expected_first_col not in lines[2]:
        fehler.append(f"Zeile 3: Spaltenüberschrift erwartet, erste Spalte sollte '{expected_first_col}' sein")

    # --- Datenzeilen ab Zeile 4 ---
    if len(lines) <= 3:
        warnungen.append("Keine Buchungszeilen in der Datei")
        return {"valid": len(fehler) == 0, "fehler": fehler, "warnungen": warnungen, "zeilen": 0}

    reader = csv.reader(lines[3:], delimiter=";")
    for i, row in enumerate(reader, start=4):
        if not row or all(c.strip() == "" for c in row):
            continue  # Leerzeile ignorieren
        zeilen += 1

        if len(row) < 9:
            fehler.append(f"Zeile {i}: Nur {len(row)} Spalten, mindestens 9 erwartet")
            continue

        betrag, sh_kz, wkz, konto, gegenkonto, bu, datum, belegfeld, buchungstext = (
            row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip(),
            row[4].strip(), row[5].strip(), row[6].strip(),
            row[7].strip() if len(row) > 7 else "",
            row[8].strip() if len(row) > 8 else "",
        )

        # Betrag
        if not BETRAG_PATTERN.match(betrag):
            fehler.append(f"Zeile {i}: Ungültiger Betrag '{betrag}' (erwartet z.B. '100,00')")

        # Betrag > 0
        try:
            betrag_float = float(betrag.replace(".", "").replace(",", "."))
            if betrag_float <= 0:
                fehler.append(f"Zeile {i}: Betrag {betrag} ist <= 0")
        except ValueError:
            pass  # Bereits oben gefangen

        # Soll/Haben
        if sh_kz not in VALID_SH_KZ:
            fehler.append(f"Zeile {i}: Ungültiges S/H-Kennzeichen '{sh_kz}' (erwartet S oder H)")

        # Währung
        if wkz and wkz not in VALID_WKZ:
            warnungen.append(f"Zeile {i}: Unbekannte Währung '{wkz}'")

        # Konto
        if not KONTO_PATTERN.match(konto):
            fehler.append(f"Zeile {i}: Ungültige Kontonummer '{konto}' (4-5 Ziffern erwartet)")

        # Gegenkonto
        if not KONTO_PATTERN.match(gegenkonto):
            fehler.append(f"Zeile {i}: Ungültige Gegenkontonummer '{gegenkonto}' (4-5 Ziffern erwartet)")

        # BU-Schlüssel
        if not BU_PATTERN.match(bu):
            fehler.append(f"Zeile {i}: Ungültiger BU-Schlüssel '{bu}'")

        # Belegdatum
        if datum and not DATUM_PATTERN.match(datum):
            fehler.append(f"Zeile {i}: Ungültiges Belegdatum '{datum}' (TTMM erwartet)")

        if datum and DATUM_PATTERN.match(datum):
            tag = int(datum[:2])
            monat = int(datum[2:])
            if tag < 1 or tag > 31:
                fehler.append(f"Zeile {i}: Tag {tag} im Belegdatum ungültig")
            if monat < 1 or monat > 12:
                fehler.append(f"Zeile {i}: Monat {monat} im Belegdatum ungültig")

        # Buchungstext max 60 Zeichen
        if len(buchungstext) > 60:
            warnungen.append(f"Zeile {i}: Buchungstext länger als 60 Zeichen ({len(buchungstext)})")

    is_valid = len(fehler) == 0

    if is_valid:
        logger.info("DATEV-Validierung OK: %d Buchungszeilen in %s", zeilen, path.name)
    else:
        logger.warning("DATEV-Validierung fehlgeschlagen: %d Fehler in %s", len(fehler), path.name)

    return {
        "valid": is_valid,
        "fehler": fehler,
        "warnungen": warnungen,
        "zeilen": zeilen,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Verwendung: python -m tools.datev_validate <datei.csv>")
        sys.exit(1)
    result = validate_datev_csv(Path(sys.argv[1]))
    print(f"Gültig: {result['valid']}")
    print(f"Zeilen: {result['zeilen']}")
    if result["fehler"]:
        print(f"\nFehler ({len(result['fehler'])}):")
        for f in result["fehler"]:
            print(f"  ✗ {f}")
    if result["warnungen"]:
        print(f"\nWarnungen ({len(result['warnungen'])}):")
        for w in result["warnungen"]:
            print(f"  ⚠ {w}")
