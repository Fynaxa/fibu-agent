"""OCR & Datenextraktion: PDF/Bild → strukturierte Belegdaten.

Strategie:
1. PDF mit Text-Layer → pdfplumber (schnell, kostenlos)
2. Bild oder PDF ohne Text → Claude Vision API
"""
from __future__ import annotations

import base64
import json
import logging
import re
import sys
import time
from pathlib import Path

from tools.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (2, 5, 10)  # Sekunden zwischen Versuchen bei API-Fehlern


def _call_with_retry(fn, *args, **kwargs):
    """Ruft fn auf und wiederholt bei transienten Anthropic-Fehlern (429/529/500)."""
    import anthropic
    last_exc = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), 1):
        try:
            return fn(*args, **kwargs)
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIStatusError) as exc:
            last_exc = exc
            if delay is None:
                break
            logger.warning("Anthropic API Fehler (Versuch %d/%d): %s — retry in %ds",
                           attempt, len(_RETRY_DELAYS) + 1, exc, delay)
            time.sleep(delay)
        except Exception:
            raise
    raise last_exc

EXTRACTION_PROMPT = """Analysiere diesen Beleg / diese Rechnung und extrahiere die folgenden Felder.
Antworte NUR mit einem JSON-Objekt (kein Markdown, kein Text drumherum):

{
  "belegtyp": "eingangsrechnung",
  "belegdatum": "YYYY-MM-DD",
  "lieferant": "Firmenname des Rechnungsstellers",
  "rechnungsnummer": "Rechnungsnummer oder '-'",
  "nettobetrag": 0.00,
  "mwst_satz": 19.0,
  "mwst_betrag": 0.00,
  "bruttobetrag": 0.00,
  "waehrung": "EUR",
  "iban": "IBAN oder '-'",
  "verwendungszweck": "Kurzbeschreibung wofür die Rechnung ist",
  "mwst_gemischt": false,
  "mwst_positionen": null,
  "reverse_charge": false,
  "eur_betrag": null,
  "bewirtung_teilnehmer": null,
  "bewirtung_anlass": null,
  "reise_zweck": null,
  "ocr_konfidenz": 0.95
}

Regeln:
- belegtyp: Klassifiziere den Beleg als einen der folgenden Typen (exakt so schreiben):
  "eingangsrechnung"   — Standard-Lieferantenrechnung mit USt-Ausweis
  "kleinbetragsrechnung" — Bruttorechnung unter 250 EUR ohne vollständige Pflichtangaben
  "gutschrift"         — Storno/Gutschrift (Betrag negativ!)
  "anzahlungsrechnung" — Teilrechnung/Anzahlung
  "bewirtungsbeleg"    — Restaurant, Bewirtung von Geschäftspartnern
  "reisekosten"        — Hotel, Bahn, Flug, Taxi, Mietwagen
  "tankbeleg"          — Kraftstoff/Tanken
  "kassenbon"          — Kassenzettel (POS-Bon, oft ohne Rechnungsnummer)
  "eigenbeleg"         — Selbst erstellter Beleg für fehlende Originalbelege
  "reverse_charge"     — §13b UStG, keine MwSt ausgewiesen
  "eu_rechnung"        — Innergemeinschaftlicher Erwerb (EU-Ausland, keine DE-USt)
  "drittlands_rechnung" — Import aus Nicht-EU-Land
  "kreditkartenabrechnung" — Sammelabrechnung Kreditkarte
  "lohnabrechnung"     — Gehalts-/Lohnabrechnung
  "anlagenrechnung"    — Kauf von Wirtschaftsgütern (GWG-Prüfung nötig)
- bewirtung_teilnehmer: Bei bewirtungsbeleg — Namen der Teilnehmer, sonst null
- bewirtung_anlass: Bei bewirtungsbeleg — Anlass/Zweck der Bewirtung, sonst null
- reise_zweck: Bei reisekosten/tankbeleg — Reisezweck/Zielort, sonst null
- Alle Beträge als Dezimalzahlen (Punkt als Trennzeichen)
- mwst_satz: Zahl (7.0 oder 19.0). Bei steuerfrei oder Reverse Charge: 0.0. Bei MEHREREN MwSt-Sätzen: den höchsten nennen UND mwst_gemischt=true setzen
- mwst_gemischt: true wenn der Beleg sowohl 7% als auch 19% MwSt enthält (z.B. Kassenbon mit Lebensmitteln und Büromaterial)
- mwst_positionen: bei mwst_gemischt=true als Array angeben, z.B. [{"satz": 19.0, "netto": 84.03, "mwst": 15.97, "brutto": 100.00}, {"satz": 7.0, "netto": 10.28, "mwst": 0.72, "brutto": 11.00}], sonst null
- reverse_charge: true wenn § 13b UStG / "Steuerschuldnerschaft des Leistungsempfängers" / "Reverse Charge" auf dem Beleg steht
- eur_betrag: EUR-Gegenwert nur wenn die Rechnung in Fremdwährung ausgestellt ist UND ein EUR-Betrag explizit auf dem Beleg steht, sonst null
- Datum im Format YYYY-MM-DD — auch TT/MM/JJJJ, TT.MM.JJJJ, "Apr 01, 2026" korrekt umrechnen
- waehrung: IMMER die Originalwährung der Rechnung (USD, CHF, EUR etc.)
- Wenn ein Feld nicht erkennbar ist: null statt raten
- Bei Gutschriften/Storno: bruttobetrag als negative Zahl (z.B. -29.75)
- ocr_konfidenz: 0.0-1.0 wie sicher du dir bei der Extraktion bist"""

# Felder die bei Doppelextraktion übereinstimmen müssen
CRITICAL_FIELDS = ["bruttobetrag", "nettobetrag", "mwst_betrag", "belegdatum", "lieferant", "rechnungsnummer"]
# Prozentbasierte Toleranz für Betragsfelder: 0,5 % des Betrags, mindestens 10 Cent
_BETRAG_TOL_PCT = 0.005
_BETRAG_TOL_MIN = 0.10


def _extract_pdf_text(path: Path) -> str | None:
    """Versucht Text direkt aus PDF zu extrahieren."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            texts = [page.extract_text() or "" for page in pdf.pages]
        full = "\n".join(texts).strip()
        return full if len(full) > 50 else None  # zu wenig Text = gescannter Beleg
    except Exception as exc:
        logger.warning("pdfplumber failed for %s: %s", path, exc)
        return None


def _extract_via_claude_text(text: str, beleg_id: str | None = None) -> dict:
    """Extrahiert Belegdaten aus bereits vorhandenem Text via Claude."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    truncated = text[:15000]
    if len(text) > 15000:
        logger.warning("Belegtext auf 15.000 Zeichen gekürzt (Original: %d Zeichen)", len(text))
        truncated += "\n[Text gekürzt — Sammelrechnung oder mehrseitiges Dokument]"

    def _create():
        return client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": f"{EXTRACTION_PROMPT}\n\nBelegtext:\n{truncated}"}],
        )

    response = _call_with_retry(_create)

    # Kosten tracken
    try:
        from tools.cost_tracker import log_api_call
        log_api_call(beleg_id, "ocr_text", "claude-sonnet-4-6",
                     response.usage.input_tokens, response.usage.output_tokens)
    except Exception:
        pass

    return _parse_json_response(response.content[0].text)


def _extract_via_claude_vision(path: Path, beleg_id: str | None = None) -> dict:
    """Extrahiert Belegdaten aus Bild/gescanntem PDF via Claude Vision."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix in (".png",):
        media_type = "image/png"
    elif suffix in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    else:
        media_type = "image/png"

    data_b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")

    if suffix == ".pdf":
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": media_type, "data": data_b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    else:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]

    def _create():
        return client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": content}],
        )

    response = _call_with_retry(_create)

    # Kosten tracken
    try:
        from tools.cost_tracker import log_api_call
        log_api_call(beleg_id, "ocr_vision", "claude-sonnet-4-6",
                     response.usage.input_tokens, response.usage.output_tokens)
    except Exception:
        pass

    return _parse_json_response(response.content[0].text)


def _parse_json_response(raw: str) -> dict:
    """Extrahiert das erste vollständige JSON-Objekt aus Claude-Antwort.

    Nutzt JSONDecoder.raw_decode() statt greedy-regex, damit extra content
    nach dem JSON (z.B. zweites JSON-Objekt bei Mehrseitigem PDF) keinen
    'Extra data'-Fehler auslöst.
    """
    stripped = raw.strip()
    start = stripped.find("{")
    if start == -1:
        raise ValueError(f"Kein JSON in Antwort: {stripped[:200]}")
    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(stripped, start)
    except json.JSONDecodeError:
        # Fallback: erstes {...} per Regex
        match = re.search(r"\{[\s\S]*?\}", stripped)
        if not match:
            raise ValueError(f"Kein parsebares JSON: {stripped[:200]}")
        data = json.loads(match.group())
    # Typen normalisieren
    for field in ("nettobetrag", "mwst_betrag", "bruttobetrag", "mwst_satz"):
        if data.get(field) is not None:
            try:
                data[field] = float(data[field])
            except (ValueError, TypeError):
                data[field] = None
    return data


def _normalize_string(s: str) -> str:
    """Normalisiert Strings für fuzzy-Vergleich: lowercase, Satzzeichen entfernen, Leerzeichen normieren."""
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"[,.\-/\\]", " ", str(s).lower())).strip()


def _compare_extractions(a: dict, b: dict) -> list[str]:
    """Vergleicht zwei unabhängige Extraktionen. Gibt Abweichungen zurück."""
    abweichungen = []
    for field in CRITICAL_FIELDS:
        va, vb = a.get(field), b.get(field)
        if va is None and vb is None:
            continue
        # Fehlende Werte bei Nicht-Betragsfeldern: nimm den vorhandenen Wert, kein Flag
        if field in ("lieferant", "rechnungsnummer"):
            va_s = str(va).strip() if va is not None else ""
            vb_s = str(vb).strip() if vb is not None else ""
            if not va_s or va_s == "-" or not vb_s or vb_s == "-":
                continue
            # Fuzzy-Vergleich: Satzzeichen und Whitespace normiert
            if _normalize_string(va_s) != _normalize_string(vb_s):
                abweichungen.append(f"{field}: '{va}' vs '{vb}'")
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            # Prozentbasierte Toleranz statt fixer 1-Cent-Grenze
            tol = max(_BETRAG_TOL_MIN, max(abs(va), abs(vb)) * _BETRAG_TOL_PCT)
            if abs(va - vb) > tol:
                abweichungen.append(f"{field}: {va} vs {vb}")
        elif str(va).strip().lower() != str(vb).strip().lower():
            abweichungen.append(f"{field}: '{va}' vs '{vb}'")
    return abweichungen


def _merge_extractions(a: dict, b: dict) -> dict:
    """Merged zwei übereinstimmende Extraktionen (nimmt den Wert der ersten)."""
    merged = dict(a)
    # Felder die in A leer sind, aus B nehmen
    for k, v in b.items():
        if not merged.get(k) and v:
            merged[k] = v
    return merged


def extract(path: Path, double_check: bool = True) -> dict:
    """Hauptfunktion: extrahiert Belegdaten aus PDF oder Bild.

    double_check=True: Führt zwei unabhängige Extraktionen durch und vergleicht.
    Bei Abweichungen wird ocr_konfidenz auf 0.3 gesetzt → löst Rückfrage aus.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Beleg nicht gefunden: {path}")

    # Dateiprüfung: leer, zu groß, korrupt
    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Leere Datei: {path.name} (0 Bytes)")
    if file_size > 20 * 1024 * 1024:  # 20 MB Limit
        raise ValueError(f"Datei zu groß: {path.name} ({file_size / 1024 / 1024:.1f} MB, max 20 MB)")

    # PDF-Integrität und Passwortschutz prüfen
    if path.suffix.lower() == ".pdf":
        # Passwortschutz-Check: verschlüsselte PDFs können weder per Text noch Vision gelesen werden
        raw_bytes = path.read_bytes()
        if b"/Encrypt" in raw_bytes:
            raise ValueError(
                f"PDF ist passwortgeschützt: {path.name} — "
                "Bitte unverschlüsselte Version einsenden oder Passwort entfernen (z.B. mit Adobe Acrobat)."
            )
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                if len(pdf.pages) == 0:
                    raise ValueError(f"PDF hat keine Seiten: {path.name}")
                if len(pdf.pages) > 50:
                    raise ValueError(f"PDF hat zu viele Seiten ({len(pdf.pages)}): {path.name}")
        except Exception as exc:
            if "ValueError" in type(exc).__name__:
                raise
            # pdfplumber wirft bei Passwortschutz ebenfalls Fehler — besser lesbare Meldung
            if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
                raise ValueError(f"PDF ist passwortgeschützt: {path.name}")
            raise ValueError(f"PDF kann nicht gelesen werden: {path.name} — {exc}")

    logger.info("Extrahiere: %s (%.1f KB)", path.name, file_size / 1024)

    def _single_extract() -> dict:
        if path.suffix.lower() == ".pdf":
            text = _extract_pdf_text(path)
            if text:
                logger.info("PDF-Text gefunden (%d Zeichen), nutze Text-Extraktion", len(text))
                if ANTHROPIC_API_KEY:
                    # Kassenzettel-Erkennung (#4): spezialisierter Prompt für Kassenbons
                    beleg_typ = _detect_beleg_typ(text, path)
                    if beleg_typ == "kassenzettel":
                        logger.info("Kassenzettel erkannt — nutze spezialisierten Prompt")
                        return _extract_via_claude_kassenzettel(text)
                    return _extract_via_claude_text(text)
                return _fallback_regex(text)
        if ANTHROPIC_API_KEY:
            logger.info("Nutze Claude Vision für %s", path.name)
            return _extract_via_claude_vision(path)
        raise RuntimeError(f"Kein ANTHROPIC_API_KEY gesetzt und kein Text in {path.name}")

    result_a = _single_extract()

    if not double_check or not ANTHROPIC_API_KEY:
        result_a.setdefault("ocr_konfidenz", 0.7)
        return result_a

    # Zweite unabhängige Extraktion
    logger.info("Double-Check: zweite Extraktion für %s", path.name)
    try:
        result_b = _single_extract()
    except Exception as exc:
        logger.warning("Double-Check fehlgeschlagen: %s — nutze Single-Extraktion", exc)
        result_a.setdefault("ocr_konfidenz", 0.6)
        result_a["ocr_hinweis"] = "Double-Check fehlgeschlagen"
        return result_a

    abweichungen = _compare_extractions(result_a, result_b)

    if not abweichungen:
        merged = _merge_extractions(result_a, result_b)
        # Beide Extraktionen stimmen überein → hohe Konfidenz
        base_conf = float(result_a.get("ocr_konfidenz") or 0.85)
        merged["ocr_konfidenz"] = min(base_conf + 0.1, 1.0)
        logger.info("Double-Check OK: Extraktionen stimmen überein (Konfidenz %.0f%%)",
                     merged["ocr_konfidenz"] * 100)
        return merged
    else:
        # Abweichungen → niedrige Konfidenz → wird zur Rückfrage
        logger.warning("Double-Check ABWEICHUNG: %s", abweichungen)
        result_a["ocr_konfidenz"] = 0.3
        result_a["ocr_abweichungen"] = abweichungen
        result_a["ocr_hinweis"] = f"Doppelextraktion weicht ab: {'; '.join(abweichungen)}"
        return result_a


def _detect_beleg_typ(text: str, path: Path | None = None) -> str:
    """Erkennt den Beleg-Typ anhand von Keywords und Layout (#4).

    Rückgabe: 'kassenzettel' | 'gutschrift' | 'rechnung'
    """
    t = text.lower()
    # Kassenzettel-Signale: kein Lieferantenfeld oben, nur kurze Zeilen,
    # typische Schlüsselwörter von Kassensystemen
    kassenzettel_kw = (
        "kassenzettel", "kassenbon", "quittung", "bon ", "gesamtbetrag",
        "gegeben", "rückgeld", "rückgabe", "bar bezahlt", "zahlung erhalten",
        "ec-karte", "mastercard", "visa", "kartenzahlung", "kassen-id",
        "art.-nr", "mwst a", "mwst b", "steuer a", "steuer b",
        "eur a", "eur b",  # REWE/dm Kassenbon-Format
    )
    if any(kw in t for kw in kassenzettel_kw):
        return "kassenzettel"
    if any(kw in t for kw in ("gutschrift", "storno", "credit note", "kreditnote")):
        return "gutschrift"
    return "rechnung"


KASSENZETTEL_PROMPT = """Analysiere diesen Kassenbon / Kassenzettel und extrahiere:

{
  "belegdatum": "YYYY-MM-DD",
  "lieferant": "Name des Geschäfts (z.B. 'REWE Markt', 'dm-drogerie markt')",
  "rechnungsnummer": "Kassennummer / Bon-Nummer oder '-'",
  "nettobetrag": 0.00,
  "mwst_satz": 19.0,
  "mwst_betrag": 0.00,
  "bruttobetrag": 0.00,
  "waehrung": "EUR",
  "iban": null,
  "verwendungszweck": "Kurzbeschreibung: was wurde gekauft (z.B. 'Bürobedarf dm', 'Lebensmittel REWE')",
  "mwst_gemischt": false,
  "mwst_positionen": null,
  "reverse_charge": false,
  "eur_betrag": null,
  "ocr_konfidenz": 0.90
}

Hinweise für Kassenbons:
- bruttobetrag = der auf dem Bon als "Gesamt", "Summe" oder "Total" ausgewiesene Betrag
- Bei Kassenbons mit MwSt-Aufschlüsselung (A=19%, B=7%): mwst_gemischt=true setzen und mwst_positionen befüllen
- Wenn MwSt nicht separat ausgewiesen: nettobetrag = bruttobetrag / 1.19 (angenommen 19%), mwst_betrag = bruttobetrag - nettobetrag
- Lieferantenname aus Kopf des Bons lesen (oft erste 1-3 Zeilen)
- rechnungsnummer = Bon-Nr. / Beleg-Nr. / Transaktion-Nr. — oft auf dem Bon zu finden
- Antworte NUR mit JSON, kein Markdown"""


def _extract_via_claude_kassenzettel(text: str, beleg_id: str | None = None) -> dict:
    """Spezialisierte Extraktion für Kassenbons (#4)."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _create():
        return client.messages.create(
            model="claude-haiku-4-5-20251001",  # Kassenzettel sind einfach → Haiku reicht
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": f"{KASSENZETTEL_PROMPT}\n\nKassenbon-Text:\n{text[:8000]}"
            }],
        )

    response = _call_with_retry(_create)
    try:
        from tools.cost_tracker import log_api_call
        log_api_call(beleg_id, "ocr_kassenzettel", "claude-haiku-4-5-20251001",
                     response.usage.input_tokens, response.usage.output_tokens)
    except Exception:
        pass

    return _parse_json_response(response.content[0].text)


# ─── Zeilenpositions-Extraktion (#8) ──────────────────────

POSITIONEN_PROMPT = """Extrahiere alle Einzelpositionen aus dieser Rechnung.
Antworte NUR mit einem JSON-Objekt:

{
  "positionen": [
    {
      "beschreibung": "Produktname / Leistungsbeschreibung",
      "menge": 1.0,
      "einheit": "Stk",
      "einzelpreis_netto": 0.00,
      "mwst_satz": 19.0,
      "gesamtpreis_netto": 0.00,
      "gesamtpreis_brutto": 0.00
    }
  ],
  "hat_mehrere_positionen": true,
  "gemeinsames_konto_moeglich": false,
  "empfehlung": "Kurze Empfehlung: gemeinsam oder getrennt buchen?"
}

Hinweise:
- Nur tatsächlich einzeln ausgewiesene Positionen aufführen
- Wenn nur Gesamtbeträge sichtbar: leeres Array zurückgeben
- gemeinsames_konto_moeglich=true wenn alle Positionen gleiche MwSt und ähnliche Kontoart haben
- menge kann auch 0.5 oder z.B. Stunden sein (dann einheit="h")"""


def extract_positionen(path_or_text: Path | str) -> dict:
    """Extrahiert Einzelpositionen aus einer Rechnung (#8).

    Ermöglicht positionsgenaue Buchung statt Gesamtbeleg.
    Gibt dict zurück mit 'positionen' (Liste) und 'gemeinsames_konto_moeglich'.
    """
    if not ANTHROPIC_API_KEY:
        return {"positionen": [], "hat_mehrere_positionen": False,
                "gemeinsames_konto_moeglich": True, "empfehlung": "Kein API-Key"}

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if isinstance(path_or_text, Path):
        text = _extract_pdf_text(path_or_text) or ""
        if not text:
            # Vision für gescannte Rechnungen
            result = _extract_via_claude_vision(path_or_text)
            return {"positionen": [], "hat_mehrere_positionen": False,
                    "gemeinsames_konto_moeglich": True,
                    "empfehlung": "Gescannte Rechnung — Positionen manuell prüfen"}
        content = f"{POSITIONEN_PROMPT}\n\nRechnungstext:\n{text[:12000]}"
    else:
        content = f"{POSITIONEN_PROMPT}\n\nRechnungstext:\n{str(path_or_text)[:12000]}"

    def _create():
        return client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": content}],
        )

    try:
        response = _call_with_retry(_create)
        data = _parse_json_response(response.content[0].text)
        positionen = data.get("positionen", [])
        # Beträge normalisieren
        for p in positionen:
            for feld in ("einzelpreis_netto", "gesamtpreis_netto", "gesamtpreis_brutto", "menge", "mwst_satz"):
                if p.get(feld) is not None:
                    try:
                        p[feld] = float(p[feld])
                    except (TypeError, ValueError):
                        p[feld] = 0.0
        logger.info("Positionen extrahiert: %d Positionen", len(positionen))
        return data
    except Exception as exc:
        logger.warning("Positions-Extraktion fehlgeschlagen: %s", exc)
        return {"positionen": [], "hat_mehrere_positionen": False,
                "gemeinsames_konto_moeglich": True, "empfehlung": f"Fehler: {exc}"}


def split_in_einzelbelege(beleg: dict, positionen: list[dict]) -> list[dict]:
    """Teilt einen Sammelbeleg in Einzelbelege pro Position auf (#8).

    Jede Position wird zu einem eigenen Beleg-Dict das einzeln kontiert wird.
    Gemeinsame Felder (Lieferant, Datum, IBAN) werden kopiert.
    """
    if not positionen:
        return [beleg]

    gemeinsam = {
        "lieferant": beleg.get("lieferant"),
        "belegdatum": beleg.get("belegdatum"),
        "rechnungsnummer": beleg.get("rechnungsnummer"),
        "iban": beleg.get("iban"),
        "mandant_id": beleg.get("mandant_id"),
        "waehrung": beleg.get("waehrung", "EUR"),
        "dateiname": beleg.get("dateiname"),
        "dateipfad": beleg.get("dateipfad"),
        "ist_teilbeleg": True,
        "eltern_rechnungsnummer": beleg.get("rechnungsnummer"),
    }

    einzelbelege = []
    for i, pos in enumerate(positionen, 1):
        netto = pos.get("gesamtpreis_netto") or 0.0
        brutto = pos.get("gesamtpreis_brutto") or 0.0
        mwst_satz = pos.get("mwst_satz") or 19.0
        mwst = round(netto * mwst_satz / 100, 2)

        einzelbelege.append({
            **gemeinsam,
            "verwendungszweck": pos.get("beschreibung", f"Position {i}"),
            "nettobetrag": round(netto, 2),
            "mwst_satz": mwst_satz,
            "mwst_betrag": mwst,
            "bruttobetrag": round(brutto or netto + mwst, 2),
            "position_nr": i,
            "position_menge": pos.get("menge", 1.0),
            "position_einheit": pos.get("einheit", "Stk"),
        })

    return einzelbelege


def _fallback_regex(text: str) -> dict:
    """Minimale Extraktion ohne LLM — nur als Notfallback."""
    result = {
        "belegdatum": None, "lieferant": None, "rechnungsnummer": None,
        "nettobetrag": None, "mwst_satz": None, "mwst_betrag": None,
        "bruttobetrag": None, "waehrung": "EUR", "iban": None,
        "verwendungszweck": None,
        "ocr_konfidenz": 0.4,  # Bug 2: fehlte — löste immer Rückfrage aus
    }
    # Datum
    m = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", text)
    if m:
        result["belegdatum"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # IBAN
    m = re.search(r"[A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{0,4}", text)
    if m:
        result["iban"] = m.group().replace(" ", "")
    # Bruttobetrag (letzter großer Betrag)
    amounts = re.findall(r"(\d{1,6}[,.]\d{2})\s*(?:EUR|€)", text)
    if amounts:
        result["bruttobetrag"] = float(amounts[-1].replace(".", "").replace(",", "."))
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python -m tools.ocr_extract <pfad/zur/rechnung.pdf>")
        sys.exit(1)
    result = extract(Path(sys.argv[1]))
    print(json.dumps(result, indent=2, ensure_ascii=False))
