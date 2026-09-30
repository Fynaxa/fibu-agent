"""EÜR — Einnahmen-Überschuss-Rechnung (§ 4 Abs. 3 EStG).

Aggregiert Belege aus der DB nach Einnahmen- und Ausgaben-Kategorien
entsprechend der Anlage EÜR. Unterstützt SKR03 und SKR04.
Keine neuen Tabellen nötig — reine Aggregation auf bestehenden Daten.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)


def _d(val) -> Decimal:
    if val is None:
        return Decimal("0")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


# ─── Konten-Mapping SKR03 → EÜR-Kategorien ───────────────

_SKR03_EINNAHMEN: dict[str, list[str]] = {
    "Umsatzerlöse 19% USt":          ["8400", "8401", "8402"],
    "Umsatzerlöse 7% USt":           ["8300", "8301"],
    "Steuerfreie Umsätze":           ["8100", "8120", "8125", "8130"],
    "Sonstige betriebliche Erlöse":  ["8910", "8920", "8900", "8999"],
    "Zinseinnahmen":                 ["8600", "8610"],
    "Veräußerungserlöse Anlagen":    ["8820"],
}

_SKR03_AUSGABEN: dict[str, list[str]] = {
    "Wareneinkauf / Material":              ["3200", "3201", "3400", "3800"],
    "Fremdleistungen":                      ["3100", "3120", "3500"],
    "Personalkosten (Löhne/Gehälter)":     ["4100", "4110", "4120"],
    "Sozialabgaben":                        ["4130", "4138", "4139", "4140"],
    "Miete / Pacht":                        ["4210", "4211", "4212", "4213", "4220"],
    "Raumkosten / Energie / Reinigung":     ["4200", "4230", "4240", "4250", "4260"],
    "Leasing":                              ["4570", "4575"],
    "Fahrzeugkosten":                       ["4520", "4521", "4530", "4540"],
    "Reisekosten":                          ["4660", "4661", "4662", "4670"],
    "Bewirtungskosten":                     ["4650", "4654"],
    "Bürobedarf / Arbeitsmittel":          ["4930", "4940", "4941", "4945"],
    "Porto / Telefon / Internet":           ["4910", "4920", "4921"],
    "Werbung / Marketing":                  ["4600", "4601", "4602"],
    "EDV / Software / Cloud":               ["4964", "4965", "4966", "4985"],
    "GWG / Geringwertige Wirtschaftsgüter": ["0650", "0655", "0670"],
    "Abschreibungen (AfA)":                 ["4830", "4831", "4832", "4855"],
    "Versicherungen":                       ["4360", "4361", "4362"],
    "Buchführung / Steuerberatung":         ["4810", "4815", "4820", "4952", "4955"],
    "Zinsen / Bankspesen":                  ["4970", "4971", "2600", "2609"],
    "Sonstiger Betriebsaufwand":            ["4900", "4950", "4960", "4980", "4999"],
}

_SKR04_EINNAHMEN: dict[str, list[str]] = {
    "Umsatzerlöse 19% USt":          ["4400", "4410"],
    "Umsatzerlöse 7% USt":           ["4300", "4310"],
    "Steuerfreie Umsätze":           ["4100", "4120", "4130"],
    "Sonstige betriebliche Erlöse":  ["4830", "4840"],
    "Zinseinnahmen":                 ["4600", "4610"],
    "Veräußerungserlöse Anlagen":    ["4855"],
}

_SKR04_AUSGABEN: dict[str, list[str]] = {
    "Wareneinkauf / Material":       ["5200", "5400", "5600"],
    "Fremdleistungen":               ["5100", "5900"],
    "Personalkosten (Löhne/Gehälter)": ["6000", "6010", "6020", "6030"],
    "Sozialabgaben":                 ["6110", "6120", "6130"],
    "Miete / Pacht":                 ["6310", "6311", "6320"],
    "Leasing":                       ["6565"],
    "Fahrzeugkosten":                ["6530", "6540", "6560"],
    "Reisekosten":                   ["6650", "6660", "6670"],
    "Bewirtungskosten":              ["6640", "6641"],
    "Bürobedarf / Arbeitsmittel":    ["6815", "6820"],
    "Porto / Telefon / Internet":    ["6800", "6805", "6810"],
    "Werbung / Marketing":           ["6600", "6601"],
    "Abschreibungen (AfA)":          ["6200", "6220", "6260"],
    "Versicherungen":                ["6400", "6401"],
    "Buchführung / Beratung":        ["6825", "6830"],
    "Zinsen / Bankspesen":           ["7300", "7310", "6855"],
    "Sonstiger Betriebsaufwand":     ["6840", "6850", "6870", "6890"],
}


def _konto_zu_kategorie(konto: str, mapping: dict[str, list[str]]) -> str | None:
    """Findet die EÜR-Kategorie für ein Konto."""
    konto_clean = str(konto).strip()[:4]
    for kategorie, konten in mapping.items():
        if konto_clean in konten:
            return kategorie
    return None


def erstelle_euer(
    belege: list[dict],
    jahr: int,
    kontenrahmen: str = "SKR03",
    mandant_id: str | None = None,
) -> dict:
    """Erstellt die EÜR aus einer Liste von Belegen.

    Nur exportierte Belege werden einbezogen. Einnahmen = haben_konto
    liegt in Erlöskonten. Ausgaben = soll_konto liegt in Aufwandskonten.
    """
    skr = kontenrahmen.upper()
    einnahmen_map = _SKR03_EINNAHMEN if skr == "SKR03" else _SKR04_EINNAHMEN
    ausgaben_map  = _SKR03_AUSGABEN  if skr == "SKR03" else _SKR04_AUSGABEN

    einnahmen: dict[str, Decimal] = {k: Decimal("0") for k in einnahmen_map}
    ausgaben:  dict[str, Decimal] = {k: Decimal("0") for k in ausgaben_map}
    nicht_zugeordnet_e = Decimal("0")
    nicht_zugeordnet_a = Decimal("0")
    belege_count = 0

    jahres_str = str(jahr)

    for b in belege:
        if b.get("status") not in ("exportiert", "exportiert_datev"):
            continue
        # Jahresfilter nach Belegdatum
        beleg_datum = str(b.get("belegdatum") or "")
        if beleg_datum and not beleg_datum.startswith(jahres_str):
            continue

        brutto = _d(b.get("bruttobetrag"))
        netto  = _d(b.get("nettobetrag")) or brutto
        soll   = str(b.get("soll_konto") or "")
        haben  = str(b.get("haben_konto") or "")

        # Einnahme: haben_konto in Erlösen
        kat_e = _konto_zu_kategorie(haben, einnahmen_map)
        if kat_e:
            einnahmen[kat_e] += netto
            belege_count += 1
            continue

        # Ausgabe: soll_konto in Aufwendungen
        kat_a = _konto_zu_kategorie(soll, ausgaben_map)
        if kat_a:
            ausgaben[kat_a] += netto
            belege_count += 1
        else:
            # Heuristik: 4xxx/5xxx/6xxx/7xxx-Konten → Aufwand
            soll_nr = int(soll[:1]) if soll and soll[0].isdigit() else -1
            haben_nr = int(haben[:1]) if haben and haben[0].isdigit() else -1
            if skr == "SKR03" and soll_nr in (2, 3, 4):
                nicht_zugeordnet_a += netto
                belege_count += 1
            elif skr == "SKR04" and soll_nr in (5, 6, 7):
                nicht_zugeordnet_a += netto
                belege_count += 1
            elif skr == "SKR03" and haben_nr == 8:
                nicht_zugeordnet_e += netto
                belege_count += 1
            elif skr == "SKR04" and haben_nr == 4:
                nicht_zugeordnet_e += netto
                belege_count += 1

    # Runden + leere Kategorien entfernen
    def _round_map(d: dict[str, Decimal]) -> list[dict]:
        result = []
        for k, v in d.items():
            if v != 0:
                result.append({
                    "kategorie": k,
                    "betrag": float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                })
        return result

    einnahmen_zeilen = _round_map(einnahmen)
    if nicht_zugeordnet_e > 0:
        einnahmen_zeilen.append({"kategorie": "Nicht zugeordnet", "betrag": float(nicht_zugeordnet_e)})

    ausgaben_zeilen = _round_map(ausgaben)
    if nicht_zugeordnet_a > 0:
        ausgaben_zeilen.append({"kategorie": "Nicht zugeordnet", "betrag": float(nicht_zugeordnet_a)})

    gesamt_einnahmen = sum(z["betrag"] for z in einnahmen_zeilen)
    gesamt_ausgaben  = sum(z["betrag"] for z in ausgaben_zeilen)
    gewinn_verlust   = round(gesamt_einnahmen - gesamt_ausgaben, 2)

    return {
        "jahr":               jahr,
        "kontenrahmen":       kontenrahmen,
        "mandant_id":         mandant_id,
        "belege_count":       belege_count,
        "einnahmen":          einnahmen_zeilen,
        "ausgaben":           ausgaben_zeilen,
        "gesamt_einnahmen":   round(gesamt_einnahmen, 2),
        "gesamt_ausgaben":    round(gesamt_ausgaben, 2),
        "gewinn_verlust":     gewinn_verlust,
        "erstellt_am":        datetime.now().isoformat(),
    }


def erstelle_euer_aus_db(
    mandant_id: str | None = None,
    jahr: int | None = None,
    kontenrahmen: str = "SKR03",
) -> dict:
    """Lädt Belege direkt aus der DB und erstellt die EÜR."""
    from tools.db import get_db

    if jahr is None:
        jahr = date.today().year

    datum_von = f"{jahr}-01-01"
    datum_bis = f"{jahr}-12-31"

    query = "SELECT * FROM belege WHERE status IN ('exportiert', 'exportiert_datev')"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    query += " AND belegdatum >= ? AND belegdatum <= ?"
    params += [datum_von, datum_bis]

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        belege = [dict(r) for r in rows]

    if not belege and mandant_id:
        # Fallback: ohne Datumsfilter (falls Belegdaten fehlen)
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM belege WHERE status IN ('exportiert','exportiert_datev') AND mandant_id = ?",
                (mandant_id,)
            ).fetchall()
            belege = [dict(r) for r in rows]

    # Kontenrahmen aus Mandant holen wenn nicht explizit angegeben
    if kontenrahmen == "SKR03" and mandant_id:
        from tools.config import get_mandant
        m = get_mandant(mandant_id)
        if m:
            kontenrahmen = m.get("kontenrahmen", "SKR03")

    logger.info("EÜR %d: %d Belege (Mandant: %s, KR: %s)",
                jahr, len(belege), mandant_id or "alle", kontenrahmen)

    return erstelle_euer(belege, jahr, kontenrahmen, mandant_id)


def format_euer_text(euer: dict) -> str:
    """Formatiert die EÜR als lesbaren Text."""
    lines = [
        "═" * 55,
        f"  EINNAHMEN-ÜBERSCHUSS-RECHNUNG — {euer['jahr']}",
        f"  Kontenrahmen: {euer['kontenrahmen']}  |  {euer['belege_count']} Belege",
        "═" * 55,
        "",
        "  BETRIEBSEINNAHMEN",
        "  " + "─" * 50,
    ]

    for z in euer["einnahmen"]:
        lines.append(f"  {z['kategorie']:<42}  {z['betrag']:>9,.2f} €")

    lines += [
        "  " + "─" * 50,
        f"  {'GESAMT EINNAHMEN':<42}  {euer['gesamt_einnahmen']:>9,.2f} €",
        "",
        "  BETRIEBSAUSGABEN",
        "  " + "─" * 50,
    ]

    for z in euer["ausgaben"]:
        lines.append(f"  {z['kategorie']:<42}  {z['betrag']:>9,.2f} €")

    lines += [
        "  " + "─" * 50,
        f"  {'GESAMT AUSGABEN':<42}  {euer['gesamt_ausgaben']:>9,.2f} €",
        "",
        "═" * 55,
    ]

    pref = "GEWINN" if euer["gewinn_verlust"] >= 0 else "VERLUST"
    lines.append(f"  {pref + ' (§ 4 Abs. 3 EStG)':<42}  {abs(euer['gewinn_verlust']):>9,.2f} €")
    lines.append("═" * 55)

    return "\n".join(lines)
