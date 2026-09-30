"""DATEV Buchungsstapel CSV-Export."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from tools.config import DATEV_BERATER_NR, DATEV_MANDANT_NR, OUTBOX_DIR

logger = logging.getLogger(__name__)

DATEV_HEADER = [
    "Umsatz (ohne Soll/Haben-Kz)",
    "Soll/Haben-Kennzeichen",
    "WKZ Umsatz",
    "Konto",
    "Gegenkonto (ohne BU-Schlüssel)",
    "BU-Schlüssel",
    "Belegdatum",
    "Belegfeld 1",
    "Buchungstext",
]

# DATEV Belegfeld 1 ist auf 12 Zeichen begrenzt (Fix 9)
BELEGFELD_MAX = 12


def _format_datum(iso_datum: str | None) -> str:
    """YYYY-MM-DD → TTMM (DATEV-Format)."""
    if not iso_datum:
        return ""
    try:
        dt = datetime.strptime(iso_datum, "%Y-%m-%d")
        return dt.strftime("%d%m")
    except ValueError:
        return ""


def _format_betrag(betrag: float | None) -> str:
    """Float → deutsches Dezimalformat (Komma, immer positiv)."""
    if betrag is None:
        return "0,00"
    return f"{abs(betrag):,.2f}".replace(",", "X").replace(".", ",").replace("X", "")


def _sh_kennzeichen(brutto: float) -> str:
    """Fix 1: Gutschriften/Storno bekommen 'H', normale Buchungen 'S'."""
    return "H" if brutto < 0 else "S"


def _bu_schluessel(beleg: dict) -> str:
    """Fix 2 + 11: Korrekten BU-Schlüssel ableiten.

    - Reverse Charge EU (§13b): BU 21
    - Reverse Charge Drittland: BU 84
    - Bewirtungskosten (4650): BU 57 (30% nicht abzugsfähig)
    - Sonst: Steuerschlüssel (9/8/0)
    """
    if beleg.get("reverse_charge"):
        # EU-Lieferant (IBAN beginnt mit EU-Ländercode oder Hinweis im Beleg)
        iban = (beleg.get("iban") or "").upper()
        lieferant_text = (beleg.get("lieferant") or "") + (beleg.get("verwendungszweck") or "")
        eu_laender = ("IE", "FR", "NL", "BE", "AT", "IT", "ES", "PL", "SE", "FI",
                      "DK", "PT", "CZ", "HU", "RO", "SK", "SI", "HR", "BG", "EE",
                      "LV", "LT", "LU", "CY", "MT", "GR")
        is_eu = any(iban.startswith(cc) for cc in eu_laender)
        # Auch EU-Länder im Lieferanten-Text erkennen
        if not is_eu:
            eu_keywords = ("ireland", "irland", "france", "frankreich", "netherlands",
                           "niederlande", "belgium", "belgien", "luxembourg", "luxemburg")
            is_eu = any(kw in lieferant_text.lower() for kw in eu_keywords)
        return "21" if is_eu else "84"

    if beleg.get("soll_konto") == "4650":
        return "57"  # Fix 11: Bewirtungskosten 70% abzugsfähig

    return str(beleg.get("steuerschluessel") or "")


def _beleg_rows(beleg: dict) -> list[list]:
    """Fix 4: Erzeugt eine oder mehrere CSV-Zeilen pro Beleg.

    Bei gemischter MwSt (7% + 19%) werden zwei Zeilen erzeugt,
    sofern mwst_positionen im Beleg vorhanden sind.
    """
    rows = []
    belegfeld = str(beleg.get("rechnungsnummer") or "")[:BELEGFELD_MAX]  # Fix 9
    buchungstext = (
        beleg.get("buchungstext") or beleg.get("verwendungszweck") or beleg.get("lieferant") or ""
    )[:60]
    datum = _format_datum(beleg.get("belegdatum"))
    bu = _bu_schluessel(beleg)
    brutto = beleg.get("bruttobetrag") or 0
    sh = _sh_kennzeichen(brutto)

    # Fix 3: Fremdwährung — EUR-Gegenwert bevorzugen wenn vorhanden
    waehrung = beleg.get("waehrung", "EUR")
    if waehrung != "EUR" and beleg.get("eur_betrag"):
        # Buchung in EUR mit Originalbetrag im Buchungstext
        betrag_fuer_export = beleg["eur_betrag"]
        buchungstext = f"{buchungstext} ({_format_betrag(brutto)} {waehrung})"[:60]
        waehrung_export = "EUR"
    else:
        betrag_fuer_export = brutto
        waehrung_export = waehrung

    soll_konto = beleg.get("soll_konto", "")
    haben_konto = beleg.get("haben_konto", "1200")

    # Fix 4: Gemischte MwSt → mehrere Zeilen
    mwst_positionen = beleg.get("mwst_positionen")
    if beleg.get("mwst_gemischt") and mwst_positionen:
        for pos in mwst_positionen:
            pos_brutto = (pos.get("netto") or 0) + (pos.get("mwst") or 0)
            pos_bu = str(pos.get("schluessel") or bu)
            rows.append([
                _format_betrag(pos_brutto),
                sh,
                waehrung_export,
                soll_konto,
                haben_konto,
                pos_bu,
                datum,
                belegfeld,
                buchungstext,
            ])
        return rows

    # Normalfall: eine Zeile
    rows.append([
        _format_betrag(betrag_fuer_export),
        sh,
        waehrung_export,
        soll_konto,
        haben_konto,
        bu,
        datum,
        belegfeld,
        buchungstext,
    ])
    return rows


def export_buchungsstapel(
    belege: list[dict],
    dateiname: str | None = None,
    output_dir: Path | None = None,
    berater_nr: str | None = None,
    mandant_nr: str | None = None,
) -> Path:
    """Schreibt DATEV-CSV für eine Liste von validierten Belegen."""
    if not dateiname:
        dateiname = f"EXTF_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    out = Path(output_dir) if output_dir else OUTBOX_DIR
    out.mkdir(parents=True, exist_ok=True)
    output = out / dateiname
    berater = berater_nr or DATEV_BERATER_NR
    mandant = mandant_nr or DATEV_MANDANT_NR
    rows_written = 0

    daten = [b.get("belegdatum") for b in belege if b.get("belegdatum")]
    if daten:
        datum_von = min(daten).replace("-", "")
        datum_bis = max(daten).replace("-", "")
    else:
        heute = datetime.now().strftime("%Y%m%d")
        datum_von = datum_bis = heute

    wj_beginn = datum_von[:4] + "0101"
    now_str = datetime.now().strftime("%Y%m%d%H%M%S")

    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        header_fields = [
            '"EXTF"', "700", "21", '"Buchungsstapel"', "12",
            now_str, "", '"RE"', '"FiBu-Agent"', "",
            berater or "", mandant or "", wj_beginn, "4", datum_von, datum_bis,
            '"FiBu-Agent Export"', "", "1", "",
            "0", '"EUR"', "", "", "", "", "", "", "",
        ]
        f.write(";".join(header_fields) + "\n")
        f.write("\n")

        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(DATEV_HEADER)

        for beleg in belege:
            for row in _beleg_rows(beleg):
                writer.writerow(row)
                rows_written += 1

    logger.info("DATEV-Export: %d Buchungszeilen → %s", rows_written, output)

    from tools.datev_validate import validate_datev_csv
    validation = validate_datev_csv(output)
    if not validation["valid"]:
        logger.error("DATEV-Export Validierung fehlgeschlagen: %s", validation["fehler"])
    if validation["warnungen"]:
        logger.warning("DATEV-Export Warnungen: %s", validation["warnungen"])

    return output


if __name__ == "__main__":
    demo = [
        {
            "bruttobetrag": 100.00, "waehrung": "EUR", "soll_konto": "4920",
            "haben_konto": "1200", "steuerschluessel": "9", "belegdatum": "2026-04-08",
            "rechnungsnummer": "RE-2026-4471823", "buchungstext": "Vodafone Mobilfunk 04/2026",
        },
        {
            "bruttobetrag": -29.75, "waehrung": "EUR", "soll_konto": "4900",
            "haben_konto": "1200", "steuerschluessel": "9", "belegdatum": "2026-04-10",
            "rechnungsnummer": "GS-2026-0041", "buchungstext": "Gutschrift Vodafone",
        },
        {
            "bruttobetrag": 1500.00, "waehrung": "EUR", "soll_konto": "4964",
            "haben_konto": "1200", "steuerschluessel": "0", "belegdatum": "2026-04-01",
            "rechnungsnummer": "SF-DE-2026-48291", "buchungstext": "Salesforce RC",
            "reverse_charge": True, "iban": "IE29AIBK93104715203015",
        },
    ]
    path = export_buchungsstapel(demo)
    print(path.read_text(encoding="utf-8-sig"))
