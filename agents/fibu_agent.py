"""FiBu-Agent: Orchestriert den gesamten Buchhaltungs-Workflow.

Belege einlesen → OCR → Kontierung → Validierung → DATEV-Export → Report
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from tools import intake, ocr_extract, kontierung, validate, datev_export, report, audit_log, db, cost_tracker, pipeline_status
from tools.config import INBOX_DIR, OUTBOX_DIR, KONFIDENZ_SCHWELLE, ROOT, get_mandant, mandant_dirs, load_mandanten

logger = logging.getLogger("fibu_agent")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


def process_beleg(path: Path, beleg_id: str, bisherige: list[dict], kontenrahmen: str = "SKR03", mandant_id: str | None = None) -> dict:
    """Verarbeitet einen einzelnen Beleg durch die gesamte Pipeline."""
    beleg: dict = {
        "id": beleg_id,
        "quelle": "watchfolder",
        "datei": str(path),
        "eingangsdatum": datetime.now().strftime("%Y-%m-%d"),
        "status": "neu",
    }

    # Audit: Eingang
    audit_log.log_event(beleg_id, "eingang", {"datei": str(path), "quelle": "watchfolder"})

    # 0. eRechnung-Check: ZUGFeRD / XRechnung (kein LLM nötig — 100% strukturierte Daten)
    try:
        from tools.erechnung import extract_erechnung
        erechnung_data = extract_erechnung(path)
        if erechnung_data:
            beleg.update(erechnung_data)
            beleg["belegtyp"] = erechnung_data.get("erechnung_format", "zugferd")
            beleg["status"] = "extrahiert"
            beleg["kontierung_methode"] = "erechnung"
            logger.info("[%s] eRechnung erkannt (%s): %s — %.2f EUR",
                        beleg_id, beleg["belegtyp"],
                        beleg.get("lieferant", "?"), beleg.get("bruttobetrag", 0) or 0)
            audit_log.log_event(beleg_id, "ocr_extraktion", {
                "methode": "erechnung",
                "format": beleg["belegtyp"],
                "ocr_konfidenz": 1.0,
            }, beleg_snapshot=beleg)
    except Exception as exc:
        logger.debug("[%s] eRechnung-Check übersprungen: %s", beleg_id, exc)

    # 1. OCR & Extraktion (mit Double-Check) — nur wenn kein eRechnung-Treffer
    if beleg.get("status") != "extrahiert":
      try:
        extracted = ocr_extract.extract(path, double_check=True)
        beleg.update(extracted)
        beleg["status"] = "extrahiert"
        logger.info("[%s] Extrahiert: %s — %.2f EUR (OCR-Konfidenz: %.0f%%)",
                     beleg_id, beleg.get("lieferant", "?"),
                     beleg.get("bruttobetrag", 0) or 0,
                     (beleg.get("ocr_konfidenz", 0) or 0) * 100)

        audit_log.log_event(beleg_id, "ocr_extraktion", {
            "methode": "double_check",
            "ocr_konfidenz": beleg.get("ocr_konfidenz"),
            "abweichungen": beleg.get("ocr_abweichungen"),
        }, beleg_snapshot=beleg)

        # OCR-Konfidenz zu niedrig → Rückfrage, BEVOR kontiert wird
        ocr_conf = beleg.get("ocr_konfidenz", 0) or 0
        if ocr_conf < KONFIDENZ_SCHWELLE:
            beleg["status"] = "rueckfrage"
            hint = beleg.get("ocr_hinweis", "OCR unsicher")
            beleg["rueckfrage"] = f"OCR-Konfidenz {ocr_conf:.0%} — Belegdaten bitte manuell prüfen: {hint}"
            logger.warning("[%s] OCR-Rückfrage: %s", beleg_id, beleg["rueckfrage"])
            audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
            return beleg
      except Exception as exc:
        logger.exception("[%s] OCR fehlgeschlagen: %s", beleg_id, exc)
        beleg["status"] = "fehler"
        beleg["rueckfrage"] = f"OCR-Fehler: {exc}"
        audit_log.log_event(beleg_id, "fehler", {"grund": str(exc)})
        return beleg

    # 1b. Belegart-Sonderregeln NACH Extraktion
    belegtyp = beleg.get("belegtyp", "eingangsrechnung") or "eingangsrechnung"

    # Volltext für Keyword-Checks (alle String-Felder)
    _beleg_volltext = " ".join(str(v) for v in beleg.values() if isinstance(v, str)).lower()

    # Belegtyp-Korrektur per Keyword-Fallback (wenn OCR falsch klassifiziert hat)
    if belegtyp != "bewirtungsbeleg" and any(kw in _beleg_volltext for kw in (
            "bewirtung", "bewirtungsbeleg", "§ 4 abs. 5", "§4 abs.5",
            "nur 70%", "teilnehmer", "anlass/geschäftszweck")):
        belegtyp = "bewirtungsbeleg"
        beleg["belegtyp"] = "bewirtungsbeleg"
        logger.info("[%s] Belegtyp per Keyword auf 'bewirtungsbeleg' korrigiert", beleg_id)

    if belegtyp != "eigenbeleg" and any(kw in _beleg_volltext for kw in (
            "eigenbeleg", "barauslage", "eigenquittung", "kein kassenbon vorhanden",
            "kein original", "selbst erstellt")):
        belegtyp = "eigenbeleg"
        beleg["belegtyp"] = "eigenbeleg"
        logger.info("[%s] Belegtyp per Keyword auf 'eigenbeleg' korrigiert", beleg_id)

    # Fremdwährung → Rückfrage (EUR-Betrag muss manuell eingetragen werden)
    waehrung = (beleg.get("waehrung") or "EUR").upper().strip()
    if waehrung not in ("EUR", "", "EURO"):
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = (
            f"Fremdwährungsrechnung ({waehrung}) — EZB-Tageskurs zum Rechnungsdatum "
            f"({beleg.get('belegdatum', '?')}) erforderlich. "
            "Bitte EUR-Betrag nachtragen bevor Buchung erfolgt."
        )
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Ungewöhnlicher MwSt-Satz → Rückfrage (deutsches Recht: nur 0%, 7%, 19%)
    mwst_satz = beleg.get("mwst_satz")
    if mwst_satz is not None:
        try:
            mwst_f = float(mwst_satz)
            if mwst_f > 0 and mwst_f not in (7.0, 19.0):
                beleg["status"] = "rueckfrage"
                beleg["rueckfrage"] = (
                    f"Ungewöhnlicher MwSt-Satz: {mwst_f}% (zulässig: 7% oder 19%). "
                    "Bitte Rechnung prüfen — ggf. Korrekturrechnung vom Lieferanten anfordern."
                )
                audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
                return beleg
        except (ValueError, TypeError):
            pass

    # Privatrechnung → Rückfrage (Rechnungsadresse Privatperson)
    if any(kw in _beleg_volltext for kw in ("privatperson", "privatrechnung", "(privat)", "privatadresse")):
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = (
            "Privatrechnung erkannt (Rechnungsadresse Privatperson) — "
            "nur buchbar wenn nachweislich betrieblich veranlasst. "
            "Andernfalls: Privatentnahme (1800) oder Gesellschafterdarlehen (1840)."
        )
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Kreditkartenabrechnung → immer Rückfrage (Sammelbeleg, Einzelpositionen nötig)
    if belegtyp == "kreditkartenabrechnung":
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = (
            "Kreditkartenabrechnung (Sammelbeleg) — Einzelpositionen müssen separat gebucht werden. "
            "Bitte Einzelquittungen zuordnen und getrennt einreichen."
        )
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Lohnabrechnung → immer Rückfrage (Mehrfachbuchung: 4110, 4130, 1741, 1742, 1743)
    if belegtyp == "lohnabrechnung":
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = (
            "Lohnabrechnung — erfordert manuelle Mehrfachbuchung: "
            "Bruttolohn (4110), AG-SV (4130), Lohnsteuer-Verbindlichkeit (1741), "
            "Nettolohn-Verbindlichkeit (1742), SV-Verbindlichkeit (1743). "
            "Bitte in Lohnbuchhaltung verarbeiten."
        )
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Leasing-Erkennung → Hinweis setzen (kein Anlagenkonto!)
    if any(kw in _beleg_volltext for kw in ("leasing", "leasingrate", "leasingnehmer", "operating lease", "finance lease")):
        beleg["is_leasing"] = True
        beleg["buchungstext_hinweis"] = (
            (beleg.get("buchungstext_hinweis") or "") +
            " | LEASING: Aufwandskonto (z.B. 4570), KEIN Anlagenkonto!"
        ).strip(" | ")
        logger.info("[%s] Leasing-Rechnung erkannt — kein Anlagenkonto", beleg_id)

    # §13b Bauleistung: Steuerschlüssel 84 statt 21 markieren
    if any(kw in _beleg_volltext for kw in ("bauleistung", "bauarbeit", "malerarbeit", "sanitär",
                                             "renovierung", "sanierung", "abs. 2 nr. 4", "abs.2 nr.4")):
        beleg["rc_bauleistung"] = True
        logger.info("[%s] §13b Abs.2 Nr.4 Bauleistung erkannt → SK 84", beleg_id)

    # Bewirtungsbeleg: 70%-Regel + Pflichtfelder
    if belegtyp == "bewirtungsbeleg":
        missing = []
        if not beleg.get("bewirtung_teilnehmer"):
            missing.append("Teilnehmer")
        if not beleg.get("bewirtung_anlass"):
            missing.append("Anlass/Geschäftszweck")
        if missing:
            beleg["status"] = "rueckfrage"
            beleg["rueckfrage"] = (
                f"Bewirtungsbeleg: Pflichtangaben fehlen ({', '.join(missing)}). "
                "Nur 70% steuerlich abzugsfähig (§ 4 Abs. 5 Nr. 2 EStG)."
            )
            audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
            return beleg
        beleg["buchungstext_hinweis"] = "Bewirtung — nur 70% abzugsfähig (§4 Abs.5 Nr.2 EStG)"

    # Eigenbeleg: immer Rückfrage
    if belegtyp == "eigenbeleg":
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = "Eigenbeleg erkannt — bitte manuell prüfen und freigeben."
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Drittlandsrechnung / EU-Rechnung: Rückfrage wenn Zollstatus unklar
    if belegtyp == "drittlands_rechnung":
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = "Drittlandsrechnung — Zoll/Einfuhrumsatzsteuer prüfen (§ 21 UStG)."
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Auslands-MwSt-Warnung: Nicht-EU-Firma weist DE-USt aus (§ 15 UStG — kein Vorsteuerabzug!)
    lieferant_str = (beleg.get("lieferant") or "").lower()
    if (beleg.get("mwst_betrag") or 0) > 0 and any(kw in _beleg_volltext for kw in
                                                      ("ltd.", "llc", "inc.", "corp.", "plc",
                                                       "wales", "united kingdom", "uk ", "england")):
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = (
            "Auslands-Unternehmen (UK/US) mit DE-MwSt-Ausweis — "
            "Vorsteuerabzug nur möglich wenn Lieferant gültig in DE für USt registriert ist. "
            "DE-USt-ID-Nummer des Lieferanten über BZSt (bzst.de) prüfen. "
            "Evtl. §13b Abs. 1 UStG zutreffend (Reverse Charge statt VSt-Abzug)."
        )
        audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
        return beleg

    # Gutschrift: Betrag muss negativ sein
    if belegtyp == "gutschrift" and beleg.get("bruttobetrag", 0) > 0:
        beleg["bruttobetrag"] = -(beleg["bruttobetrag"])
        beleg["nettobetrag"] = -(beleg.get("nettobetrag") or 0)
        beleg["mwst_betrag"] = -(beleg.get("mwst_betrag") or 0)
        logger.info("[%s] Gutschrift: Beträge auf negativ korrigiert", beleg_id)

    # 2. Kontierung
    try:
        kont = kontierung.kontiere(beleg, kontenrahmen=kontenrahmen, belegtyp=belegtyp)
        beleg["soll_konto"] = kont.get("soll_konto", "")
        beleg["haben_konto"] = kont.get("haben_konto", "1200")
        beleg["steuerschluessel"] = kont.get("steuerschluessel", "")
        beleg["kontierung_methode"] = kont.get("methode", "")
        beleg["konfidenz"] = kont.get("konfidenz", 0)
        beleg["buchungstext"] = (
            kont.get("bezeichnung", "")
            + " — "
            + (beleg.get("verwendungszweck") or beleg.get("lieferant") or "")
        )[:60]
        beleg["status"] = "kontiert"

        audit_log.log_event(beleg_id, "kontierung", {
            "methode": beleg["kontierung_methode"],
            "soll_konto": beleg["soll_konto"],
            "haben_konto": beleg["haben_konto"],
            "konfidenz": beleg["konfidenz"],
        }, beleg_snapshot=beleg)

        if kont.get("rueckfrage"):
            beleg["status"] = "rueckfrage"
            beleg["rueckfrage"] = f"Konfidenz {beleg['konfidenz']:.0%} — Konto {beleg['soll_konto']} prüfen"
            logger.warning("[%s] Rückfrage: %s", beleg_id, beleg["rueckfrage"])
            audit_log.log_event(beleg_id, "rueckfrage", {"grund": beleg["rueckfrage"]}, beleg_snapshot=beleg)
            return beleg

        logger.info("[%s] Kontiert: %s → %s (%.0f%%)",
                     beleg_id, beleg.get("lieferant"), beleg["soll_konto"], beleg["konfidenz"] * 100)
    except Exception as exc:
        logger.exception("[%s] Kontierung fehlgeschlagen: %s", beleg_id, exc)
        beleg["status"] = "fehler"
        beleg["rueckfrage"] = f"Kontierungs-Fehler: {exc}"
        audit_log.log_event(beleg_id, "fehler", {"grund": str(exc)})
        return beleg

    # 3. Validierung — Fix 7: mandant_id für isolierten Duplikat-Check
    val = validate.validate(beleg, bisherige, mandant_id=mandant_id)
    if not val["valid"]:
        beleg["status"] = "rueckfrage"
        beleg["rueckfrage"] = "; ".join(val["fehler"])
        audit_log.log_event(beleg_id, "validierung_fehler", {"fehler": val["fehler"]}, beleg_snapshot=beleg)
        return beleg

    beleg["status"] = "validiert"
    audit_log.log_event(beleg_id, "validierung_ok", {}, beleg_snapshot=beleg)

    # Feedback-Loop: Jede auto-validierte Buchung in den Vendor-Cache schreiben
    # → bei 10 Bestätigungen wird der Lieferant "Vertrauenslieferant" (kein LLM mehr nötig)
    if beleg.get("lieferant") and beleg.get("soll_konto"):
        try:
            from tools.db import update_vendor_cache as _uvc
            _uvc(
                lieferant        = beleg["lieferant"],
                soll_konto       = beleg["soll_konto"],
                bezeichnung      = beleg.get("buchungstext", ""),
                steuerschluessel = beleg.get("steuerschluessel", ""),
                mandant_id       = mandant_id,
                bestaetigt       = True,
            )
        except Exception as _exc:
            logger.debug("Vendor-Cache-Update fehlgeschlagen (non-critical): %s", _exc)

    return beleg


def run(source: str = "folder", imap: bool = False, mandant_id: str | None = None) -> dict:
    """Hauptlauf: alle neuen Belege verarbeiten.

    mandant_id: Optional — wenn gesetzt, werden mandantenspezifische Pfade und
    DATEV-Nummern verwendet. Ohne mandant_id wird das globale inbox/ genutzt.
    """
    _setup_logging()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Fix 14: Race-Condition-Lock — verhindert gleichzeitige Pipeline-Läufe
    lock_file = ROOT / f".pipeline_running{'_' + mandant_id if mandant_id else ''}"
    if lock_file.exists():
        age_seconds = (datetime.now().timestamp() - lock_file.stat().st_mtime)
        if age_seconds < 3600:  # Lock gilt max. 1 Stunde (Absicherung gegen Crash-Reste)
            logger.warning("Pipeline läuft bereits (Lock-Datei %s, %ds alt) — Abbruch", lock_file.name, int(age_seconds))
            return {"run_id": run_id, "belege": 0, "exportiert": 0, "rueckfragen": 0, "fehler": "Pipeline bereits aktiv"}
        else:
            logger.warning("Veraltete Lock-Datei gefunden (%ds) — wird überschrieben", int(age_seconds))
    lock_file.write_text(run_id)
    try:
        return _run_intern(run_id, source=source, imap=imap, mandant_id=mandant_id)
    finally:
        lock_file.unlink(missing_ok=True)


def _run_intern(run_id: str, source: str = "folder", imap: bool = False, mandant_id: str | None = None) -> dict:
    """Interne Pipeline-Logik (aufgerufen von run() nach Lock-Erwerb)."""

    # Mandant auflösen
    mandant = None
    scan_dir = INBOX_DIR
    export_dir = OUTBOX_DIR
    berater_nr = ""
    mandant_nr = ""

    if mandant_id:
        mandant = get_mandant(mandant_id)
        if not mandant:
            available = [m["id"] for m in load_mandanten()]
            raise ValueError(f"Mandant '{mandant_id}' nicht gefunden. Verfügbar: {available}")
        dirs = mandant_dirs(mandant)
        scan_dir = dirs["inbox"]
        export_dir = dirs["outbox"]
        berater_nr = mandant.get("berater_nr", "")
        mandant_nr = mandant.get("mandant_nr", "")
        logger.info("═══ FiBu-Agent Run %s | Mandant: %s (%s) ═══", run_id, mandant["name"], mandant_id)
    else:
        logger.info("═══ FiBu-Agent Run %s | Kein Mandant (global) ═══", run_id)

    # 1. Belegeingang
    if imap:
        new_files = intake.poll_imap()
        logger.info("IMAP: %d neue Anhänge", len(new_files))
    new_files_folder = intake.scan_folder(scan_dir)
    if imap:
        all_files = list(set(new_files + new_files_folder))
    else:
        all_files = new_files_folder

    if not all_files:
        logger.info("Keine neuen Belege gefunden.")
        return {"run_id": run_id, "belege": 0, "exportiert": 0, "rueckfragen": 0}

    logger.info("%d Belege zur Verarbeitung", len(all_files))
    pipeline_status.start_run(run_id, mandant_id=mandant_id, total_belege=len(all_files))

    # 2. Jeden Beleg durch die Pipeline (mit Budget-Check)
    alle_belege: list[dict] = []
    try:
        for i, path in enumerate(all_files, 1):
            # Budget prüfen bevor API-Calls gemacht werden
            if not cost_tracker.check_budget():
                logger.error("BUDGET ERSCHÖPFT — verbleibende %d Belege übersprungen", len(all_files) - i + 1)
                pipeline_status.finish_run(run_id, error="Budget erschöpft")
                break

            beleg_id = f"BLG-{run_id}-{i:03d}"
            kr = mandant.get("kontenrahmen", "SKR03") if mandant else "SKR03"
            beleg = process_beleg(path, beleg_id, alle_belege, kontenrahmen=kr, mandant_id=mandant_id)
            alle_belege.append(beleg)
            pipeline_status.update_progress(run_id, path.name, beleg.get("status", "fehler"))
    except Exception as exc:
        logger.exception("Pipeline-Fehler: %s", exc)
        pipeline_status.finish_run(run_id, error=str(exc))

    # 3. DATEV-Export — wird manuell per Freigabe in Multi-Entity ausgelöst
    # Belege bleiben auf "validiert" und warten auf manuelle Freigabe (→ "exportiert")
    export_path = None
    export_paths: list[Path] = []

    # 4. Verarbeitete Belege archivieren (GoBD: Original-Beleg unveränderlich aufbewahren)
    archiv_dir = mandant_dirs(mandant)["archiv"] if mandant else None
    fehler_dir = (ROOT / f"fehler/{mandant_id}") if mandant_id else (ROOT / "fehler")
    for b in alle_belege:
        datei_path = Path(b["datei"]) if b.get("datei") else None
        if not datei_path or not datei_path.exists():
            continue
        try:
            if b["status"] in ("exportiert", "validiert", "rueckfrage"):
                archiv_path = intake.move_to_archiv(datei_path, ziel_dir=archiv_dir)
                audit_log.log_event(b["id"], "archivierung", {"archiv_pfad": str(archiv_path)})
            elif b["status"] == "fehler":
                # Fehler-Belege in fehler/-Ordner verschieben damit sie nicht endlos wiederholt werden
                fehler_dir.mkdir(parents=True, exist_ok=True)
                dest = fehler_dir / datei_path.name
                counter = 1
                while dest.exists():
                    dest = fehler_dir / f"{datei_path.stem}_{counter}{datei_path.suffix}"
                    counter += 1
                import shutil
                shutil.move(str(datei_path), str(dest))
                logger.warning("[%s] Fehler-Beleg nach %s verschoben: %s", b["id"], fehler_dir.name, datei_path.name)
                audit_log.log_event(b["id"], "fehler_archivierung", {"pfad": str(dest)})
        except Exception as exc:
            logger.warning("Archivierung fehlgeschlagen für %s: %s", b.get("id"), exc)

    # 5. Report
    summary = report.generate_report(alle_belege)
    print("\n" + summary)
    print("\n" + cost_tracker.get_summary())

    # 5b. Report-E-Mail senden
    try:
        from tools.report_email import send_report
        run_result_for_email = {
            "run_id":     run_id,
            "belege":     len(alle_belege),
            "exportiert": sum(1 for b in alle_belege if b["status"] == "exportiert"),
            "rueckfragen": sum(1 for b in alle_belege if b["status"] == "rueckfrage"),
            "fehler":     sum(1 for b in alle_belege if b["status"] == "fehler"),
        }
        to_email = mandant.get("report_email") if mandant else None
        send_report(
            run_result_for_email,
            export_path=export_path,
            mandant_name=mandant["name"] if mandant else None,
            to_email=to_email,
        )
    except Exception as exc:
        logger.warning("Report-E-Mail konnte nicht gesendet werden: %s", exc)

    # 6. Run-Snapshot (JSON — Rückwärtskompatibilität)
    snapshot = {
        "run_id": run_id,
        "belege": alle_belege,
        "export_datei": str(export_path) if export_path else None,
    }
    snapshot_path = export_dir / f"run_{run_id}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str))

    # 7. SQLite-Persistenz
    try:
        db.create_run(run_id, mandant_id=mandant_id)
        for b in alle_belege:
            db.upsert_beleg({
                "beleg_id": b.get("id"),
                "run_id": run_id,
                "mandant_id": mandant_id,
                "dateiname": Path(b.get("datei", "")).name if b.get("datei") else None,
                "dateipfad": b.get("datei"),
                "lieferant": b.get("lieferant"),
                "rechnungsnummer": b.get("rechnungsnummer"),
                "belegdatum": b.get("belegdatum"),
                "bruttobetrag": b.get("bruttobetrag"),
                "nettobetrag": b.get("nettobetrag"),
                "mwst_betrag": b.get("mwst_betrag"),
                "mwst_satz": b.get("mwst_satz"),
                "waehrung": b.get("waehrung", "EUR"),
                "soll_konto": b.get("soll_konto"),
                "haben_konto": b.get("haben_konto"),
                "steuerschluessel": b.get("steuerschluessel"),
                "buchungstext": b.get("buchungstext"),
                "status": b.get("status"),
                "ocr_konfidenz": b.get("ocr_konfidenz"),
                "kontierung_methode": b.get("kontierung_methode"),
                "rueckfrage_grund": b.get("rueckfrage"),
                "validierung_fehler": b.get("validierung_fehler"),
            })
        db.finish_run(run_id, {
            "total": len(alle_belege),
            "exportiert": sum(1 for b in alle_belege if b["status"] == "exportiert"),
            "fehler": sum(1 for b in alle_belege if b["status"] == "fehler"),
            "rueckfrage": sum(1 for b in alle_belege if b["status"] == "rueckfrage"),
        }, export_datei=str(export_path) if export_path else None)
    except Exception as exc:
        logger.warning("DB-Persistenz fehlgeschlagen (non-critical): %s", exc)

    pipeline_status.finish_run(run_id)

    return {
        "run_id": run_id,
        "belege": len(alle_belege),
        "exportiert": sum(1 for b in alle_belege if b["status"] == "exportiert"),
        "rueckfragen": sum(1 for b in alle_belege if b["status"] == "rueckfrage"),
        "export_datei": str(export_path) if export_path else None,
        "snapshot": str(snapshot_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="FiBu-Agent: KI-gestützte Buchhaltung")
    parser.add_argument("--imap", action="store_true", help="Auch IMAP-Mailbox prüfen")
    parser.add_argument("--mandant", type=str, default=None,
                        help="Mandanten-ID (z.B. M001). Ohne: globales inbox/")
    parser.add_argument("--list-mandanten", action="store_true",
                        help="Zeigt alle konfigurierten Mandanten")
    args = parser.parse_args()

    if args.list_mandanten:
        for m in load_mandanten():
            print(f"  {m['id']:6s}  {m['name']:30s}  {m.get('kontenrahmen', 'SKR03')}")
        return

    result = run(imap=args.imap, mandant_id=args.mandant)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
