"""Debitorenbuchhaltung: Ausgangsrechnungen + Forderungsmanagement.

Verwaltet offene Kundenforderungen, Zahlungseingänge und Mahnwesen.
DATEV-Export als EXTF-CSV für Ausgangsrechnungen.
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

# Standardkonten
_DEBITOREN_KONTO_SKR03 = "1400"   # Forderungen aus Lieferungen und Leistungen
_DEBITOREN_KONTO_SKR04 = "1200"   # Forderungen aus Lieferungen und Leistungen
_ERLOESE_KONTO_SKR03   = "8400"   # Umsatzerlöse 19%
_ERLOESE_KONTO_SKR04   = "4400"   # Umsatzerlöse 19%

# Mahngebühren (€) pro Mahnstufe
MAHNGEBUEHREN = {1: 0.00, 2: 5.00, 3: 15.00}

# Zahlungsziel in Tagen (Standard)
ZAHLUNGSZIEL_TAGE = 30


def _d(val) -> Decimal:
    if val is None:
        return Decimal("0")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _init_tables() -> None:
    from tools.db import get_db
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ausgangsrechnungen (
                rechnung_id      TEXT PRIMARY KEY,
                rechnungsnummer  TEXT,
                debitor_name     TEXT NOT NULL,
                debitor_email    TEXT,
                debitor_adresse  TEXT,
                betrag_netto     REAL NOT NULL,
                betrag_brutto    REAL NOT NULL,
                mwst_satz        REAL DEFAULT 19.0,
                mwst_betrag      REAL,
                rechnungsdatum   TEXT NOT NULL,
                faelligkeitsdatum TEXT NOT NULL,
                status           TEXT DEFAULT 'offen',
                zahlungsdatum    TEXT,
                buchungstext     TEXT,
                soll_konto       TEXT,
                haben_konto      TEXT,
                steuerschluessel TEXT DEFAULT '9',
                mandant_id       TEXT,
                notizen          TEXT,
                erstellt_am      TEXT,
                aktualisiert_am  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ar_mandant  ON ausgangsrechnungen(mandant_id);
            CREATE INDEX IF NOT EXISTS idx_ar_status   ON ausgangsrechnungen(status);
            CREATE INDEX IF NOT EXISTS idx_ar_faellig  ON ausgangsrechnungen(faelligkeitsdatum);

            CREATE TABLE IF NOT EXISTS mahnungen (
                mahnung_id       TEXT PRIMARY KEY,
                rechnung_id      TEXT NOT NULL,
                mahnstufe        INTEGER NOT NULL,
                mahndatum        TEXT NOT NULL,
                zahlungsfrist_bis TEXT,
                mahngebuehr      REAL DEFAULT 0,
                erstellt_am      TEXT,
                FOREIGN KEY (rechnung_id) REFERENCES ausgangsrechnungen(rechnung_id)
            );
            CREATE INDEX IF NOT EXISTS idx_mahn_rechnung ON mahnungen(rechnung_id);
        """)


def erfasse_ausgangsrechnung(
    debitor_name: str,
    betrag_netto: float,
    rechnungsdatum: str,
    mwst_satz: float = 19.0,
    rechnungsnummer: str | None = None,
    debitor_email: str | None = None,
    debitor_adresse: str | None = None,
    zahlungsziel_tage: int = ZAHLUNGSZIEL_TAGE,
    buchungstext: str | None = None,
    mandant_id: str | None = None,
    kontenrahmen: str = "SKR03",
    notizen: str | None = None,
) -> str:
    """Legt eine neue Ausgangsrechnung an. Gibt rechnung_id zurück."""
    _init_tables()

    netto  = _d(betrag_netto)
    mwst   = (netto * _d(mwst_satz) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    brutto = netto + mwst

    # Fälligkeit berechnen
    rdat = date.fromisoformat(rechnungsdatum)
    faellig = (rdat + timedelta(days=zahlungsziel_tage)).isoformat()

    # Konten
    if kontenrahmen.upper() == "SKR04":
        soll  = _DEBITOREN_KONTO_SKR04
        haben = _ERLOESE_KONTO_SKR04
    else:
        soll  = _DEBITOREN_KONTO_SKR03
        haben = _ERLOESE_KONTO_SKR03

    # Steuerschlüssel aus MwSt-Satz
    sk_map = {19.0: "9", 7.0: "8", 0.0: "0"}
    sk = sk_map.get(float(mwst_satz), "9")

    rechnung_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    from tools.db import get_db
    with get_db() as conn:
        conn.execute("""
            INSERT INTO ausgangsrechnungen
            (rechnung_id, rechnungsnummer, debitor_name, debitor_email, debitor_adresse,
             betrag_netto, betrag_brutto, mwst_satz, mwst_betrag,
             rechnungsdatum, faelligkeitsdatum, status,
             buchungstext, soll_konto, haben_konto, steuerschluessel,
             mandant_id, notizen, erstellt_am, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            rechnung_id, rechnungsnummer, debitor_name, debitor_email, debitor_adresse,
            float(netto), float(brutto), float(mwst_satz), float(mwst),
            rechnungsdatum, faellig, "offen",
            buchungstext or f"Rechnung {rechnungsnummer or rechnung_id[:8]} {debitor_name}",
            soll, haben, sk,
            mandant_id, notizen, now, now,
        ))

    logger.info("Ausgangsrechnung erfasst: %s / %s — %.2f € brutto (fällig %s)",
                debitor_name, rechnungsnummer or rechnung_id[:8], float(brutto), faellig)
    return rechnung_id


def mark_bezahlt(
    rechnung_id: str,
    zahlungsdatum: str | None = None,
) -> bool:
    """Markiert eine Ausgangsrechnung als bezahlt."""
    _init_tables()
    datum = zahlungsdatum or date.today().isoformat()
    from tools.db import get_db
    with get_db() as conn:
        conn.execute("""
            UPDATE ausgangsrechnungen
            SET status = 'bezahlt', zahlungsdatum = ?, aktualisiert_am = ?
            WHERE rechnung_id = ?
        """, (datum, datetime.now().isoformat(), rechnung_id))
    return True


def storniere_rechnung(rechnung_id: str) -> bool:
    """Storniert eine Ausgangsrechnung."""
    _init_tables()
    from tools.db import get_db
    with get_db() as conn:
        conn.execute("""
            UPDATE ausgangsrechnungen
            SET status = 'storniert', aktualisiert_am = ?
            WHERE rechnung_id = ?
        """, (datetime.now().isoformat(), rechnung_id))
    return True


def get_offene_forderungen(
    mandant_id: str | None = None,
    heute: str | None = None,
) -> list[dict]:
    """Gibt alle offenen Forderungen zurück, angereichert mit Überfälligkeitstagen."""
    _init_tables()
    from tools.db import get_db
    today_str = heute or date.today().isoformat()

    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM ausgangsrechnungen
            WHERE status = 'offen' AND (mandant_id = ? OR ? IS NULL)
            ORDER BY faelligkeitsdatum ASC
        """, (mandant_id, mandant_id)).fetchall()
        rechnungen = [dict(r) for r in rows]

    for r in rechnungen:
        faellig = r.get("faelligkeitsdatum", "")
        if faellig and faellig < today_str:
            tage = (date.fromisoformat(today_str) - date.fromisoformat(faellig)).days
            r["tage_ueberfaellig"] = tage
            r["ueberfaellig"] = True
        else:
            r["tage_ueberfaellig"] = 0
            r["ueberfaellig"] = False

    return rechnungen


def get_ausgangsrechnungen(
    mandant_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Gibt Ausgangsrechnungen mit optionalen Filtern zurück."""
    _init_tables()
    from tools.db import get_db
    query = "SELECT * FROM ausgangsrechnungen WHERE 1=1"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY rechnungsdatum DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def mahnlauf(
    mandant_id: str | None = None,
    heute: str | None = None,
    tage_bis_erste_mahnung: int = 7,
    tage_zweite_mahnung: int = 14,
    tage_dritte_mahnung: int = 30,
) -> list[dict]:
    """Ermittelt Rechnungen die eine Mahnung benötigen.

    Returns: Liste von Dicts mit rechnung + empfohlener Mahnstufe.
    Legt Mahnungs-Einträge in der DB an.
    """
    _init_tables()
    from tools.db import get_db
    today_str = heute or date.today().isoformat()
    faelligkeiten = get_offene_forderungen(mandant_id, today_str)
    zu_mahnen: list[dict] = []

    for r in faelligkeiten:
        if not r.get("ueberfaellig"):
            continue

        tage = r["tage_ueberfaellig"]
        rechnung_id = r["rechnung_id"]

        # Bestehende Mahnungen prüfen
        with get_db() as conn:
            letzte = conn.execute("""
                SELECT MAX(mahnstufe) as max_stufe FROM mahnungen
                WHERE rechnung_id = ?
            """, (rechnung_id,)).fetchone()
            letzte_stufe = letzte["max_stufe"] or 0

        # Nächste Mahnstufe berechnen
        if letzte_stufe == 0 and tage >= tage_bis_erste_mahnung:
            naechste_stufe = 1
        elif letzte_stufe == 1 and tage >= tage_zweite_mahnung:
            naechste_stufe = 2
        elif letzte_stufe == 2 and tage >= tage_dritte_mahnung:
            naechste_stufe = 3
        else:
            continue

        # Mahnung anlegen
        mahnung_id = str(uuid.uuid4())
        zahlungsfrist = (date.fromisoformat(today_str) + timedelta(days=14)).isoformat()
        gebuehr = MAHNGEBUEHREN.get(naechste_stufe, 0.0)

        with get_db() as conn:
            conn.execute("""
                INSERT INTO mahnungen
                (mahnung_id, rechnung_id, mahnstufe, mahndatum,
                 zahlungsfrist_bis, mahngebuehr, erstellt_am)
                VALUES (?,?,?,?,?,?,?)
            """, (mahnung_id, rechnung_id, naechste_stufe, today_str,
                  zahlungsfrist, gebuehr, datetime.now().isoformat()))

        zu_mahnen.append({
            **r,
            "mahnstufe":       naechste_stufe,
            "mahndatum":       today_str,
            "zahlungsfrist":   zahlungsfrist,
            "mahngebuehr":     gebuehr,
        })

    logger.info("Mahnlauf: %d Rechnungen gemahnt", len(zu_mahnen))
    return zu_mahnen


def erstelle_datev_export_debitoren(
    mandant_id: str | None = None,
    datum_von: str | None = None,
    datum_bis: str | None = None,
    berater_nr: str = "",
    mandant_nr: str = "",
    kontenrahmen: str = "SKR03",
) -> str:
    """Erstellt DATEV EXTF-CSV für Ausgangsrechnungen (Debitorenbuchungen).

    Returns: CSV-String im EXTF-Format v700.
    """
    _init_tables()
    from tools.db import get_db

    query = "SELECT * FROM ausgangsrechnungen WHERE status IN ('offen','bezahlt')"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if datum_von:
        query += " AND rechnungsdatum >= ?"
        params.append(datum_von)
    if datum_bis:
        query += " AND rechnungsdatum <= ?"
        params.append(datum_bis)
    query += " ORDER BY rechnungsdatum ASC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        rechnungen = [dict(r) for r in rows]

    if not rechnungen:
        return ""

    # DATEV EXTF-Header
    jetzt = datetime.now()
    wj_beginn = f"0101{jetzt.year}"
    header = (
        f'"EXTF";700;21;"Buchungsstapel";7;{jetzt.strftime("%Y%m%d%H%M%S")}000;'
        f';;"FiBu-Agent Debitoren";;{berater_nr};{mandant_nr};{wj_beginn};4;'
        f'EUR;;;"";{kontenrahmen};0;0\n'
    )

    col_header = (
        "Umsatz (ohne Soll/Haben-Kz);Soll/Haben-Kennzeichen;WKZ Umsatz;"
        "Kurs;Basis-Umsatz;WKZ Basis-Umsatz;Konto;Gegenkonto (ohne BU-Schlüssel);"
        "BU-Schlüssel;Belegdatum;Belegfeld 1;Belegfeld 2;Skonto;Buchungstext;"
        "Postensperre;Diverse Adressnummer;Geschäftspartnerbank;Sachverhalt;"
        "Zinssperre;Beleglink;Beleginfo - Art 1;Beleginfo - Inhalt 1;"
        "Beleginfo - Art 2;Beleginfo - Inhalt 2\n"
    )

    output = io.StringIO()
    output.write(header)
    output.write(col_header)

    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    for r in rechnungen:
        betrag = abs(r.get("betrag_brutto") or 0)
        betrag_str = f"{betrag:.2f}".replace(".", ",")
        rdat_str = (r.get("rechnungsdatum") or "")[:10]  # YYYY-MM-DD
        belegdatum = (rdat_str[8:10] + rdat_str[5:7]) if len(rdat_str) == 10 else ""  # TTMM
        belegfeld1 = (r.get("rechnungsnummer") or r["rechnung_id"][:8])[:12]
        buchungstext = (r.get("buchungstext") or r.get("debitor_name") or "")[:60]

        writer.writerow([
            betrag_str, "S", "EUR", "", "", "",
            r.get("soll_konto") or _DEBITOREN_KONTO_SKR03,
            r.get("haben_konto") or _ERLOESE_KONTO_SKR03,
            r.get("steuerschluessel") or "9",
            belegdatum, belegfeld1, "", "",
            buchungstext, "", "", "", "", "",
            "", "", "", "", "",
        ])

    logger.info("DATEV-Export Debitoren: %d Rechnungen", len(rechnungen))
    return output.getvalue()


def get_forderungs_summary(mandant_id: str | None = None) -> dict:
    """Gibt eine Zusammenfassung der Forderungslage zurück."""
    _init_tables()
    from tools.db import get_db
    today = date.today().isoformat()

    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as gesamt,
                SUM(CASE WHEN status = 'offen' THEN betrag_brutto ELSE 0 END) as offen_summe,
                SUM(CASE WHEN status = 'bezahlt' THEN betrag_brutto ELSE 0 END) as bezahlt_summe,
                SUM(CASE WHEN status = 'offen' AND faelligkeitsdatum < ? THEN betrag_brutto ELSE 0 END) as ueberfaellig_summe,
                COUNT(CASE WHEN status = 'offen' AND faelligkeitsdatum < ? THEN 1 END) as ueberfaellig_count
            FROM ausgangsrechnungen
            WHERE mandant_id = ? OR ? IS NULL
        """, (today, today, mandant_id, mandant_id)).fetchone()
        return dict(row) if row else {}
