"""SQLite-Datenbank für Belege, Runs und Audit-Events.

Ersetzt die JSON-Datei-basierte Speicherung durch eine persistente,
querybare SQLite-Datenbank mit Cross-Run-Duplikaterkennung.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from pathlib import Path

import os

from tools.config import ROOT

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "fibu_agent.db")))


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager für Datenbankverbindung."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Erstellt alle Tabellen falls nicht vorhanden."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS belege (
                beleg_id TEXT PRIMARY KEY,
                run_id TEXT,
                mandant_id TEXT,
                dateiname TEXT,
                dateipfad TEXT,
                lieferant TEXT,
                rechnungsnummer TEXT,
                belegdatum TEXT,
                bruttobetrag REAL,
                nettobetrag REAL,
                mwst_betrag REAL,
                mwst_satz REAL,
                waehrung TEXT DEFAULT 'EUR',
                soll_konto TEXT,
                haben_konto TEXT,
                steuerschluessel TEXT,
                buchungstext TEXT,
                status TEXT DEFAULT 'neu',
                ocr_konfidenz REAL,
                kontierung_methode TEXT,
                rueckfrage_grund TEXT,
                validierung_fehler TEXT,
                verwendungszweck TEXT,
                erstellt_am TEXT,
                aktualisiert_am TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_belege_status ON belege(status);
            CREATE INDEX IF NOT EXISTS idx_belege_mandant ON belege(mandant_id);
            CREATE INDEX IF NOT EXISTS idx_belege_run ON belege(run_id);
            CREATE INDEX IF NOT EXISTS idx_belege_duplikat ON belege(rechnungsnummer, lieferant, bruttobetrag);

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                mandant_id TEXT,
                gestartet_am TEXT,
                beendet_am TEXT,
                status TEXT DEFAULT 'laufend',
                belege_total INTEGER DEFAULT 0,
                belege_exportiert INTEGER DEFAULT 0,
                belege_fehler INTEGER DEFAULT 0,
                belege_rueckfrage INTEGER DEFAULT 0,
                export_datei TEXT,
                zusammenfassung TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beleg_id TEXT,
                event_type TEXT NOT NULL,
                zeitstempel TEXT NOT NULL,
                akteur TEXT DEFAULT 'fibu_agent',
                details TEXT,
                beleg_snapshot TEXT,
                prev_hash TEXT,
                hash TEXT,
                FOREIGN KEY (beleg_id) REFERENCES belege(beleg_id)
            );

            CREATE INDEX IF NOT EXISTS idx_audit_beleg ON audit_events(beleg_id);

            CREATE TABLE IF NOT EXISTS vendor_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lieferant TEXT NOT NULL,
                mandant_id TEXT,
                soll_konto TEXT,
                bezeichnung TEXT,
                steuerschluessel TEXT,
                bestaetigt_count INTEGER DEFAULT 0,
                fehler_count INTEGER DEFAULT 0,
                ist_vertrauenslieferant INTEGER DEFAULT 0,
                letztes_datum TEXT,
                UNIQUE(lieferant, mandant_id)
            );
            CREATE INDEX IF NOT EXISTS idx_vendor_cache_lieferant ON vendor_cache(lieferant);
        """)
    # Migration: verwendungszweck zu bestehenden DBs hinzufügen
    with get_db() as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(belege)").fetchall()}
        if "verwendungszweck" not in existing:
            conn.execute("ALTER TABLE belege ADD COLUMN verwendungszweck TEXT")
            logger.info("Migration: verwendungszweck-Spalte zu belege hinzugefügt")
    logger.info("Datenbank initialisiert: %s", DB_PATH)


# ─── Beleg-Operationen ────────────────────────────────────

def upsert_beleg(beleg: dict) -> None:
    """Speichert oder aktualisiert einen Beleg."""
    now = datetime.now().isoformat()
    beleg.setdefault("erstellt_am", now)
    beleg["aktualisiert_am"] = now

    # validierung_fehler als JSON-String
    val_fehler = beleg.get("validierung_fehler")
    if isinstance(val_fehler, list):
        val_fehler = json.dumps(val_fehler, ensure_ascii=False)

    with get_db() as conn:
        conn.execute("""
            INSERT INTO belege (
                beleg_id, run_id, mandant_id, dateiname, dateipfad,
                lieferant, rechnungsnummer, belegdatum,
                bruttobetrag, nettobetrag, mwst_betrag, mwst_satz, waehrung,
                soll_konto, haben_konto, steuerschluessel, buchungstext,
                verwendungszweck, status, ocr_konfidenz, kontierung_methode,
                rueckfrage_grund, validierung_fehler,
                erstellt_am, aktualisiert_am
            ) VALUES (
                :beleg_id, :run_id, :mandant_id, :dateiname, :dateipfad,
                :lieferant, :rechnungsnummer, :belegdatum,
                :bruttobetrag, :nettobetrag, :mwst_betrag, :mwst_satz, :waehrung,
                :soll_konto, :haben_konto, :steuerschluessel, :buchungstext,
                :verwendungszweck, :status, :ocr_konfidenz, :kontierung_methode,
                :rueckfrage_grund, :validierung_fehler,
                :erstellt_am, :aktualisiert_am
            )
            ON CONFLICT(beleg_id) DO UPDATE SET
                status=excluded.status,
                soll_konto=excluded.soll_konto,
                haben_konto=excluded.haben_konto,
                steuerschluessel=excluded.steuerschluessel,
                buchungstext=excluded.buchungstext,
                verwendungszweck=excluded.verwendungszweck,
                ocr_konfidenz=excluded.ocr_konfidenz,
                kontierung_methode=excluded.kontierung_methode,
                rueckfrage_grund=excluded.rueckfrage_grund,
                validierung_fehler=excluded.validierung_fehler,
                aktualisiert_am=excluded.aktualisiert_am
        """, {
            "beleg_id": beleg.get("beleg_id"),
            "run_id": beleg.get("run_id"),
            "mandant_id": beleg.get("mandant_id"),
            "dateiname": beleg.get("dateiname"),
            "dateipfad": beleg.get("dateipfad"),
            "lieferant": beleg.get("lieferant"),
            "rechnungsnummer": beleg.get("rechnungsnummer"),
            "belegdatum": beleg.get("belegdatum"),
            "bruttobetrag": beleg.get("bruttobetrag"),
            "nettobetrag": beleg.get("nettobetrag"),
            "mwst_betrag": beleg.get("mwst_betrag"),
            "mwst_satz": beleg.get("mwst_satz"),
            "waehrung": beleg.get("waehrung", "EUR"),
            "soll_konto": beleg.get("soll_konto"),
            "haben_konto": beleg.get("haben_konto"),
            "steuerschluessel": beleg.get("steuerschluessel"),
            "buchungstext": beleg.get("buchungstext"),
            "verwendungszweck": beleg.get("verwendungszweck"),
            "status": beleg.get("status", "neu"),
            "ocr_konfidenz": beleg.get("ocr_konfidenz"),
            "kontierung_methode": beleg.get("kontierung_methode"),
            "rueckfrage_grund": beleg.get("rueckfrage_grund"),
            "validierung_fehler": val_fehler,
            "erstellt_am": beleg.get("erstellt_am", now),
            "aktualisiert_am": now,
        })


def get_beleg(beleg_id: str) -> dict | None:
    """Holt einen einzelnen Beleg."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM belege WHERE beleg_id = ?", (beleg_id,)).fetchone()
        return dict(row) if row else None


def get_belege(mandant_id: str | None = None, status: str | None = None) -> list[dict]:
    """Holt Belege mit optionalen Filtern."""
    query = "SELECT * FROM belege WHERE 1=1"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY erstellt_am DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def check_duplikat(
    rechnungsnummer: str,
    lieferant: str,
    bruttobetrag: float,
    mandant_id: str | None = None,
    waehrung: str = "EUR",
) -> bool:
    """Cross-Run-Duplikatcheck — Fix 7: mandant_id-isoliert, Fix 15: Fremdwährung nur per RE-Nr.

    Für Fremdwährungen (nicht EUR) wird nur Rechnungsnummer + Lieferant verglichen,
    da der Betrag durch Rundung/Wechselkurs variieren kann.
    """
    with get_db() as conn:
        if waehrung != "EUR":
            # Fix 15: Fremdwährung — Betrag-Vergleich weglassen
            query = "SELECT COUNT(*) as cnt FROM belege WHERE rechnungsnummer = ? AND lieferant = ?"
            params: tuple = (rechnungsnummer, lieferant)
            if mandant_id:
                query += " AND mandant_id = ?"
                params = (*params, mandant_id)
        else:
            query = "SELECT COUNT(*) as cnt FROM belege WHERE rechnungsnummer = ? AND lieferant = ? AND bruttobetrag = ?"
            params = (rechnungsnummer, lieferant, bruttobetrag)
            if mandant_id:
                query += " AND mandant_id = ?"
                params = (*params, mandant_id)

        row = conn.execute(query, params).fetchone()
        return row["cnt"] > 0


def get_stats(mandant_id: str | None = None) -> dict:
    """Aggregierte Statistiken."""
    where = "WHERE mandant_id = ?" if mandant_id else ""
    params = (mandant_id,) if mandant_id else ()

    with get_db() as conn:
        row = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'exportiert' THEN 1 ELSE 0 END) as exportiert,
                SUM(CASE WHEN status = 'rueckfrage' THEN 1 ELSE 0 END) as rueckfragen,
                SUM(CASE WHEN status = 'fehler' THEN 1 ELSE 0 END) as fehler,
                SUM(CASE WHEN status = 'exportiert' THEN bruttobetrag ELSE 0 END) as volumen
            FROM belege {where}
        """, params).fetchone()
        return dict(row)


# ─── Run-Operationen ──────────────────────────────────────

def create_run(run_id: str, mandant_id: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, mandant_id, gestartet_am) VALUES (?, ?, ?)",
            (run_id, mandant_id, datetime.now().isoformat())
        )


def finish_run(run_id: str, stats: dict, export_datei: str | None = None) -> None:
    with get_db() as conn:
        conn.execute("""
            UPDATE runs SET
                beendet_am = ?,
                status = 'abgeschlossen',
                belege_total = ?,
                belege_exportiert = ?,
                belege_fehler = ?,
                belege_rueckfrage = ?,
                export_datei = ?
            WHERE run_id = ?
        """, (
            datetime.now().isoformat(),
            stats.get("total", 0),
            stats.get("exportiert", 0),
            stats.get("fehler", 0),
            stats.get("rueckfrage", 0),
            export_datei,
            run_id,
        ))


def get_runs(mandant_id: str | None = None, limit: int = 20) -> list[dict]:
    query = "SELECT * FROM runs"
    params: list = []
    if mandant_id:
        query += " WHERE mandant_id = ?"
        params.append(mandant_id)
    query += " ORDER BY gestartet_am DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ─── Kontierungs-Korrekturen (Lernschleife) ───────────────

def save_kontierung_korrektur(
    lieferant: str,
    verwendungszweck: str,
    falsches_konto: str,
    korrektes_konto: str,
    mandant_id: str | None = None,
) -> None:
    """Speichert eine manuelle Kontierungskorrektur für späteres Few-Shot-Learning."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kontierung_korrekturen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lieferant TEXT,
                verwendungszweck TEXT,
                falsches_konto TEXT,
                korrektes_konto TEXT,
                mandant_id TEXT,
                bestaetigt_count INTEGER DEFAULT 1,
                auto_regel_erstellt INTEGER DEFAULT 0,
                erstellt_am TEXT
            )
        """)
        # Existierende Korrektur für gleichen Lieferant + Konto erhöhen
        row = conn.execute("""
            SELECT id, bestaetigt_count FROM kontierung_korrekturen
            WHERE lieferant = ? AND korrektes_konto = ? AND (mandant_id = ? OR mandant_id IS NULL)
            ORDER BY bestaetigt_count DESC LIMIT 1
        """, (lieferant, korrektes_konto, mandant_id)).fetchone()

        if row:
            conn.execute(
                "UPDATE kontierung_korrekturen SET bestaetigt_count = bestaetigt_count + 1, "
                "verwendungszweck = ? WHERE id = ?",
                (verwendungszweck, row["id"])
            )
        else:
            conn.execute("""
                INSERT INTO kontierung_korrekturen
                (lieferant, verwendungszweck, falsches_konto, korrektes_konto,
                 mandant_id, bestaetigt_count, erstellt_am)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (lieferant, verwendungszweck, falsches_konto, korrektes_konto,
                  mandant_id, datetime.now().isoformat()))


def get_aehnliche_korrekturen(
    lieferant: str,
    verwendungszweck: str,
    mandant_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Holt ähnliche bestätigte Korrekturen als Few-Shot-Beispiele für den LLM-Prompt.

    Mandant-isoliert: nur eigene Korrekturen, keine Cross-Mandant-Kontamination.
    """
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kontierung_korrekturen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lieferant TEXT, verwendungszweck TEXT,
                falsches_konto TEXT, korrektes_konto TEXT, mandant_id TEXT,
                bestaetigt_count INTEGER DEFAULT 1,
                auto_regel_erstellt INTEGER DEFAULT 0, erstellt_am TEXT
            )
        """)
        suchtext = f"%{lieferant.lower()[:15]}%"
        rows = conn.execute("""
            SELECT lieferant, verwendungszweck, falsches_konto, korrektes_konto, bestaetigt_count
            FROM kontierung_korrekturen
            WHERE (LOWER(lieferant) LIKE ? OR LOWER(verwendungszweck) LIKE ?)
              AND (mandant_id = ? OR mandant_id IS NULL)
            ORDER BY bestaetigt_count DESC, erstellt_am DESC
            LIMIT ?
        """, (suchtext, f"%{verwendungszweck.lower()[:20]}%", mandant_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_korrekturen_fuer_regelwerk(min_bestaetigt: int = 3) -> list[dict]:
    """Korrekturen die oft genug bestätigt wurden um ins Regelwerk aufgenommen zu werden."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kontierung_korrekturen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lieferant TEXT, verwendungszweck TEXT,
                falsches_konto TEXT, korrektes_konto TEXT, mandant_id TEXT,
                bestaetigt_count INTEGER DEFAULT 1,
                auto_regel_erstellt INTEGER DEFAULT 0, erstellt_am TEXT
            )
        """)
        rows = conn.execute("""
            SELECT id, lieferant, verwendungszweck, korrektes_konto, bestaetigt_count
            FROM kontierung_korrekturen
            WHERE bestaetigt_count >= ? AND auto_regel_erstellt = 0
            ORDER BY bestaetigt_count DESC
        """, (min_bestaetigt,)).fetchall()
        return [dict(r) for r in rows]


def mark_korrektur_als_regel(korrektur_id: int) -> None:
    """Markiert eine Korrektur als bereits ins Regelwerk überführt."""
    with get_db() as conn:
        conn.execute(
            "UPDATE kontierung_korrekturen SET auto_regel_erstellt = 1 WHERE id = ?",
            (korrektur_id,)
        )


# ─── Vendor Master Cache (#6 + #18) ───────────────────────

VERTRAUENS_SCHWELLE = 10  # Nach X bestätigten Buchungen: Vertrauenslieferant


def get_vendor_cache(lieferant: str, mandant_id: str | None = None) -> dict | None:
    """Lieferant-Cache-Lookup. Mandant-spezifisch vor globalem Eintrag."""
    normalized = lieferant.strip().lower()
    with get_db() as conn:
        # Mandant-spezifisch zuerst, dann global (NULL mandant_id)
        row = conn.execute("""
            SELECT * FROM vendor_cache
            WHERE LOWER(lieferant) = ?
              AND (mandant_id = ? OR mandant_id IS NULL)
            ORDER BY
                CASE WHEN mandant_id = ? THEN 0 ELSE 1 END,
                bestaetigt_count DESC
            LIMIT 1
        """, (normalized, mandant_id, mandant_id)).fetchone()
        return dict(row) if row else None


def update_vendor_cache(
    lieferant: str,
    soll_konto: str,
    bezeichnung: str,
    steuerschluessel: str,
    mandant_id: str | None = None,
    bestaetigt: bool = True,
) -> None:
    """Aktualisiert Vendor-Cache nach bestätigter oder korrigierter Buchung.

    bestaetigt=True  → Buchung vom Buchhalter abgenickt, count erhöhen
    bestaetigt=False → Buchung war falsch, Korrektur speichern, Trust zurücksetzen
    """
    now = datetime.now().isoformat()
    normalized = lieferant.strip().lower()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, bestaetigt_count FROM vendor_cache WHERE LOWER(lieferant) = ? AND mandant_id IS ?",
            (normalized, mandant_id)
        ).fetchone()

        if existing:
            if bestaetigt:
                new_count = existing["bestaetigt_count"] + 1
                is_trusted = 1 if new_count >= VERTRAUENS_SCHWELLE else 0
                conn.execute("""
                    UPDATE vendor_cache SET
                        soll_konto = ?, bezeichnung = ?, steuerschluessel = ?,
                        bestaetigt_count = ?, ist_vertrauenslieferant = ?, letztes_datum = ?
                    WHERE id = ?
                """, (soll_konto, bezeichnung, steuerschluessel,
                      new_count, is_trusted, now, existing["id"]))
                if is_trusted and existing["bestaetigt_count"] < VERTRAUENS_SCHWELLE:
                    logger.info(
                        "Vertrauenslieferant erreicht: '%s' (%d Bestätigungen)",
                        lieferant, new_count
                    )
            else:
                # Korrektur: Kontierung aktualisieren, Trust entziehen
                conn.execute("""
                    UPDATE vendor_cache SET
                        soll_konto = ?, bezeichnung = ?, steuerschluessel = ?,
                        fehler_count = fehler_count + 1,
                        ist_vertrauenslieferant = 0,
                        letztes_datum = ?
                    WHERE id = ?
                """, (soll_konto, bezeichnung, steuerschluessel, now, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO vendor_cache
                (lieferant, mandant_id, soll_konto, bezeichnung, steuerschluessel,
                 bestaetigt_count, ist_vertrauenslieferant, letztes_datum)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (normalized, mandant_id, soll_konto, bezeichnung, steuerschluessel,
                  1 if bestaetigt else 0, now))


def get_rueckfragen_queue(mandant_id: str | None = None, limit: int = 100) -> list[dict]:
    """Gibt offene Rückfragen zurück, sortiert nach Bruttobetrag absteigend (#3).

    Höchste Beträge zuerst — der Buchhalter soll zuerst die wichtigsten Belege sehen.
    """
    query = "SELECT * FROM belege WHERE status = 'rueckfrage'"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    query += " ORDER BY ABS(bruttobetrag) DESC, erstellt_am ASC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_vertrauenslieferanten(mandant_id: str | None = None) -> list[dict]:
    """Gibt alle Vertrauenslieferanten zurück (für Übersicht im UI)."""
    with get_db() as conn:
        query = "SELECT * FROM vendor_cache WHERE ist_vertrauenslieferant = 1"
        params: list = []
        if mandant_id:
            query += " AND (mandant_id = ? OR mandant_id IS NULL)"
            params.append(mandant_id)
        query += " ORDER BY bestaetigt_count DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ─── Anomalie-Erkennung (#20) ─────────────────────────────

def check_anomalie(
    lieferant: str,
    bruttobetrag: float,
    belegdatum: str | None = None,
    mandant_id: str | None = None,
    min_history: int = 3,
) -> list[str]:
    """Prüft einen Beleg auf statistische und strukturelle Anomalien.

    Gibt Liste mit Anomalie-Beschreibungen zurück (leer = alles normal).
    Benötigt mindestens min_history vergangene Buchungen für Betragsvergleich.
    """
    warnungen: list[str] = []
    betrag = abs(bruttobetrag or 0)

    # 1. Historische Betragsstatistik für diesen Lieferanten
    with get_db() as conn:
        query = """
            SELECT bruttobetrag FROM belege
            WHERE lieferant = ? AND status IN ('exportiert', 'exportiert_datev')
              AND bruttobetrag IS NOT NULL
        """
        params: list = [lieferant]
        if mandant_id:
            query += " AND mandant_id = ?"
            params.append(mandant_id)
        query += " ORDER BY erstellt_am DESC LIMIT 100"
        rows = conn.execute(query, params).fetchall()

    historisch = [abs(r["bruttobetrag"]) for r in rows if r["bruttobetrag"]]

    if len(historisch) >= min_history:
        mean = sum(historisch) / len(historisch)
        if mean > 0:
            abweichung = betrag / mean
            if abweichung > 3.0:
                warnungen.append(
                    f"Betrag {betrag:.2f} € ist {abweichung:.1f}x höher als "
                    f"Durchschnitt {mean:.2f} € ({len(historisch)} Buchungen)"
                )
            elif abweichung < 0.2:
                warnungen.append(
                    f"Betrag {betrag:.2f} € ist ungewöhnlich niedrig "
                    f"(Durchschnitt {mean:.2f} €)"
                )
    elif len(historisch) == 0:
        # Noch nie gebucht — hohe Beträge markieren
        if betrag >= 5000:
            warnungen.append(
                f"Unbekannter Lieferant mit hohem Betrag {betrag:.2f} € — erste Buchung"
            )

    # 2. Runde Betrag + hoher Wert (Umsatzsteuer-Betrugsindikator)
    if betrag >= 1000 and betrag == int(betrag):
        warnungen.append(
            f"Runder Betrag {betrag:.0f} € (≥ 1.000 €) — bitte Originalrechnung prüfen"
        )

    # 3. Datum: Wochenende oder Zukunft
    if belegdatum:
        try:
            from datetime import date as _date, datetime as _dt
            bd = _dt.strptime(belegdatum, "%Y-%m-%d").date()
            if bd.weekday() >= 5:
                warnungen.append(
                    f"Belegdatum {belegdatum} liegt auf einem "
                    f"{'Samstag' if bd.weekday() == 5 else 'Sonntag'}"
                )
        except ValueError:
            pass

    return warnungen


# ─── Offene-Posten-Tracking (#21) ─────────────────────────

def _init_offene_posten(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS offene_posten (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandant_id TEXT,
            beleg_id TEXT,
            lieferant TEXT NOT NULL,
            rechnungsnummer TEXT,
            betrag REAL NOT NULL,
            waehrung TEXT DEFAULT 'EUR',
            belegdatum TEXT,
            faelligkeitsdatum TEXT,
            status TEXT DEFAULT 'offen',
            bezahlt_am TEXT,
            erstellt_am TEXT,
            FOREIGN KEY (beleg_id) REFERENCES belege(beleg_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_op_status ON offene_posten(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_op_mandant ON offene_posten(mandant_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_op_faellig ON offene_posten(faelligkeitsdatum)")


def erfasse_offenen_posten(
    lieferant: str,
    betrag: float,
    belegdatum: str,
    mandant_id: str | None = None,
    rechnungsnummer: str | None = None,
    beleg_id: str | None = None,
    waehrung: str = "EUR",
    zahlungsziel_tage: int = 30,
) -> int:
    """Legt einen neuen offenen Posten an. Gibt die ID zurück."""
    from datetime import date, timedelta
    try:
        bd = datetime.strptime(belegdatum, "%Y-%m-%d").date()
        faellig = (bd + timedelta(days=zahlungsziel_tage)).isoformat()
    except ValueError:
        faellig = None

    with get_db() as conn:
        _init_offene_posten(conn)
        cur = conn.execute("""
            INSERT INTO offene_posten
            (mandant_id, beleg_id, lieferant, rechnungsnummer, betrag, waehrung,
             belegdatum, faelligkeitsdatum, status, erstellt_am)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'offen', ?)
        """, (mandant_id, beleg_id, lieferant, rechnungsnummer, betrag, waehrung,
              belegdatum, faellig, datetime.now().isoformat()))
        return cur.lastrowid


def mark_posten_bezahlt(posten_id: int, bezahlt_am: str | None = None) -> None:
    """Markiert einen offenen Posten als bezahlt."""
    with get_db() as conn:
        _init_offene_posten(conn)
        conn.execute("""
            UPDATE offene_posten SET status = 'bezahlt', bezahlt_am = ?
            WHERE id = ?
        """, (bezahlt_am or datetime.now().isoformat(), posten_id))


def get_offene_posten(
    mandant_id: str | None = None,
    nur_faellige: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Gibt offene Posten zurück. nur_faellige=True: nur überfällige (Fälligkeit < heute)."""
    with get_db() as conn:
        _init_offene_posten(conn)
        heute = datetime.now().date().isoformat()
        query = "SELECT * FROM offene_posten WHERE status = 'offen'"
        params: list = []
        if mandant_id:
            query += " AND mandant_id = ?"
            params.append(mandant_id)
        if nur_faellige:
            query += " AND faelligkeitsdatum < ?"
            params.append(heute)
        query += " ORDER BY faelligkeitsdatum ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Überfälligkeitsstatus berechnen
            if d.get("faelligkeitsdatum") and d["faelligkeitsdatum"] < heute:
                d["ueberfaellig"] = True
                try:
                    from datetime import date as _date
                    delta = (_date.fromisoformat(heute) - _date.fromisoformat(d["faelligkeitsdatum"])).days
                    d["tage_ueberfaellig"] = delta
                except Exception:
                    d["tage_ueberfaellig"] = None
            else:
                d["ueberfaellig"] = False
                d["tage_ueberfaellig"] = 0
            result.append(d)
        return result


def get_offene_posten_summe(mandant_id: str | None = None) -> dict:
    """Aggregiert offene Posten nach Status für Dashboard."""
    with get_db() as conn:
        _init_offene_posten(conn)
        heute = datetime.now().date().isoformat()
        where = "WHERE status = 'offen'"
        params: list = []
        if mandant_id:
            where += " AND mandant_id = ?"
            params.append(mandant_id)
        row = conn.execute(f"""
            SELECT
                COUNT(*) as anzahl,
                SUM(betrag) as gesamt,
                SUM(CASE WHEN faelligkeitsdatum < '{heute}' THEN betrag ELSE 0 END) as ueberfaellig,
                SUM(CASE WHEN faelligkeitsdatum >= '{heute}' THEN betrag ELSE 0 END) as faellig_bald
            FROM offene_posten {where}
        """, params).fetchone()
        return dict(row)


# ─── Initialisierung beim Import ──────────────────────────

init_db()
