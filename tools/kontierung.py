"""Kontierung: regelbasiert (SKR03) + LLM-Fallback via Claude."""
from __future__ import annotations

import json
import logging
import re
import time

from tools.config import ANTHROPIC_API_KEY, KONFIDENZ_SCHWELLE, load_rules

_RETRY_DELAYS = (2, 5, 10)


def _call_with_retry(fn, *args, **kwargs):
    """Wiederholt API-Aufruf bei transienten Fehlern."""
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

logger = logging.getLogger(__name__)


def _regel_match(beleg: dict, rules: list[dict]) -> dict | None:
    """Matcht Lieferant + Verwendungszweck gegen Kontierungsregeln.

    Findet ALLE Matches und wählt das längste (spezifischste) Pattern.
    So gewinnt 'google ads' (10 Zeichen) über 'google' (6 Zeichen).
    """
    suchtext = " ".join([
        (beleg.get("lieferant") or ""),
        (beleg.get("verwendungszweck") or ""),
    ]).lower()

    best_match = None
    best_pattern_len = 0

    for rule in rules:
        for pattern in rule["patterns"]:
            if pattern in suchtext and len(pattern) > best_pattern_len:
                best_pattern_len = len(pattern)
                best_match = {
                    "soll_konto": rule["soll_konto"],
                    "bezeichnung": rule["bezeichnung"],
                    "haben_konto": "1000" if re.search(r"\b(bar|kasse)\b", suchtext) else "1200",
                    "steuerschluessel": rule["mwst_schluessel"],
                    "methode": "regel",
                    "konfidenz": 0.95,
                    "match_pattern": pattern,
                }

    return best_match


_REQUIRED_LLM_FIELDS: dict[str, type | tuple] = {
    "soll_konto": str,
    "bezeichnung": str,
    "haben_konto": str,
    "steuerschluessel": str,
    "konfidenz": (int, float),
}


def _validate_llm_result(result: dict) -> list[str]:
    """Prüft Pflichtfelder, Typen und Wertebereich der LLM-Antwort."""
    fehler = []
    for feld, typ in _REQUIRED_LLM_FIELDS.items():
        val = result.get(feld)
        if val is None:
            fehler.append(f"'{feld}' fehlt")
        elif not isinstance(val, typ):
            fehler.append(f"'{feld}' falscher Typ ({type(val).__name__})")
    soll = str(result.get("soll_konto", ""))
    if soll and not re.match(r"^\d{4,5}$", soll):
        fehler.append(f"soll_konto '{soll}' keine 4-5-stellige Zahl")
    konfidenz = result.get("konfidenz")
    if konfidenz is not None:
        try:
            if not (0.0 <= float(konfidenz) <= 1.0):
                fehler.append(f"konfidenz {konfidenz} außerhalb [0,1]")
        except (TypeError, ValueError):
            fehler.append(f"konfidenz '{konfidenz}' nicht numerisch")
    return fehler


_KONTEN_REFERENZ = {
    "SKR03": (
        "4920=Telefon, 4930=Bürobedarf, 4964=EDV/Software, 4660=Reisekosten AN, "
        "4670=Reisekosten Inhaber, 4210=Miete, 4650=Bewirtung, 4600=Werbung, "
        "4945=Fortbildung, 4952=Unternehmensberatung, 4955=Steuerberatung, "
        "4970=Bankgebühren, 0650=GWG/Hardware, 4530=KFZ/Tanken, "
        "4815=Versicherungen, 1787=Umsatzsteuer §13b"
    ),
    "SKR04": (
        "6815=Telefon, 6830=Bürobedarf, 6848=EDV/Software, 6610=Reisekosten AN, "
        "6620=Reisekosten Inhaber, 6300=Miete, 6650=Bewirtung, 6200=Werbung, "
        "6855=Fortbildung/Beratung, 6825=Unternehmensberatung, 6320=KFZ-Kosten, "
        "6855=Steuerberatung, 6855=Bankgebühren, 0480=GWG/Hardware, "
        "6400=Versicherungen, 3800=Umsatzsteuer §13b"
    ),
}


def _vendor_cache_lookup(beleg: dict, kontenrahmen: str = "SKR03") -> dict | None:
    """Fast-Path via Vendor-Cache (#6). Überspringt Regelwerk + LLM für bekannte Lieferanten.

    Vertrauenslieferanten (#18): nach VERTRAUENS_SCHWELLE Bestätigungen automatisch
    mit konfidenz=0.98 und ohne rueckfrage-Flag zurückgegeben.
    """
    lieferant = (beleg.get("lieferant") or "").strip()
    if not lieferant or lieferant.lower() in ("unbekannt", "unknown", ""):
        return None
    try:
        from tools.db import get_vendor_cache
        cached = get_vendor_cache(lieferant, beleg.get("mandant_id"))
        if not cached or not cached.get("soll_konto"):
            return None

        is_trusted = bool(cached["ist_vertrauenslieferant"])
        suchtext = lieferant.lower()
        result = {
            "soll_konto": cached["soll_konto"],
            "bezeichnung": cached["bezeichnung"],
            "haben_konto": "1000" if re.search(r"\b(bar|kasse)\b", suchtext) else "1200",
            "steuerschluessel": cached["steuerschluessel"],
            "methode": "vendor_cache",
            "konfidenz": 0.98 if is_trusted else 0.92,
            "vendor_bestaetigt_count": cached["bestaetigt_count"],
        }
        logger.info(
            "Vendor-Cache-Hit: '%s' → %s (bestaetigt: %d%s)",
            lieferant, cached["soll_konto"], cached["bestaetigt_count"],
            ", VERTRAUENSLIEFERANT — auto-approve" if is_trusted else "",
        )
        return result
    except Exception as exc:
        logger.debug("Vendor-Cache-Lookup fehlgeschlagen: %s", exc)
        return None


def _ist_komplex(beleg: dict) -> bool:
    """Haiku reicht für Standardbelege. Sonnet nur bei echten Sonderfällen."""
    if beleg.get("reverse_charge"):
        return True
    if beleg.get("mwst_gemischt"):
        return True
    if beleg.get("mwst_satz") not in (0, 7, 19, None):
        return True
    lieferant = beleg.get("lieferant", "")
    if not lieferant or lieferant.lower() in ("unbekannt", "unknown", ""):
        return True
    return False


def _llm_kontierung(beleg: dict, kontenrahmen: str = "SKR03", belegtyp: str = "eingangsrechnung") -> dict:
    """Fragt Claude nach der passenden Kontierung."""
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY nicht gesetzt — LLM-Kontierung übersprungen")
        return {
            "soll_konto": "",
            "bezeichnung": "",
            "haben_konto": "1200",
            "steuerschluessel": "",
            "methode": "llm",
            "konfidenz": 0.0,
            "hinweis": "Kein API-Key — manuelle Kontierung nötig",
        }

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    beleg_text = (
        f"Belegtyp: {belegtyp}\n"
        f"Lieferant: {beleg.get('lieferant', 'unbekannt')}\n"
        f"Rechnungsnummer: {beleg.get('rechnungsnummer', '-')}\n"
        f"Belegdatum: {beleg.get('belegdatum', '-')}\n"
        f"Nettobetrag: {beleg.get('nettobetrag', '-')} EUR\n"
        f"MwSt-Satz: {beleg.get('mwst_satz', '-')}%\n"
        f"Bruttobetrag: {beleg.get('bruttobetrag', '-')} EUR\n"
        f"Verwendungszweck: {beleg.get('verwendungszweck', '-')}\n"
    )
    if beleg.get("bewirtung_teilnehmer"):
        beleg_text += f"Bewirtung Teilnehmer: {beleg['bewirtung_teilnehmer']}\n"
    if beleg.get("bewirtung_anlass"):
        beleg_text += f"Bewirtung Anlass: {beleg['bewirtung_anlass']}\n"
    if beleg.get("reise_zweck"):
        beleg_text += f"Reisezweck: {beleg['reise_zweck']}\n"

    # RAG: Ähnliche vergangene Buchungen aus der DATEV-Buchungshistorie laden (#1)
    few_shot_block = ""
    try:
        from tools.rag import retrieve_buchungskontext, format_rag_block
        rag_kontext = retrieve_buchungskontext(
            beleg.get("lieferant", ""),
            beleg.get("verwendungszweck", ""),
            mandant_id=beleg.get("mandant_id"),
        )
        few_shot_block = format_rag_block(rag_kontext)
    except Exception:
        pass

    # Feedback-Loop: Manuelle Korrekturen als Few-Shot-Beispiele in den Prompt injizieren
    try:
        from tools.db import get_aehnliche_korrekturen
        korrekturen = get_aehnliche_korrekturen(
            beleg.get("lieferant", ""),
            beleg.get("verwendungszweck") or beleg.get("buchungstext") or "",
            mandant_id=beleg.get("mandant_id"),
        )
        if korrekturen:
            korr_lines = []
            for k in korrekturen[:3]:
                korr_lines.append(
                    f"  - Lieferant '{k['lieferant']}': manuell korrigiert auf Konto {k['korrektes_konto']}"
                    f" (von Konto {k.get('falsches_konto','?')}) — {k['bestaetigt_count']}x bestätigt"
                )
            few_shot_block += (
                "\n\nMANUELLE KORREKTUREN (ähnliche Belege, vom Buchhalter bestätigt):\n"
                + "\n".join(korr_lines)
                + "\nDiese Korrekturen haben höchste Priorität gegenüber allgemeinen Regeln.\n"
            )
    except Exception:
        pass

    kr = kontenrahmen.upper()
    konten_liste = _KONTEN_REFERENZ.get(kr, _KONTEN_REFERENZ["SKR03"])
    reverse_charge_hinweis = ""
    if beleg.get("reverse_charge") or belegtyp == "reverse_charge":
        if beleg.get("rc_bauleistung"):
            reverse_charge_hinweis = (
                "\nACHTUNG: §13b Abs. 2 Nr. 4 UStG (BAULEISTUNG) — "
                "Steuerschlüssel 84 (DATEV)! Empfänger schuldet USt. "
                "Gegenbuchung: 1576 VSt §13b / 3837 USt §13b.\n"
            )
        else:
            reverse_charge_hinweis = (
                "\nACHTUNG: §13b Abs. 1 UStG Reverse Charge (digitale/sonstige Leistung) — "
                "Steuerschlüssel 21. Empfänger schuldet USt. Kein Vorsteuerabzug aus dieser Rechnung!\n"
            )

    belegtyp_hinweis = ""
    if belegtyp == "bewirtungsbeleg":
        belegtyp_hinweis = (
            "\nBEWIRTUNGSBELEG: Konto 4650 (SKR03) bzw. 6650 (SKR04). "
            "NUR 70% steuerlich abzugsfähig (§4 Abs.5 Nr.2 EStG). "
            "Steuerschlüssel 9 (19% Vorsteuer nur zu 70% abziehbar).\n"
        )
    elif belegtyp == "tankbeleg":
        belegtyp_hinweis = "\nTANKBELEG: Konto 4530 (SKR03) KFZ-Betriebskosten/Kraftstoff.\n"
    elif belegtyp in ("reisekosten", "hotel"):
        belegtyp_hinweis = "\nREISEKOSTEN: Konto 4660 (AN, SKR03) oder 4670 (Inhaber, SKR03). Übernachtung: 4666.\n"
    elif belegtyp == "kleinbetragsrechnung":
        belegtyp_hinweis = "\nKLEINBETRAGSRECHNUNG (unter 250 EUR): Normale Kontierung, Vorsteuer nur wenn USt-ID vorhanden.\n"
    elif belegtyp == "gutschrift":
        belegtyp_hinweis = "\nGUTSCHRIFT/STORNO: haben_konto bleibt 1200, soll_konto wie Originalrechnung. Betrag ist negativ.\n"
    elif belegtyp == "eu_rechnung":
        belegtyp_hinweis = (
            "\nINNERGEMEINSCHAFTLICHER ERWERB (§ 1a UStG): "
            "Kontiere den Aufwand auf dem richtigen Aufwandskonto (4xxx). "
            "Steuerschlüssel 0 — Erwerbsteuer 19% wird in USt-VA Zeile 26+27 selbst angemeldet. "
            "Zusatzbuchung: 3425 Erwerbsteuer Soll / 1787 Verbindlichkeit USt Haben (SKR03). "
            "Vorsteuerabzug aus IgE nur bei Vollunternehmer möglich.\n"
        )
    elif belegtyp == "anlagenrechnung":
        belegtyp_hinweis = (
            "\nANLAGENRECHNUNG: Prüfe GWG-Grenze (§ 6 Abs. 2 EStG). "
            "≤ 800 EUR netto → 0650 (GWG/Sofortabschreibung). "
            "> 800 EUR netto → Anlagekonto nach Art (0320=Maschinen, 0410=EDV, 0490=BGA). "
            "ACHTUNG bei exakt 800 EUR: ist KEIN Grenzfall — GWG gilt bis 800 EUR EINSCHLIESSLICH.\n"
        )
    elif belegtyp == "lohnabrechnung":
        belegtyp_hinweis = (
            "\nLOHNABRECHNUNG: Bruttolohn → 4110 (SKR03). "
            "AG-Anteile SV → 4130. Kein Vorsteuerabzug (steuerfreie Leistung).\n"
        )
    elif belegtyp == "kreditkartenabrechnung":
        belegtyp_hinweis = (
            "\nKREDITKARTENABRECHNUNG: Sammelbeleg — kontiere auf Debitorenkonto "
            "oder direkt auf jeweilige Aufwandskonten je Einzelposition.\n"
        )
    elif belegtyp == "anzahlungsrechnung":
        belegtyp_hinweis = (
            "\nANZAHLUNGSRECHNUNG: Konto 1590 (geleistete Anzahlungen, SKR03). "
            "KEIN Aufwandskonto — erst bei Lieferung/Leistung umbuchen! "
            "VSt auf Anzahlung sofort abziehbar (§ 15 Abs. 1 UStG).\n"
        )
    elif belegtyp == "kassenbon":
        belegtyp_hinweis = (
            "\nKASSENBON (Kleinbetragsrechnung <250 EUR): "
            "Keine USt-ID nötig. Aufwandskonto je Art (4650=Bewirtung, 4820=Porto/Büro). "
            "Vorsteuer nur abziehbar wenn MwSt-Betrag auf Bon ausgewiesen.\n"
        )

    # Zusätzliche Kontext-Hinweise (keyword-basiert, belegtyp-unabhängig)
    _bt = beleg_text.lower()
    if beleg.get("is_leasing") or any(kw in _bt for kw in ("leasing", "leasingrate")):
        belegtyp_hinweis += (
            "\nLEASING-WARNUNG: KEIN Anlagenkonto (0xxx)! "
            "Leasingraten = laufender Aufwand. KFZ-Leasing → 4570 (SKR03). "
            "Allg. Leasing → 4576. NIEMALS aktivieren!\n"
        )
    if any(kw in _bt for kw in ("notar", "grundstück", "beurkundung", "grunderwerbsteuer", "kaufpreis grundstück")):
        belegtyp_hinweis += (
            "\nNOTAR/IMMOBILIEN: Anschaffungsnebenkosten → AKTIVIEREN auf Anlagenkonto, "
            "KEIN Aufwandskonto! Immobilie: 0100-0199. "
            "Erst AbA/AfA nach Aktivierung möglich.\n"
        )
    if any(kw in _bt for kw in ("jahresprämie", "jahresgebühr", "versicherungszeitraum", "gültig bis", "laufzeit")):
        belegtyp_hinweis += (
            "\nJAHRESBEITRAG/VERSICHERUNG: Rechnungsabgrenzungsposten (RAP) prüfen! "
            "Anteil der auf nächstes Geschäftsjahr entfällt → 1300 aktiver RAP (SKR03). "
            "Versicherungssteuer: kein Vorsteuerabzug (§ 4 Nr. 10 UStG).\n"
        )

    prompt = f"""Du bist ein erfahrener Buchhalter. Kontiere den folgenden Beleg nach {kr}.
Antworte NUR mit einem JSON-Objekt — keine Erklärungen, kein Markdown davor oder danach.

{beleg_text}{few_shot_block}{reverse_charge_hinweis}{belegtyp_hinweis}
Häufige {kr}-Konten zur Orientierung:
{konten_liste}

JSON-Format (exakt einhalten):
{{
  "soll_konto": "<4-5-stellige {kr}-Kontonummer>",
  "bezeichnung": "<offizielle {kr}-Kontobezeichnung>",
  "haben_konto": "1200",
  "steuerschluessel": "<0, 8, 9 oder 21 bei Reverse Charge>",
  "konfidenz": <0.0-1.0>,
  "begruendung": "<ein Satz>"
}}

Steuerschlüssel: 9=19% VSt, 8=7% VSt, 0=steuerfrei/kein MwSt-Ausweis, 21=§13b Reverse Charge.
Konfidenz: 0.95=sicher, 0.75=wahrscheinlich, 0.5=unklar."""

    # Strukturiertes Output-Schema (#5) — erzwingt valides JSON via tool_use
    model = "claude-sonnet-4-6" if _ist_komplex(beleg) else "claude-haiku-4-5-20251001"
    kontierung_tool = {
        "name": "kontierung_ausgeben",
        "description": f"Gibt die korrekte Kontierung nach {kr} aus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "soll_konto": {
                    "type": "string",
                    "description": f"4-5-stellige {kr}-Kontonummer, nur Ziffern",
                },
                "bezeichnung": {
                    "type": "string",
                    "description": f"Offizielle {kr}-Kontobezeichnung",
                },
                "haben_konto": {
                    "type": "string",
                    "description": "Gegenkonto: 1200=Bank (Standard), 1000=Kasse",
                },
                "steuerschluessel": {
                    "type": "string",
                    "description": "9=19% VSt, 8=7% VSt, 0=steuerfrei, 21=§13b RC",
                },
                "konfidenz": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "0.95=sicher, 0.75=wahrscheinlich, 0.5=unklar",
                },
                "begruendung": {
                    "type": "string",
                    "description": "Kurze Begründung der Kontierung (ein Satz)",
                },
            },
            "required": ["soll_konto", "bezeichnung", "haben_konto", "steuerschluessel", "konfidenz"],
        },
    }

    try:
        def _create():
            return client.messages.create(
                model=model,
                max_tokens=600,
                temperature=0,
                tools=[kontierung_tool],
                tool_choice={"type": "tool", "name": "kontierung_ausgeben"},
                messages=[{"role": "user", "content": prompt}],
            )
        response = _call_with_retry(_create)

        # Tool-Use Antwort auslesen — kein Regex-Hack mehr nötig (#5)
        result = None
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "kontierung_ausgeben":
                result = dict(block.input)
                break

        if result is None:
            raise ValueError("Kein tool_use Block in Antwort — Model hat Tool nicht aufgerufen")

        val_fehler = _validate_llm_result(result)
        if val_fehler:
            logger.warning("Tool-Antwort unvollständig (%s): %s", beleg.get("lieferant"), val_fehler)
            result.setdefault("soll_konto", "")
            result.setdefault("bezeichnung", "")
            result.setdefault("haben_konto", "1200")
            result.setdefault("steuerschluessel", "")
            result["konfidenz"] = 0.3
            result["hinweis"] = f"Unvollständige Tool-Antwort: {'; '.join(val_fehler)}"
        result["methode"] = "llm"
        result["llm_model"] = model
        result["konfidenz"] = float(result.get("konfidenz", 0.5))
        return result
    except Exception as exc:
        logger.exception("LLM-Kontierung fehlgeschlagen: %s", exc)
        return {
            "soll_konto": "",
            "bezeichnung": "",
            "haben_konto": "1200",
            "steuerschluessel": "",
            "methode": "llm",
            "konfidenz": 0.0,
            "hinweis": f"LLM-Fehler: {exc}",
        }


def auto_regelwerk_aktualisieren(kontenrahmen: str = "SKR03") -> int:
    """Überprüft ob neue Korrekturen ins Regelwerk aufgenommen werden können.

    Korrekturen die >= 3x bestätigt wurden werden als neues Pattern in die
    JSON-Regeldatei geschrieben. Gibt Anzahl neu hinzugefügter Regeln zurück.
    """
    try:
        from tools.db import get_korrekturen_fuer_regelwerk, mark_korrektur_als_regel
        from tools.config import ROOT
    except Exception:
        return 0

    kandidaten = get_korrekturen_fuer_regelwerk(min_bestaetigt=3)
    if not kandidaten:
        return 0

    rules_path = ROOT / "workflows" / f"{kontenrahmen.lower()}_rules.json"
    try:
        rules: list[dict] = json.loads(rules_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    # Bestehende Konto-Einträge indexieren für Zusammenführung
    konto_index: dict[str, int] = {r["soll_konto"]: i for i, r in enumerate(rules)}
    neue_regeln = 0

    for k in kandidaten:
        lieferant = k["lieferant"].lower().strip()
        verwendung = k["verwendungszweck"].lower().strip()
        konto = k["korrektes_konto"]

        # Neues Pattern aus Lieferant ableiten (Kurzform, max 20 Zeichen)
        pattern = lieferant[:20].strip()

        if konto in konto_index:
            # Bestehendes Konto-Pattern erweitern
            idx = konto_index[konto]
            if pattern not in rules[idx]["patterns"]:
                rules[idx]["patterns"].append(pattern)
                logger.info("Auto-Regel: Pattern '%s' zu Konto %s hinzugefügt", pattern, konto)
                neue_regeln += 1
        else:
            # Neue Regel erstellen
            rules.append({
                "patterns": [pattern],
                "soll_konto": konto,
                "bezeichnung": f"Auto-Regel: {k['lieferant'][:40]}",
                "mwst_schluessel": "9",  # Standard; Buchhalter kann anpassen
            })
            konto_index[konto] = len(rules) - 1
            logger.info("Auto-Regel: Neue Regel für Konto %s mit Pattern '%s'", konto, pattern)
            neue_regeln += 1

        mark_korrektur_als_regel(k["id"])

    if neue_regeln > 0:
        tmp = rules_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(rules_path)
        logger.info("Regelwerk aktualisiert: %d neue Pattern in %s", neue_regeln, rules_path.name)

    return neue_regeln


_GWG_KONTEN = {
    "SKR03": {"gwg": "0650", "edv_anlage": "0655", "buero_anlage": "0420"},
    "SKR04": {"gwg": "0480", "edv_anlage": "0440", "buero_anlage": "0440"},
}


def _gwg_korrekt(result: dict, beleg: dict, kontenrahmen: str = "SKR03") -> dict:
    """GWG-Grenze prüfen und Konto ggf. korrigieren (SKR03 + SKR04).

    § 6 Abs. 2 EStG: ≤ 800 EUR netto → GWG, > 800 EUR → Anlagevermögen.
    """
    kr = kontenrahmen.upper()
    konten = _GWG_KONTEN.get(kr, _GWG_KONTEN["SKR03"])
    if result.get("soll_konto") not in (konten["gwg"], konten["buero_anlage"]):
        return result

    netto = beleg.get("nettobetrag")
    if netto is None:
        brutto = beleg.get("bruttobetrag") or 0
        mwst_satz = beleg.get("mwst_satz") or 19
        netto = brutto / (1 + mwst_satz / 100) if brutto else 0

    if netto > 800:
        altes_konto = result["soll_konto"]
        if altes_konto == konten["gwg"]:
            result["soll_konto"] = konten["edv_anlage"]
            result["bezeichnung"] = f"EDV-Anlagen {kr} (Netto > 800 EUR, kein GWG)"
        else:
            result["soll_konto"] = konten["buero_anlage"]
            result["bezeichnung"] = f"Anlagevermögen {kr} (Netto > 800 EUR)"
        result["konfidenz"] = 0.90
        logger.info(
            "GWG-Grenze überschritten: %s EUR netto → Konto %s statt %s (%s)",
            round(netto, 2), result["soll_konto"], altes_konto, kr,
        )

    return result


def _reverse_charge_korrekt(result: dict, beleg: dict, kontenrahmen: str = "SKR03") -> dict:
    """Reverse Charge → Steuerschlüssel differenziert nach §13b-Absatz."""
    if not beleg.get("reverse_charge"):
        return result
    if beleg.get("rc_bauleistung"):
        # §13b Abs. 2 Nr. 4 UStG — Bauleistungen: DATEV SK 84
        result["steuerschluessel"] = "84"
        result["rc_hinweis"] = "§13b Abs. 2 Nr. 4 UStG (Bauleistung) — DATEV SK 84"
        logger.info("[%s] §13b Bauleistung → Steuerschlüssel 84", beleg.get("rechnungsnummer", "?"))
    else:
        # §13b Abs. 1 UStG — digitale/sonstige Leistungen: DATEV SK 21
        result["steuerschluessel"] = "21"
        logger.info("[%s] §13b Abs. 1 → Steuerschlüssel 21", beleg.get("rechnungsnummer", "?"))
    result["konfidenz"] = min(result.get("konfidenz", 0.9), 0.9)
    return result


def _plausi_check(result: dict, beleg: dict, kontenrahmen: str = "SKR03") -> dict:
    """Plausibilitätsprüfung nach Kontierung — fängt grobe LLM-Fehler ab.

    Check 1: Eingangsrechnung darf nicht auf Erlöskonto gebucht werden.
    Check 2: MwSt-Satz muss mit Steuerschlüssel übereinstimmen.
    """
    soll = str(result.get("soll_konto") or "")
    schluessel = str(result.get("steuerschluessel") or "")
    kr = kontenrahmen.upper()
    fehler: list[str] = []

    # 1. Belegart-Check: Eingangsrechnung → kein Erlöskonto
    # SKR03 Erlöse: 8xxx; SKR04 Erlöse: 4xxx (Achtung: in SKR04 4xxx auch Aufwand → nur 40xx-44xx)
    if soll:
        haben = str(result.get("haben_konto") or beleg.get("haben_konto") or "")
        ist_ausgangsrechnung = (
            haben.startswith("8")                          # haben_konto auf Erlöskonto
            or str(beleg.get("beleg_id", "")).startswith(("AR-", "DEMO-E", "DEMO2-E"))
        )
        erloes_prefix = "8" if kr == "SKR03" else ""
        if erloes_prefix and soll.startswith(erloes_prefix) and not ist_ausgangsrechnung:
            fehler.append(
                f"Eingangsrechnung auf Erlöskonto {soll} — "
                f"SKR03 Erlöskonten (8xxx) sind für Ausgangsrechnungen reserviert."
            )
            logger.warning(
                "Plausi-Check: Erlöskonto %s für '%s' (kein AR) → Rückfrage",
                soll, beleg.get("lieferant", "?"),
            )

    # 2. MwSt ↔ Steuerschlüssel Konsistenz
    # SK 21 = EU Reverse Charge (IgE), SK 84 = §13b Bauleistung — beide sind VSt-neutral, kein MwSt-Check
    mwst = beleg.get("mwst_satz")
    if mwst is not None and schluessel not in ("", "21", "84"):
        try:
            mwst_f = float(mwst)
            erwarteter_schluessel = "9" if mwst_f == 19 else "8" if mwst_f == 7 else "0"
            if schluessel != erwarteter_schluessel and not (mwst_f == 0 and schluessel in ("0", "")):
                fehler.append(
                    f"MwSt {mwst_f}% aber Steuerschlüssel '{schluessel}' "
                    f"(erwartet: {erwarteter_schluessel})."
                )
                logger.warning(
                    "Plausi-Check: MwSt %.0f%% ↔ Steuerschlüssel '%s' inkonsistent",
                    mwst_f, schluessel,
                )
        except (TypeError, ValueError):
            pass

    if fehler:
        result["rueckfrage"] = True
        result["konfidenz"] = min(result.get("konfidenz", 0.5), 0.2)
        existing = result.get("rueckfrage_grund") or ""
        result["rueckfrage_grund"] = (existing + " " + " | ".join(fehler)).strip()

    return result


def kontiere(beleg: dict, kontenrahmen: str = "SKR03", belegtyp: str | None = None) -> dict:
    """Kontiert einen Beleg. Lookup-Reihenfolge: Vendor-Cache → Regelwerk → LLM.

    Vertrauenslieferanten (Vendor-Cache mit ist_vertrauenslieferant=1) überspringen
    den Konfidenz-Check und werden automatisch genehmigt (#18).
    """
    if belegtyp is None:
        belegtyp = beleg.get("belegtyp", "eingangsrechnung") or "eingangsrechnung"

    # 1. Vendor-Cache — schnellster Pfad, mandant-isoliert (#6)
    result = _vendor_cache_lookup(beleg, kontenrahmen)
    if result:
        result = _gwg_korrekt(result, beleg, kontenrahmen)
        result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
        result = _plausi_check(result, beleg, kontenrahmen)
        # Vertrauenslieferanten: kein rueckfrage-Flag (#18)
        if result["konfidenz"] < KONFIDENZ_SCHWELLE and result.get("vendor_bestaetigt_count", 0) < 10:
            result["rueckfrage"] = True
        return result

    # 2. Regelwerk — deterministisch, kein API-Aufruf
    rules = load_rules(kontenrahmen)
    result = _regel_match(beleg, rules)
    if result:
        logger.info(
            "Regel-Match: '%s' → %s (%s)",
            beleg.get("lieferant"), result["soll_konto"], result["match_pattern"],
        )
        result = _gwg_korrekt(result, beleg, kontenrahmen)
        result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
        result = _plausi_check(result, beleg, kontenrahmen)
        return result

    # 3. LLM-Fallback mit strukturiertem Output (#5)
    logger.info("Kein Cache/Regel-Match für '%s' — LLM-Fallback", beleg.get("lieferant"))
    result = _llm_kontierung(beleg, kontenrahmen, belegtyp=belegtyp)
    result = _gwg_korrekt(result, beleg, kontenrahmen)
    result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
    result = _plausi_check(result, beleg, kontenrahmen)

    if result["konfidenz"] < KONFIDENZ_SCHWELLE:
        result["rueckfrage"] = True
        logger.warning(
            "Niedrige Konfidenz %.2f für '%s' — Rückfrage erforderlich",
            result["konfidenz"], beleg.get("lieferant"),
        )

    return result


def kontiere_batch(belege: list[dict], kontenrahmen: str = "SKR03") -> list[dict]:
    """Kontiert mehrere Belege effizient — nutzt einen LLM-Call für alle einfachen Fälle (#11).

    Ablauf:
    1. Cache + Regelwerk pro Beleg (kein API-Aufruf)
    2. Verbleibende einfache Belege → ein gemeinsamer LLM-Batch-Call
    3. Komplexe Belege (Reverse Charge, unbekannt) → einzelne LLM-Calls

    Reduziert API-Kosten bei Massenverarbeitung signifikant.
    """
    if not belege:
        return []

    ergebnisse: list[dict | None] = [None] * len(belege)
    llm_einfach: list[tuple[int, dict]] = []  # (index, beleg)
    llm_komplex: list[tuple[int, dict]] = []

    # Phase 1: Cache + Regelwerk (kein API-Aufruf)
    rules = load_rules(kontenrahmen)
    for i, beleg in enumerate(belege):
        result = _vendor_cache_lookup(beleg, kontenrahmen)
        if result:
            result = _gwg_korrekt(result, beleg, kontenrahmen)
            result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
            ergebnisse[i] = result
            continue

        result = _regel_match(beleg, rules)
        if result:
            logger.info("Batch Regel-Match: '%s' → %s", beleg.get("lieferant"), result["soll_konto"])
            result = _gwg_korrekt(result, beleg, kontenrahmen)
            result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
            ergebnisse[i] = result
            continue

        # LLM nötig — komplex oder einfach?
        if _ist_komplex(beleg):
            llm_komplex.append((i, beleg))
        else:
            llm_einfach.append((i, beleg))

    # Phase 2: Einfache Belege in einem Batch-Call
    if llm_einfach and ANTHROPIC_API_KEY:
        batch_results = _llm_batch_call(llm_einfach, kontenrahmen)
        for (i, beleg), result in zip(llm_einfach, batch_results):
            result = _gwg_korrekt(result, beleg, kontenrahmen)
            result = _reverse_charge_korrekt(result, beleg, kontenrahmen)
            result = _plausi_check(result, beleg, kontenrahmen)
            if result["konfidenz"] < KONFIDENZ_SCHWELLE:
                result["rueckfrage"] = True
            ergebnisse[i] = result
    elif llm_einfach:
        for i, beleg in llm_einfach:
            ergebnisse[i] = kontiere(beleg, kontenrahmen)

    # Phase 3: Komplexe Belege — einzeln
    for i, beleg in llm_komplex:
        ergebnisse[i] = kontiere(beleg, kontenrahmen)

    return [r or {} for r in ergebnisse]


def _llm_batch_call(belege_mit_index: list[tuple[int, dict]], kontenrahmen: str = "SKR03") -> list[dict]:
    """Sendet mehrere einfache Belege in einem LLM-Call und gibt sortierte Ergebnisse zurück."""
    import anthropic
    if not ANTHROPIC_API_KEY:
        return [_llm_kontierung(b, kontenrahmen) for _, b in belege_mit_index]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kr = kontenrahmen.upper()
    konten_liste = _KONTEN_REFERENZ.get(kr, _KONTEN_REFERENZ["SKR03"])

    belege_text = ""
    for seq, (_, beleg) in enumerate(belege_mit_index, 1):
        belege_text += (
            f"\n[BELEG {seq}]\n"
            f"Lieferant: {beleg.get('lieferant', 'unbekannt')}\n"
            f"Verwendungszweck: {beleg.get('verwendungszweck', '-')}\n"
            f"Brutto: {beleg.get('bruttobetrag', '-')} EUR | MwSt: {beleg.get('mwst_satz', '-')}%\n"
        )

    batch_tool = {
        "name": "batch_kontierung_ausgeben",
        "description": f"Gibt die Kontierungen für alle Belege nach {kr} aus.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kontierungen": {
                    "type": "array",
                    "description": f"Exakt {len(belege_mit_index)} Einträge, in gleicher Reihenfolge wie die Belege",
                    "items": {
                        "type": "object",
                        "properties": {
                            "soll_konto": {"type": "string"},
                            "bezeichnung": {"type": "string"},
                            "haben_konto": {"type": "string"},
                            "steuerschluessel": {"type": "string"},
                            "konfidenz": {"type": "number"},
                            "begruendung": {"type": "string"},
                        },
                        "required": ["soll_konto", "bezeichnung", "haben_konto", "steuerschluessel", "konfidenz"],
                    },
                }
            },
            "required": ["kontierungen"],
        },
    }

    prompt = (
        f"Du bist Buchhalter. Kontiere alle folgenden Belege nach {kr}.\n"
        f"Antworte mit exakt {len(belege_mit_index)} Kontierungen in gleicher Reihenfolge.\n\n"
        f"Häufige {kr}-Konten:\n{konten_liste}\n\n"
        f"Steuerschlüssel: 9=19% VSt, 8=7% VSt, 0=steuerfrei, 21=§13b RC\n"
        f"\nBELEGE:{belege_text}"
    )

    fallback = [_llm_kontierung(b, kontenrahmen) for _, b in belege_mit_index]
    try:
        def _create():
            return client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200 * len(belege_mit_index),
                temperature=0,
                tools=[batch_tool],
                tool_choice={"type": "tool", "name": "batch_kontierung_ausgeben"},
                messages=[{"role": "user", "content": prompt}],
            )

        response = _call_with_retry(_create)
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "batch_kontierung_ausgeben":
                kontierungen = block.input.get("kontierungen", [])
                if len(kontierungen) != len(belege_mit_index):
                    logger.warning(
                        "Batch: %d Ergebnisse für %d Belege — Fallback auf Einzelaufrufe",
                        len(kontierungen), len(belege_mit_index),
                    )
                    return fallback
                results = []
                for k in kontierungen:
                    k["methode"] = "llm_batch"
                    k["llm_model"] = "claude-haiku-4-5-20251001"
                    k["konfidenz"] = float(k.get("konfidenz", 0.5))
                    results.append(k)
                logger.info("Batch-Kontierung: %d Belege in einem Call", len(results))
                return results
        return fallback
    except Exception as exc:
        logger.exception("Batch-LLM-Call fehlgeschlagen: %s — Fallback", exc)
        return fallback


if __name__ == "__main__":
    demo = {
        "lieferant": "Vodafone GmbH",
        "verwendungszweck": "Mobilfunk April 2026",
        "belegdatum": "2026-04-08",
        "nettobetrag": 84.03,
        "mwst_satz": 19.0,
        "bruttobetrag": 100.00,
    }
    print("Demo-Kontierung:")
    print(json.dumps(kontiere(demo), indent=2, ensure_ascii=False))
