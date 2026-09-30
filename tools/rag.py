"""RAG (Retrieval-Augmented Generation) für die Kontierung.

Sucht ähnliche vergangene Buchungen aus der DATEV-Buchungshistorie (belege-Tabelle)
und stellt sie als Few-Shot-Kontext für den LLM bereit.

Kombination aus:
1. Exact-Match: gleicher Lieferant (normiert) → höchste Priorität
2. Keyword-Search: Lieferant + Verwendungszweck LIKE-Match → zweite Wahl
3. Correction-Match: manuelle Korrekturen (kontierung_korrekturen) → dritte Wahl

Keine externen Vector-DBs nötig — alles über SQLite.
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)

_STOP_WORDS = frozenset({
    "gmbh", "ag", "kg", "ug", "ohg", "e.k.", "e.v.", "und", "the",
    "der", "die", "das", "für", "von", "bei", "mit", "auf", "aus",
    "rechnung", "invoice", "april", "mai", "juni", "juli", "august",
    "september", "oktober", "november", "dezember", "januar", "februar",
    "märz", "2024", "2025", "2026", "2027",
})


class BuchungsKontext(NamedTuple):
    lieferant: str
    verwendungszweck: str
    soll_konto: str
    bezeichnet_als: str
    quelle: str  # "belege", "korrekturen"
    bestaetigt_count: int
    relevanz: float  # 0.0 - 1.0


def _normiere(text: str) -> str:
    """Normiert Lieferantenname für Vergleich: Kleinbuchstaben, Sonderzeichen raus."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _keywords(text: str, min_len: int = 4) -> list[str]:
    """Extrahiert signifikante Keywords aus Text (ohne Stop-Words)."""
    words = _normiere(text).split()
    return [w for w in words if len(w) >= min_len and w not in _STOP_WORDS]


def retrieve_buchungskontext(
    lieferant: str,
    verwendungszweck: str = "",
    mandant_id: str | None = None,
    limit: int = 5,
) -> list[BuchungsKontext]:
    """Retrieval-Funktion: Gibt relevante vergangene Buchungen als Kontext zurück.

    Suchreihenfolge (absteigend nach Relevanz):
    1. Exakter Lieferanten-Match aus belege-Tabelle (erfolgreich exportiert)
    2. Keyword-Match aus belege-Tabelle
    3. Korrekturen aus kontierung_korrekturen (manuell bestätigte Buchungen)
    """
    kontext: list[BuchungsKontext] = []
    gesehen: set[tuple[str, str]] = set()  # Duplikat-Filter (lieferant, konto)

    try:
        from tools.db import get_db
        lieferant_norm = _normiere(lieferant)
        keywords = _keywords(lieferant + " " + verwendungszweck)

        with get_db() as conn:
            # ── 1. Exakter Lieferanten-Match aus Buchungshistorie ──
            rows = conn.execute("""
                SELECT lieferant, COALESCE(verwendungszweck, buchungstext, '') AS verwendungszweck,
                       soll_konto, COUNT(*) as cnt
                FROM belege
                WHERE LOWER(lieferant) = ?
                  AND status IN ('exportiert', 'exportiert_datev')
                  AND soll_konto IS NOT NULL
                  AND soll_konto != ''
                  {}
                GROUP BY soll_konto
                ORDER BY cnt DESC
                LIMIT ?
            """.format("AND mandant_id = ?" if mandant_id else ""),
                ([lieferant_norm, mandant_id, limit] if mandant_id
                 else [lieferant_norm, limit])
            ).fetchall()

            for r in rows:
                key = (r["lieferant"], r["soll_konto"])
                if key not in gesehen:
                    gesehen.add(key)
                    kontext.append(BuchungsKontext(
                        lieferant=r["lieferant"],
                        verwendungszweck=r["verwendungszweck"] or "",
                        soll_konto=r["soll_konto"],
                        bezeichnet_als="",
                        quelle="belege_exact",
                        bestaetigt_count=r["cnt"],
                        relevanz=0.95,
                    ))

            # ── 2. Keyword-Match wenn nicht genug Exact-Treffer ──
            if len(kontext) < limit and keywords:
                like_clause = " OR ".join(
                    ["LOWER(lieferant) LIKE ? OR LOWER(COALESCE(verwendungszweck, buchungstext, '')) LIKE ?"]
                    * len(keywords)
                )
                params_kw: list = []
                for kw in keywords:
                    params_kw += [f"%{kw}%", f"%{kw}%"]
                if mandant_id:
                    params_kw.append(mandant_id)
                params_kw.append(limit - len(kontext))

                rows_kw = conn.execute(f"""
                    SELECT lieferant,
                           COALESCE(verwendungszweck, buchungstext, '') AS verwendungszweck,
                           soll_konto, COUNT(*) as cnt
                    FROM belege
                    WHERE ({like_clause})
                      AND status IN ('exportiert', 'exportiert_datev')
                      AND soll_konto IS NOT NULL AND soll_konto != ''
                      {"AND mandant_id = ?" if mandant_id else ""}
                    GROUP BY soll_konto
                    ORDER BY cnt DESC
                    LIMIT ?
                """, params_kw).fetchall()

                for r in rows_kw:
                    key = (r["lieferant"], r["soll_konto"])
                    if key not in gesehen:
                        gesehen.add(key)
                        kontext.append(BuchungsKontext(
                            lieferant=r["lieferant"],
                            verwendungszweck=r["verwendungszweck"] or "",
                            soll_konto=r["soll_konto"],
                            bezeichnet_als="",
                            quelle="belege_keyword",
                            bestaetigt_count=r["cnt"],
                            relevanz=0.75,
                        ))

            # ── 3. Manuelle Korrekturen als Fallback ──
            if len(kontext) < limit:
                try:
                    conn.execute("""CREATE TABLE IF NOT EXISTS kontierung_korrekturen (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lieferant TEXT, verwendungszweck TEXT,
                        falsches_konto TEXT, korrektes_konto TEXT, mandant_id TEXT,
                        bestaetigt_count INTEGER DEFAULT 1, auto_regel_erstellt INTEGER DEFAULT 0,
                        erstellt_am TEXT)""")
                    suchtext = f"%{lieferant_norm[:15]}%"
                    rows_k = conn.execute("""
                        SELECT lieferant, verwendungszweck, korrektes_konto, bestaetigt_count
                        FROM kontierung_korrekturen
                        WHERE LOWER(lieferant) LIKE ? OR LOWER(verwendungszweck) LIKE ?
                        ORDER BY bestaetigt_count DESC
                        LIMIT ?
                    """, (suchtext, f"%{_normiere(verwendungszweck)[:20]}%",
                          limit - len(kontext))).fetchall()

                    for r in rows_k:
                        key = (r["lieferant"], r["korrektes_konto"])
                        if key not in gesehen:
                            gesehen.add(key)
                            kontext.append(BuchungsKontext(
                                lieferant=r["lieferant"],
                                verwendungszweck=r["verwendungszweck"] or "",
                                soll_konto=r["korrektes_konto"],
                                bezeichnet_als="",
                                quelle="korrekturen",
                                bestaetigt_count=r["bestaetigt_count"],
                                relevanz=0.60,
                            ))
                except Exception:
                    pass

    except Exception as exc:
        logger.warning("RAG-Retrieval fehlgeschlagen: %s", exc)

    # Nach Relevanz sortieren
    kontext.sort(key=lambda k: (-k.relevanz, -k.bestaetigt_count))
    return kontext[:limit]


def format_rag_block(kontext: list[BuchungsKontext]) -> str:
    """Formatiert Buchungs-Kontext als Few-Shot-Block für den LLM-Prompt."""
    if not kontext:
        return ""

    lines = ["\nVERGLEICHBARE BUCHUNGEN AUS DER DATEV-BUCHUNGSHISTORIE:"]
    for k in kontext:
        quelle_label = {
            "belege_exact": "Exakter Match",
            "belege_keyword": "Ähnlicher Lieferant",
            "korrekturen": "Korrektur vom Buchhalter",
        }.get(k.quelle, k.quelle)

        lines.append(
            f'  [{quelle_label}, {k.bestaetigt_count}x] '
            f'"{k.lieferant}" / "{k.verwendungszweck}" '
            f'→ Konto {k.soll_konto} ({k.bezeichnet_als})'
        )
    return "\n".join(lines) + "\n"
