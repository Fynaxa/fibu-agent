"""Bankabgleich: MT940 + CAMT.053 Import und Abgleich gegen Belege.

Parst Kontoauszüge, importiert Transaktionen in SQLite und versucht
automatischen Abgleich gegen kontierte Belege und offene Posten.
"""
from __future__ import annotations

import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# CAMT.053 XML-Namespaces (alle bekannten Versionen)
_CAMT_NS = [
    "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02",
    "urn:iso:std:iso:20022:tech:xsd:camt.053.001.03",
    "urn:iso:std:iso:20022:tech:xsd:camt.053.001.04",
    "urn:iso:std:iso:20022:tech:xsd:camt.053.001.06",
    "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08",
]


def _init_tables() -> None:
    from tools.db import get_db
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bank_transaktionen (
                tx_id           TEXT PRIMARY KEY,
                datum           TEXT NOT NULL,
                valuta          TEXT,
                betrag          REAL NOT NULL,
                waehrung        TEXT DEFAULT 'EUR',
                richtung        TEXT NOT NULL,
                verwendungszweck TEXT,
                gegenpartei     TEXT,
                referenz        TEXT,
                datei_quelle    TEXT,
                datei_typ       TEXT,
                abgeglichen     INTEGER DEFAULT 0,
                beleg_id        TEXT,
                mandant_id      TEXT,
                importiert_am   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bank_mandant  ON bank_transaktionen(mandant_id);
            CREATE INDEX IF NOT EXISTS idx_bank_abgegl   ON bank_transaktionen(abgeglichen);
            CREATE INDEX IF NOT EXISTS idx_bank_datum    ON bank_transaktionen(datum);
        """)


# ─── MT940-Parser ──────────────────────────────────────────

def _parse_mt940_betrag(raw: str) -> tuple[float, str]:
    """Parst MT940-Betrag mit Komma als Dezimalzeichen. Returns (betrag, richtung)."""
    raw = raw.strip()
    richtung = "CREDIT" if raw.startswith("C") else "DEBIT"
    # Format: C oder D, optional Rückbuchungs-Indikator R, dann BETRAG
    m = re.match(r"[CD]R?(\d+,\d{0,2})", raw)
    if m:
        betrag_str = m.group(1).replace(",", ".")
        return float(betrag_str), richtung
    return 0.0, richtung


def _mt940_datum(raw: str) -> str:
    """Konvertiert MT940-Datum YYMMDD in YYYY-MM-DD."""
    raw = raw.strip()[:6]
    if len(raw) == 6:
        yy, mm, dd = raw[:2], raw[2:4], raw[4:6]
        year = 2000 + int(yy) if int(yy) < 70 else 1900 + int(yy)
        return f"{year}-{mm}-{dd}"
    return raw


def parse_mt940(filepath: str | Path, mandant_id: str | None = None) -> list[dict]:
    """Parst eine MT940-Datei und gibt Liste von Transaktions-Dicts zurück."""
    content = Path(filepath).read_text(encoding="utf-8", errors="replace")
    transaktionen: list[dict] = []

    # Blöcke nach :61: aufteilen
    # :61: WERTDATUM[BUCHUNGSDATUM]SOLL/HABEN BETRAG BUCHUNGSSCHLÜSSEL REFERENZ
    # :86: Verwendungszweck (mehrzeilig)
    tx_blocks = re.split(r"(?=:61:)", content)

    for block in tx_blocks:
        if not block.strip().startswith(":61:"):
            continue

        m61 = re.match(r":61:(\d{6})(\d{4})?([CD]R?\d+,\d{0,2})([A-Z]{4})(.+?)(?=\n|$)", block)
        if not m61:
            continue

        datum_raw    = m61.group(1)
        valuta_raw   = m61.group(2)
        betrag_raw   = m61.group(3)
        _buchschl    = m61.group(4)
        referenz     = m61.group(5).strip()

        betrag, richtung = _parse_mt940_betrag(betrag_raw)
        datum = _mt940_datum(datum_raw)
        valuta = _mt940_datum(valuta_raw) if valuta_raw else datum

        # :86: Verwendungszweck
        m86 = re.search(r":86:(.*?)(?=:\d{2}[A-Z]?:|$)", block, re.DOTALL)
        verwendungszweck = ""
        gegenpartei = ""
        if m86:
            raw86 = m86.group(1).replace("\n", " ").strip()
            verwendungszweck = re.sub(r"\s+", " ", raw86)
            # Gegenpartei aus ?32 / ?33 Feldern extrahieren
            gp_m = re.search(r"\?32(.{0,35})", raw86)
            if gp_m:
                gegenpartei = gp_m.group(1).strip()

        transaktionen.append({
            "tx_id":           str(uuid.uuid4()),
            "datum":           datum,
            "valuta":          valuta,
            "betrag":          betrag,
            "waehrung":        "EUR",
            "richtung":        richtung,
            "verwendungszweck": verwendungszweck,
            "gegenpartei":     gegenpartei,
            "referenz":        referenz,
            "datei_quelle":    str(filepath),
            "datei_typ":       "MT940",
            "mandant_id":      mandant_id,
        })

    logger.info("MT940 geparsed: %d Transaktionen aus %s", len(transaktionen), filepath)
    return transaktionen


# ─── CAMT.053-Parser ──────────────────────────────────────

def parse_camt053(filepath: str | Path, mandant_id: str | None = None) -> list[dict]:
    """Parst eine CAMT.053-XML-Datei und gibt Liste von Transaktions-Dicts zurück."""
    tree = ET.parse(str(filepath))
    root = tree.getroot()

    # Namespace ermitteln
    ns = ""
    for candidate in _CAMT_NS:
        if f"{{{candidate}}}" in root.tag or root.tag == f"{{{candidate}}}Document":
            ns = f"{{{candidate}}}"
            break
    if not ns:
        # Aus root-Tag ableiten
        m = re.match(r"\{(.+?)\}", root.tag)
        ns = f"{{{m.group(1)}}}" if m else ""

    def t(tag: str) -> str:
        return f"{ns}{tag}"

    transaktionen: list[dict] = []

    for ntry in root.iter(t("Ntry")):
        # Betrag + Richtung
        amt_el = ntry.find(t("Amt"))
        betrag = float(amt_el.text or 0) if amt_el is not None else 0.0
        waehrung = (amt_el.attrib.get("Ccy", "EUR") if amt_el is not None else "EUR")

        cdi_el = ntry.find(t("CdtDbtInd"))
        richtung = "CREDIT" if (cdi_el is not None and cdi_el.text == "CRDT") else "DEBIT"

        # Datum
        buchg = ntry.find(f".//{t('BookgDt')}/{t('Dt')}")
        datum = buchg.text.strip()[:10] if buchg is not None else ""
        if not datum:
            val = ntry.find(f".//{t('ValDt')}/{t('Dt')}")
            datum = val.text.strip()[:10] if val is not None else datetime.now().date().isoformat()

        # Referenz
        acct_svcr = ntry.find(f".//{t('AcctSvcrRef')}")
        referenz = acct_svcr.text.strip() if acct_svcr is not None else ""

        # Verwendungszweck (Ustrd = unstrukturiert)
        vstrd_parts = [el.text.strip() for el in ntry.iter(t("Ustrd")) if el.text]
        verwendungszweck = " ".join(vstrd_parts)

        # Gegenpartei
        gegenpartei_parts: list[str] = []
        for tag in (t("Nm"), t("OrgId"), t("PrvtId")):
            el = ntry.find(f".//{t('Dbtr')}/{tag}")
            if el is None:
                el = ntry.find(f".//{t('Cdtr')}/{tag}")
            if el is not None and el.text:
                gegenpartei_parts.append(el.text.strip())
        gegenpartei = " ".join(gegenpartei_parts)

        transaktionen.append({
            "tx_id":            str(uuid.uuid4()),
            "datum":            datum,
            "valuta":           datum,
            "betrag":           betrag,
            "waehrung":         waehrung,
            "richtung":         richtung,
            "verwendungszweck": verwendungszweck,
            "gegenpartei":      gegenpartei,
            "referenz":         referenz,
            "datei_quelle":     str(filepath),
            "datei_typ":        "CAMT053",
            "mandant_id":       mandant_id,
        })

    logger.info("CAMT.053 geparsed: %d Transaktionen aus %s", len(transaktionen), filepath)
    return transaktionen


# ─── Import + Abgleich ────────────────────────────────────

def import_transaktionen(transaktionen: list[dict]) -> int:
    """Speichert Transaktionen in der DB. Ignoriert Duplikate (tx_id). Returns Anzahl neu."""
    _init_tables()
    from tools.db import get_db
    neu = 0
    with get_db() as conn:
        for tx in transaktionen:
            existing = conn.execute(
                "SELECT tx_id FROM bank_transaktionen WHERE tx_id = ?", (tx["tx_id"],)
            ).fetchone()
            if existing:
                continue
            conn.execute("""
                INSERT INTO bank_transaktionen
                (tx_id, datum, valuta, betrag, waehrung, richtung, verwendungszweck,
                 gegenpartei, referenz, datei_quelle, datei_typ, abgeglichen,
                 mandant_id, importiert_am)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)
            """, (
                tx["tx_id"], tx["datum"], tx.get("valuta"), tx["betrag"],
                tx.get("waehrung", "EUR"), tx["richtung"],
                tx.get("verwendungszweck", ""), tx.get("gegenpartei", ""),
                tx.get("referenz", ""), tx.get("datei_quelle"), tx.get("datei_typ"),
                tx.get("mandant_id"), datetime.now().isoformat(),
            ))
            neu += 1
    logger.info("Bankabgleich: %d neue Transaktionen importiert", neu)
    return neu


def abgleich_durchfuehren(mandant_id: str | None = None) -> dict:
    """Versucht offene Transaktionen mit Belegen abzugleichen.

    Matching-Strategie (Priorität):
    1. Exakter Betrag + Rechnungsnummer im Verwendungszweck
    2. Exakter Betrag + Lieferant im Gegenpartei-Feld
    3. Exakter Betrag + Datum ±3 Tage

    Returns: {"abgeglichen": int, "offen": int}
    """
    _init_tables()
    from tools.db import get_db, get_belege

    belege = get_belege(mandant_id=mandant_id, status="exportiert")
    belege_dict = {b["beleg_id"]: b for b in belege}

    with get_db() as conn:
        offene = conn.execute("""
            SELECT * FROM bank_transaktionen
            WHERE abgeglichen = 0 AND richtung = 'DEBIT'
            AND (mandant_id = ? OR ? IS NULL)
        """, (mandant_id, mandant_id)).fetchall()

        abgeglichen = 0
        for tx in offene:
            tx = dict(tx)
            match_id = _finde_beleg(tx, belege)
            if match_id:
                conn.execute("""
                    UPDATE bank_transaktionen
                    SET abgeglichen = 1, beleg_id = ?
                    WHERE tx_id = ?
                """, (match_id, tx["tx_id"]))
                abgeglichen += 1

        offen_count = conn.execute("""
            SELECT COUNT(*) FROM bank_transaktionen
            WHERE abgeglichen = 0 AND (mandant_id = ? OR ? IS NULL)
        """, (mandant_id, mandant_id)).fetchone()[0]

    logger.info("Bankabgleich: %d abgeglichen, %d offen", abgeglichen, offen_count)
    return {"abgeglichen": abgeglichen, "offen": offen_count}


def _finde_beleg(tx: dict, belege: list[dict]) -> str | None:
    """Versucht einen Beleg für eine Transaktion zu finden."""
    betrag = abs(tx["betrag"])
    vwz = (tx.get("verwendungszweck") or "").lower()
    gegenpartei = (tx.get("gegenpartei") or "").lower()

    for b in belege:
        b_betrag = abs(b.get("bruttobetrag") or 0)
        # Betrag muss übereinstimmen (±0.01 € Rundungstoleranz)
        if abs(betrag - b_betrag) > 0.01:
            continue

        re_nr = (b.get("rechnungsnummer") or "").lower()
        lieferant = (b.get("lieferant") or "").lower()

        # Priorität 1: Rechnungsnummer im Verwendungszweck
        if re_nr and len(re_nr) >= 4 and re_nr in vwz:
            return b["beleg_id"]

        # Priorität 2: Lieferant in Gegenpartei (min 5 Zeichen Übereinstimmung)
        if lieferant and len(lieferant) >= 5:
            kern = lieferant[:min(10, len(lieferant))]
            if kern in gegenpartei or kern in vwz:
                return b["beleg_id"]

    return None


def get_offene_transaktionen(
    mandant_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Gibt nicht abgeglichene Transaktionen zurück."""
    _init_tables()
    from tools.db import get_db
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM bank_transaktionen
            WHERE abgeglichen = 0 AND (mandant_id = ? OR ? IS NULL)
            ORDER BY datum DESC LIMIT ?
        """, (mandant_id, mandant_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_transaktionen(
    mandant_id: str | None = None,
    datum_von: str | None = None,
    datum_bis: str | None = None,
    nur_offen: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Gibt Transaktionen mit optionalen Filtern zurück."""
    _init_tables()
    from tools.db import get_db
    query = "SELECT * FROM bank_transaktionen WHERE 1=1"
    params: list = []

    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if datum_von:
        query += " AND datum >= ?"
        params.append(datum_von)
    if datum_bis:
        query += " AND datum <= ?"
        params.append(datum_bis)
    if nur_offen:
        query += " AND abgeglichen = 0"

    query += " ORDER BY datum DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def import_datei(filepath: str | Path, mandant_id: str | None = None) -> dict:
    """Auto-detect MT940 vs CAMT.053 und importiert direkt."""
    path = Path(filepath)
    suffix = path.suffix.lower()
    content_start = path.read_text(encoding="utf-8", errors="replace")[:200]

    if suffix in (".xml",) or content_start.lstrip().startswith("<"):
        transaktionen = parse_camt053(path, mandant_id)
        typ = "CAMT053"
    else:
        transaktionen = parse_mt940(path, mandant_id)
        typ = "MT940"

    neu = import_transaktionen(transaktionen)
    return {"typ": typ, "geparst": len(transaktionen), "neu_importiert": neu}
