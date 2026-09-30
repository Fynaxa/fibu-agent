"""UVA-Vorbereitung: Gruppiert Belege nach Steuerschlüssel für die Umsatzsteuervoranmeldung.

Ausgabe kann direkt als Grundlage für die monatliche/quartalsweise UVA dienen.
Unterstützt SKR03 und SKR04, mandant-isoliert.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

# Steuerschlüssel → Beschreibung + MwSt-Satz
STEUER_MAP = {
    "9": {"bezeichnung": "19% Vorsteuer", "satz": Decimal("0.19")},
    "8": {"bezeichnung": "7% Vorsteuer", "satz": Decimal("0.07")},
    "0": {"bezeichnung": "Steuerfrei / ohne Ausweis", "satz": Decimal("0")},
    "21": {"bezeichnung": "§13b Reverse Charge (Steuerschuld Leistungsempfänger)", "satz": None},
}


def _d(val) -> Decimal:
    """Sichere Umwandlung in Decimal für Steuerberechnung."""
    if val is None:
        return Decimal("0")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def erstelle_uva_vorbereitung(
    belege: list[dict],
    zeitraum_von: str | None = None,
    zeitraum_bis: str | None = None,
    mandant_id: str | None = None,
) -> dict:
    """Aggregiert Belege nach Steuerschlüssel für die UVA.

    Args:
        belege: Liste von Beleg-Dicts (aus DB oder Pipeline)
        zeitraum_von: ISO-Datum YYYY-MM-DD (optional, für Anzeige)
        zeitraum_bis: ISO-Datum YYYY-MM-DD (optional, für Anzeige)
        mandant_id: Mandanten-Filter (nur für Anzeige, Filterung vorher)

    Returns:
        dict mit 'zeilen', 'gesamt_netto', 'gesamt_vst', 'zeitraum', 'belege_count'
    """
    gruppen: dict[str, dict] = {}

    for b in belege:
        # Nur exportierte Belege (fertig kontiert) einbeziehen
        if b.get("status") not in ("exportiert", "exportiert_datev"):
            continue

        sk = str(b.get("steuerschluessel") or "0").strip()
        netto = _d(b.get("nettobetrag"))
        mwst_betrag = _d(b.get("mwst_betrag"))
        brutto = _d(b.get("bruttobetrag"))

        # Netto aus Brutto ableiten wenn nicht vorhanden
        if netto == 0 and brutto != 0 and sk in STEUER_MAP:
            info = STEUER_MAP[sk]
            if info["satz"] and info["satz"] > 0:
                netto = (brutto / (1 + info["satz"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                mwst_betrag = brutto - netto
            else:
                netto = brutto

        if sk not in gruppen:
            gruppen[sk] = {
                "steuerschluessel": sk,
                "bezeichnung": STEUER_MAP.get(sk, {}).get("bezeichnung", f"Schlüssel {sk}"),
                "netto_summe": Decimal("0"),
                "vst_summe": Decimal("0"),
                "belege_count": 0,
            }

        gruppen[sk]["netto_summe"] += netto
        gruppen[sk]["vst_summe"] += mwst_betrag
        gruppen[sk]["belege_count"] += 1

    # Runden und sortieren (9 → 8 → 21 → 0 → Rest)
    sort_order = {"9": 0, "8": 1, "21": 2, "0": 3}
    zeilen = sorted(
        gruppen.values(),
        key=lambda g: (sort_order.get(g["steuerschluessel"], 99), g["steuerschluessel"]),
    )
    for z in zeilen:
        z["netto_summe"] = float(z["netto_summe"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        z["vst_summe"] = float(z["vst_summe"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    gesamt_netto = sum(z["netto_summe"] for z in zeilen)
    gesamt_vst = sum(z["vst_summe"] for z in zeilen if z["steuerschluessel"] != "21")

    return {
        "zeilen": zeilen,
        "gesamt_netto": round(gesamt_netto, 2),
        "gesamt_vst": round(gesamt_vst, 2),
        "belege_count": sum(z["belege_count"] for z in zeilen),
        "zeitraum_von": zeitraum_von,
        "zeitraum_bis": zeitraum_bis,
        "mandant_id": mandant_id,
        "erstellt_am": datetime.now().isoformat(),
    }


def format_uva_text(uva: dict) -> str:
    """Formatiert die UVA-Vorbereitung als lesbaren Text für den Report."""
    lines = ["═" * 50]
    lines.append("  UVA-VORBEREITUNG (Umsatzsteuervoranmeldung)")
    if uva.get("zeitraum_von") and uva.get("zeitraum_bis"):
        lines.append(f"  Zeitraum: {uva['zeitraum_von']} bis {uva['zeitraum_bis']}")
    if uva.get("mandant_id"):
        lines.append(f"  Mandant: {uva['mandant_id']}")
    lines.append("═" * 50)
    lines.append("")

    for z in uva["zeilen"]:
        sk = z["steuerschluessel"]
        netto = f"{z['netto_summe']:>12,.2f} €"
        vst = f"{z['vst_summe']:>12,.2f} €" if sk != "21" else "  (Empfänger schuldet Steuer)"
        lines.append(f"  SK {sk:>2} | {z['bezeichnung']:<42}")
        lines.append(f"         Netto: {netto}  |  VSt: {vst}")
        lines.append(f"         ({z['belege_count']} Belege)")
        lines.append("")

    lines.append("─" * 50)
    lines.append(f"  Gesamt Netto (Vorsteuer-Basis): {uva['gesamt_netto']:>12,.2f} €")
    lines.append(f"  Gesamt Vorsteuer (abziehbar):   {uva['gesamt_vst']:>12,.2f} €")
    lines.append("═" * 50)

    return "\n".join(lines)


def erstelle_uva_aus_db(
    mandant_id: str | None = None,
    datum_von: str | None = None,
    datum_bis: str | None = None,
) -> dict:
    """Lädt Belege direkt aus der DB und erstellt die UVA-Vorbereitung.

    datum_von / datum_bis: YYYY-MM-DD Format für Zeitraumfilterung nach Belegdatum.
    """
    from tools.db import get_db

    query = "SELECT * FROM belege WHERE status IN ('exportiert', 'exportiert_datev')"
    params: list = []

    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if datum_von:
        query += " AND belegdatum >= ?"
        params.append(datum_von)
    if datum_bis:
        query += " AND belegdatum <= ?"
        params.append(datum_bis)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        belege = [dict(r) for r in rows]

    logger.info("UVA: %d Belege geladen (Mandant: %s, %s bis %s)",
                len(belege), mandant_id or "alle", datum_von or "?", datum_bis or "?")

    return erstelle_uva_vorbereitung(
        belege,
        zeitraum_von=datum_von,
        zeitraum_bis=datum_bis,
        mandant_id=mandant_id,
    )
