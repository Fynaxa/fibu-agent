"""Validierung: Pflichtfelder, Betragsplausibilität, Dublettencheck."""
from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

PFLICHTFELDER = ["belegdatum", "bruttobetrag", "lieferant"]
MAX_BETRAG = 100_000.0
MWST_TOLERANZ = 0.02
MAX_ALTER_JAHRE = 5  # Belege älter als 5 Jahre → Warnung


def validate(
    beleg: dict,
    bisherige_belege: list[dict] | None = None,
    mandant_id: str | None = None,  # Fix 7
) -> dict:
    """Validiert einen Beleg. Gibt dict mit {valid: bool, fehler: [...]} zurück."""
    fehler: list[str] = []

    # Pflichtfelder
    for feld in PFLICHTFELDER:
        if not beleg.get(feld):
            fehler.append(f"Pflichtfeld '{feld}' fehlt")

    brutto = beleg.get("bruttobetrag")
    netto = beleg.get("nettobetrag")
    mwst = beleg.get("mwst_betrag")
    mwst_satz = beleg.get("mwst_satz")

    # Betragsplausibilität
    _beleg_text = " ".join([
        (beleg.get("verwendungszweck") or ""),
        (beleg.get("rechnungsnummer") or ""),
        (beleg.get("lieferant") or ""),
        (beleg.get("buchungstext") or ""),
    ]).lower()
    is_gutschrift = any(kw in _beleg_text
                        for kw in ("gutschrift", "storno", "credit note", "credit memo",
                                   "gs-", "kreditnote", "rückerstattung", "refund"))
    if brutto is not None:
        if brutto == 0:
            fehler.append("Bruttobetrag ist 0")
        elif brutto < 0 and not is_gutschrift:
            fehler.append(f"Bruttobetrag {brutto} negativ — kein Gutschrift-/Storno-Kennzeichen erkannt")
        if abs(brutto) > MAX_BETRAG:
            fehler.append(f"Bruttobetrag {abs(brutto)} > {MAX_BETRAG} — verdächtig hoch")

    # Fix 13: Datumsvalidierung
    belegdatum_str = beleg.get("belegdatum")
    if belegdatum_str:
        try:
            belegdatum = datetime.strptime(belegdatum_str, "%Y-%m-%d").date()
            heute = date.today()
            if belegdatum > heute:
                fehler.append(f"Belegdatum {belegdatum_str} liegt in der Zukunft")
            elif (heute - belegdatum).days > MAX_ALTER_JAHRE * 365:
                fehler.append(
                    f"Belegdatum {belegdatum_str} ist älter als {MAX_ALTER_JAHRE} Jahre — "
                    "bitte prüfen ob Beleg korrekt ist"
                )
        except ValueError:
            fehler.append(f"Ungültiges Datumsformat: '{belegdatum_str}' (erwartet YYYY-MM-DD)")

    # MwSt-Plausibilität — nur bei einheitlichem MwSt-Satz
    mwst_gemischt = beleg.get("mwst_gemischt", False)
    if netto and mwst_satz and mwst is not None and not mwst_gemischt:
        expected_mwst = netto * mwst_satz / 100
        if expected_mwst > 0 and abs(mwst - expected_mwst) / expected_mwst > MWST_TOLERANZ:
            fehler.append(
                f"MwSt-Abweichung: erwartet {expected_mwst:.2f}, extrahiert {mwst:.2f}"
            )

    # Brutto = Netto + MwSt
    if brutto is not None and netto is not None and mwst is not None and not mwst_gemischt:
        expected_brutto = netto + mwst
        if abs(brutto) > 0 and abs(brutto - expected_brutto) / abs(brutto) > MWST_TOLERANZ:
            fehler.append(
                f"Brutto-Abweichung: Netto {netto:.2f} + MwSt {mwst:.2f} = {expected_brutto:.2f}, "
                f"extrahiert: {brutto:.2f}"
            )

    # Soll-Konto darf nicht gleich Haben-Konto sein
    soll = beleg.get("soll_konto")
    haben = beleg.get("haben_konto")
    if soll and haben and soll == haben:
        fehler.append(f"Soll-Konto = Haben-Konto ({soll}) — Buchungssatz ungültig")

    # Fix 12: Anzahlungsrechnungen erkennen → Rückfrage
    anzahlungs_kw = ("anzahlung", "vorauszahlung", "abschlagsrechnung", "teilrechnung",
                     "schlussrechnung", "restrechnung", "final invoice", "deposit invoice")
    if any(kw in _beleg_text for kw in anzahlungs_kw):
        fehler.append(
            "Anzahlungs-/Schlussrechnung erkannt — bitte manuell prüfen ob Gegenbuchung "
            "bereits existiert (Doppelbuchungsgefahr)"
        )

    # Duplikatcheck — in-memory (aktueller Run)
    if bisherige_belege:
        for alt in bisherige_belege:
            if (
                alt.get("rechnungsnummer")
                and alt["rechnungsnummer"] == beleg.get("rechnungsnummer")
                and alt.get("lieferant") == beleg.get("lieferant")
                and alt.get("bruttobetrag") == brutto
            ):
                fehler.append(f"Duplikat: RE {beleg.get('rechnungsnummer')} von {beleg.get('lieferant')}")
                break

    # Cross-Run-Duplikatcheck via SQLite — Fix 7: mandant_id, Fix 15: Fremdwährung
    if beleg.get("rechnungsnummer") and beleg.get("lieferant") and brutto:
        try:
            from tools.db import check_duplikat
            if check_duplikat(
                beleg["rechnungsnummer"],
                beleg["lieferant"],
                brutto,
                mandant_id=mandant_id,
                waehrung=beleg.get("waehrung", "EUR"),
            ):
                fehler.append(
                    f"Cross-Run-Duplikat: RE {beleg['rechnungsnummer']} von "
                    f"{beleg['lieferant']} bereits verarbeitet"
                )
        except Exception:
            pass

    # Kontierung vorhanden?
    if not beleg.get("soll_konto"):
        fehler.append("Soll-Konto fehlt (Kontierung nicht erfolgt)")

    is_valid = len(fehler) == 0
    if not is_valid:
        logger.warning("Validierung fehlgeschlagen für %s: %s", beleg.get("lieferant"), fehler)
    else:
        logger.info("Validierung OK: %s %.2f %s",
                    beleg.get("lieferant"), abs(brutto or 0), beleg.get("waehrung", "EUR"))

    return {"valid": is_valid, "fehler": fehler}
