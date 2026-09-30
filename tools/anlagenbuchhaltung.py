"""Anlagenbuchhaltung: Asset-Registry + lineare AfA-Berechnung.

Unterstützt SKR03 und SKR04, GWG-Sofortabschreibung (< 800 € netto),
mandant-isoliert. Keine externen Abhängigkeiten.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

# GWG-Grenze (netto) nach § 6 Abs. 2 EStG
GWG_GRENZE_SOFORT = Decimal("250.00")   # < 250 € → Betriebsausgabe, keine Anlage
GWG_GRENZE_POOL   = Decimal("800.00")   # 250–800 € → GWG / Sammelposten

# SKR03-Standardkonten für AfA
_SKR03_KONTEN = {
    "gwg":          {"soll": "0485", "afa": "4855", "gegen": "0485"},
    "edv":          {"soll": "0670", "afa": "4830", "gegen": "0679"},
    "buero":        {"soll": "0680", "afa": "4830", "gegen": "0689"},
    "fahrzeug":     {"soll": "0320", "afa": "4830", "gegen": "0329"},
    "maschinen":    {"soll": "0200", "afa": "4830", "gegen": "0209"},
    "default":      {"soll": "0680", "afa": "4830", "gegen": "0689"},
}

# SKR04-Standardkonten für AfA
_SKR04_KONTEN = {
    "gwg":          {"soll": "0485", "afa": "6260", "gegen": "0485"},
    "edv":          {"soll": "0650", "afa": "6200", "gegen": "0659"},
    "buero":        {"soll": "0660", "afa": "6200", "gegen": "0669"},
    "fahrzeug":     {"soll": "0520", "afa": "6200", "gegen": "0529"},
    "maschinen":    {"soll": "0400", "afa": "6200", "gegen": "0409"},
    "default":      {"soll": "0660", "afa": "6200", "gegen": "0669"},
}


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
            CREATE TABLE IF NOT EXISTS anlagegüter (
                anlage_id       TEXT PRIMARY KEY,
                bezeichnung     TEXT NOT NULL,
                lieferant       TEXT,
                beleg_id        TEXT,
                anschaffungsdatum TEXT NOT NULL,
                anschaffungskosten REAL NOT NULL,
                nutzungsdauer_jahre INTEGER NOT NULL,
                afa_methode     TEXT DEFAULT 'linear',
                restwert        REAL DEFAULT 0,
                soll_konto      TEXT,
                afa_konto       TEXT,
                gegenkonto_afa  TEXT,
                gwg             INTEGER DEFAULT 0,
                mandant_id      TEXT,
                aktiv           INTEGER DEFAULT 1,
                abgangsdatum    TEXT,
                notizen         TEXT,
                erstellt_am     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_anlagen_mandant ON anlagegüter(mandant_id);
            CREATE INDEX IF NOT EXISTS idx_anlagen_aktiv   ON anlagegüter(aktiv);
        """)


def konten_fuer_kategorie(kategorie: str, kontenrahmen: str = "SKR03") -> dict:
    """Gibt Standard-AfA-Konten für eine Kategorie zurück."""
    mapping = _SKR03_KONTEN if kontenrahmen.upper() == "SKR03" else _SKR04_KONTEN
    return mapping.get(kategorie.lower(), mapping["default"])


def is_gwg(nettobetrag: float | Decimal) -> str:
    """Klassifiziert Betrag: 'keine_anlage', 'gwg_sofort' oder 'normal'."""
    n = _d(nettobetrag)
    if n < GWG_GRENZE_SOFORT:
        return "keine_anlage"
    if n <= GWG_GRENZE_POOL:
        return "gwg_sofort"
    return "normal"


def erfasse_anlage(
    bezeichnung: str,
    anschaffungsdatum: str,
    anschaffungskosten: float,
    nutzungsdauer_jahre: int,
    soll_konto: str | None = None,
    afa_konto: str | None = None,
    gegenkonto_afa: str | None = None,
    afa_methode: str = "linear",
    restwert: float = 0.0,
    lieferant: str | None = None,
    beleg_id: str | None = None,
    mandant_id: str | None = None,
    kontenrahmen: str = "SKR03",
    kategorie: str = "default",
    notizen: str | None = None,
) -> str:
    """Legt eine neue Anlage in der Registry an. Gibt anlage_id zurück."""
    _init_tables()

    gwg_typ = is_gwg(anschaffungskosten)
    ist_gwg = gwg_typ == "gwg_sofort"

    # Konten ableiten wenn nicht explizit angegeben
    if ist_gwg:
        defaults = konten_fuer_kategorie("gwg", kontenrahmen)
        nutzungsdauer_jahre = 1
    else:
        defaults = konten_fuer_kategorie(kategorie, kontenrahmen)

    from tools.db import get_db
    anlage_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("""
            INSERT INTO anlagegüter
            (anlage_id, bezeichnung, lieferant, beleg_id, anschaffungsdatum,
             anschaffungskosten, nutzungsdauer_jahre, afa_methode, restwert,
             soll_konto, afa_konto, gegenkonto_afa, gwg, mandant_id,
             aktiv, notizen, erstellt_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)
        """, (
            anlage_id, bezeichnung, lieferant, beleg_id, anschaffungsdatum,
            float(anschaffungskosten), nutzungsdauer_jahre, afa_methode, float(restwert),
            soll_konto or defaults["soll"],
            afa_konto or defaults["afa"],
            gegenkonto_afa or defaults["gegen"],
            1 if ist_gwg else 0,
            mandant_id, notizen, datetime.now().isoformat(),
        ))

    logger.info("Anlage erfasst: %s (%s) — GWG: %s", bezeichnung, anlage_id, ist_gwg)
    return anlage_id


def berechne_afa_monat(
    anlage: dict,
    monat: str,  # YYYY-MM
) -> Decimal:
    """Berechnet die monatliche AfA für eine Anlage.

    Lineare AfA: (AK - Restwert) / ND_Jahre / 12.
    Im Anschaffungsmonat volle Monats-AfA.
    Nach Nutzungsdauer: 0 (Anlage voll abgeschrieben).
    """
    ak = _d(anlage["anschaffungskosten"])
    rw = _d(anlage.get("restwert", 0))
    nd = int(anlage["nutzungsdauer_jahre"])

    anschaffung = str(anlage["anschaffungsdatum"])[:7]  # YYYY-MM

    if monat < anschaffung:
        return Decimal("0")

    # Monate seit Anschaffung (0-based)
    try:
        y1, m1 = map(int, anschaffung.split("-"))
        y2, m2 = map(int, monat.split("-"))
        monate_seit_kauf = (y2 - y1) * 12 + (m2 - m1)
    except ValueError:
        return Decimal("0")

    gesamt_monate = nd * 12
    if monate_seit_kauf >= gesamt_monate:
        return Decimal("0")

    monatlich = ((ak - rw) / Decimal(str(gesamt_monate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return monatlich


def berechne_jahres_afa(
    mandant_id: str | None = None,
    jahr: int | None = None,
) -> list[dict]:
    """Berechnet die jährliche AfA für alle aktiven Anlagen eines Mandanten.

    Returns: Liste mit {anlage, afa_betrag_jahr, buchungen}
    """
    _init_tables()
    if jahr is None:
        jahr = date.today().year

    anlagen = get_anlagegüter(mandant_id, nur_aktive=True)
    ergebnis = []

    for anlage in anlagen:
        jahres_afa = Decimal("0")
        buchungen = []

        for monat_nr in range(1, 13):
            monat_str = f"{jahr}-{monat_nr:02d}"
            afa = berechne_afa_monat(anlage, monat_str)
            if afa > 0:
                jahres_afa += afa
                buchungen.append({
                    "monat": monat_str,
                    "betrag": float(afa),
                    "soll_konto": anlage["afa_konto"],
                    "haben_konto": anlage["gegenkonto_afa"],
                    "buchungstext": f"AfA {anlage['bezeichnung']} {monat_str}",
                })

        if jahres_afa > 0:
            ergebnis.append({
                "anlage_id":         anlage["anlage_id"],
                "bezeichnung":       anlage["bezeichnung"],
                "anschaffungskosten": anlage["anschaffungskosten"],
                "nutzungsdauer_jahre": anlage["nutzungsdauer_jahre"],
                "gwg":               bool(anlage.get("gwg")),
                "afa_betrag_jahr":   float(jahres_afa.quantize(Decimal("0.01"))),
                "soll_konto":        anlage["afa_konto"],
                "haben_konto":       anlage["gegenkonto_afa"],
                "buchungen":         buchungen,
            })

    logger.info("Jahres-AfA %d: %d Anlagen, %.2f € gesamt",
                jahr, len(ergebnis), sum(r["afa_betrag_jahr"] for r in ergebnis))
    return ergebnis


def get_anlagegüter(
    mandant_id: str | None = None,
    nur_aktive: bool = False,
) -> list[dict]:
    """Gibt alle Anlagen zurück, optional gefiltert."""
    _init_tables()
    from tools.db import get_db
    query = "SELECT * FROM anlagegüter WHERE 1=1"
    params: list = []
    if mandant_id:
        query += " AND mandant_id = ?"
        params.append(mandant_id)
    if nur_aktive:
        query += " AND aktiv = 1"
    query += " ORDER BY anschaffungsdatum DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_anlage(anlage_id: str) -> dict | None:
    _init_tables()
    from tools.db import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM anlagegüter WHERE anlage_id = ?", (anlage_id,)
        ).fetchone()
        return dict(row) if row else None


def deactivate_anlage(anlage_id: str, abgangsdatum: str | None = None) -> bool:
    """Markiert eine Anlage als abgegangen (verkauft/verschrottet)."""
    _init_tables()
    from tools.db import get_db
    datum = abgangsdatum or date.today().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE anlagegüter SET aktiv = 0, abgangsdatum = ? WHERE anlage_id = ?",
            (datum, anlage_id)
        )
    return True


def format_afa_bericht(ergebnis: list[dict], jahr: int) -> str:
    """Formatiert den Jahres-AfA-Bericht als lesbaren Text."""
    if not ergebnis:
        return f"Keine Anlagen mit AfA in {jahr}."

    lines = [
        "═" * 55,
        f"  ANLAGENBUCHHALTUNG — AfA-BERICHT {jahr}",
        "═" * 55,
        "",
    ]
    gesamt = 0.0
    for r in ergebnis:
        gwg_mark = " [GWG]" if r["gwg"] else ""
        lines.append(f"  {r['bezeichnung']}{gwg_mark}")
        lines.append(f"    AK: {r['anschaffungskosten']:>12,.2f} €  |  ND: {r['nutzungsdauer_jahre']} Jahre")
        lines.append(f"    AfA {jahr}: {r['afa_betrag_jahr']:>10,.2f} €  |  Kto {r['soll_konto']}/{r['haben_konto']}")
        lines.append("")
        gesamt += r["afa_betrag_jahr"]

    lines += [
        "─" * 55,
        f"  Gesamt AfA {jahr}:  {gesamt:>12,.2f} €",
        "═" * 55,
    ]
    return "\n".join(lines)
