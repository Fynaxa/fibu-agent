"""Pilot-Test: Misst OCR-Genauigkeit und Kontierung-Trefferquote.

Lässt alle Testbelege durch die Pipeline und vergleicht die Ergebnisse
mit den erwarteten Werten. Gibt einen detaillierten Report aus.

Usage:
    python tests/pilot_test.py              # Nur OCR + Kontierung
    python tests/pilot_test.py --full       # Voller Pipeline-Run inkl. DATEV-Export
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import ocr_extract, kontierung, validate
from tools.datev_export import export_buchungsstapel
from tools.datev_validate import validate_datev_csv

TESTBELEGE_DIR = Path(__file__).parent / "testbelege"
EXPECTED_FILE = TESTBELEGE_DIR / "expected_results.json"

BETRAG_TOLERANZ = 0.05  # 5 Cent Toleranz bei Beträgen
DATUM_TOLERANZ = 0  # Datum muss exakt stimmen


def _load_expected() -> list[dict]:
    return json.loads(EXPECTED_FILE.read_text(encoding="utf-8"))


def _compare_betrag(actual, expected, toleranz=BETRAG_TOLERANZ) -> bool:
    if actual is None or expected is None:
        return actual == expected
    return abs(float(actual) - float(expected)) <= toleranz


def run_pilot(full_pipeline: bool = False):
    logging.basicConfig(level=logging.WARNING)  # Weniger Noise im Test

    expected_list = _load_expected()
    results = []
    ocr_scores = {"bruttobetrag": 0, "nettobetrag": 0, "belegdatum": 0,
                  "lieferant": 0, "rechnungsnummer": 0, "mwst_satz": 0}
    ocr_total = len(expected_list)
    kontierung_korrekt = 0
    kontierung_total = 0

    print("=" * 70)
    print("PILOT-TEST: FiBu-Agent")
    print(f"{ocr_total} Testbelege")
    print("=" * 70)

    for exp in expected_list:
        pdf_path = TESTBELEGE_DIR / exp["datei"]
        if not pdf_path.exists():
            print(f"\n  SKIP {exp['id']}: Datei nicht gefunden: {exp['datei']}")
            continue

        print(f"\n--- {exp['id']} | {exp['typ']} | {exp['firma'][:30]} ---")

        # 1. OCR
        try:
            ocr = ocr_extract.extract(pdf_path, double_check=False)
        except Exception as exc:
            print(f"  OCR FEHLER: {exc}")
            results.append({"id": exp["id"], "ocr_ok": False, "error": str(exc)})
            continue

        # OCR-Felder vergleichen
        ocr_detail = {}

        # Bruttobetrag
        ok = _compare_betrag(ocr.get("bruttobetrag"), exp["bruttobetrag"])
        ocr_scores["bruttobetrag"] += int(ok)
        ocr_detail["bruttobetrag"] = f"{'OK' if ok else 'FALSCH'}: {ocr.get('bruttobetrag')} (erwartet: {exp['bruttobetrag']})"

        # Nettobetrag
        ok = _compare_betrag(ocr.get("nettobetrag"), exp["nettobetrag"])
        ocr_scores["nettobetrag"] += int(ok)
        ocr_detail["nettobetrag"] = f"{'OK' if ok else 'FALSCH'}: {ocr.get('nettobetrag')} (erwartet: {exp['nettobetrag']})"

        # Belegdatum
        ok = str(ocr.get("belegdatum", "")).strip() == str(exp["belegdatum"]).strip()
        ocr_scores["belegdatum"] += int(ok)
        ocr_detail["belegdatum"] = f"{'OK' if ok else 'FALSCH'}: {ocr.get('belegdatum')} (erwartet: {exp['belegdatum']})"

        # Lieferant (teilweise Match genügt)
        lieferant_ocr = (ocr.get("lieferant") or "").lower()
        lieferant_exp = exp["firma"].lower().split()[0]  # Erstes Wort reicht
        ok = lieferant_exp in lieferant_ocr
        ocr_scores["lieferant"] += int(ok)
        ocr_detail["lieferant"] = f"{'OK' if ok else 'FALSCH'}: '{ocr.get('lieferant')}' (erwartet enthält: '{lieferant_exp}')"

        # Rechnungsnummer
        re_ocr = (ocr.get("rechnungsnummer") or "").strip()
        re_exp = exp["rechnungsnummer"].strip()
        ok = re_exp.lower() in re_ocr.lower() or re_ocr.lower() in re_exp.lower()
        ocr_scores["rechnungsnummer"] += int(ok)
        ocr_detail["rechnungsnummer"] = f"{'OK' if ok else 'FALSCH'}: '{re_ocr}' (erwartet: '{re_exp}')"

        # MwSt-Satz
        ok = _compare_betrag(ocr.get("mwst_satz"), exp["mwst_satz"], toleranz=0.1)
        ocr_scores["mwst_satz"] += int(ok)
        ocr_detail["mwst_satz"] = f"{'OK' if ok else 'FALSCH'}: {ocr.get('mwst_satz')} (erwartet: {exp['mwst_satz']})"

        for k, v in ocr_detail.items():
            marker = "OK" if "OK:" in v else "!!"
            print(f"  [{marker}] {k:20s} {v}")

        # 2. Kontierung
        beleg_for_kont = dict(ocr)
        try:
            kont = kontierung.kontiere(beleg_for_kont)
            kontierung_total += 1
            konto_ok = kont.get("soll_konto") == exp["expected_konto"]
            if konto_ok:
                kontierung_korrekt += 1
            print(f"  [{'OK' if konto_ok else '!!'}] {'kontierung':20s} {kont.get('soll_konto')} ({kont.get('methode', '?')}) (erwartet: {exp['expected_konto']} {exp['expected_bezeichnung']})")
        except Exception as exc:
            print(f"  [!!] kontierung FEHLER: {exc}")

        results.append({"id": exp["id"], "ocr": ocr_detail, "ocr_raw": ocr})

    # ─── Zusammenfassung ───
    print("\n" + "=" * 70)
    print("ERGEBNIS-ZUSAMMENFASSUNG")
    print("=" * 70)

    print(f"\nOCR-Genauigkeit ({ocr_total} Belege):")
    for field, score in ocr_scores.items():
        pct = score / ocr_total * 100 if ocr_total > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"  {field:20s} {bar} {score}/{ocr_total} ({pct:.0f}%)")

    overall_ocr = sum(ocr_scores.values()) / (len(ocr_scores) * ocr_total) * 100 if ocr_total > 0 else 0
    print(f"\n  Gesamt OCR-Score: {overall_ocr:.1f}%")

    if kontierung_total > 0:
        kont_pct = kontierung_korrekt / kontierung_total * 100
        print(f"\nKontierung-Trefferquote:")
        bar = "█" * int(kont_pct / 5) + "░" * (20 - int(kont_pct / 5))
        print(f"  {'Korrekte Konten':20s} {bar} {kontierung_korrekt}/{kontierung_total} ({kont_pct:.0f}%)")

    # 3. DATEV-Export-Test (bei --full)
    if full_pipeline:
        print(f"\nDATEV-Export-Test:")
        exportable = []
        for r in results:
            raw = r.get("ocr_raw", {})
            if raw.get("bruttobetrag") and raw.get("soll_konto"):
                exportable.append(raw)

        if exportable:
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                path = export_buchungsstapel(exportable, output_dir=Path(tmpdir))
                val = validate_datev_csv(path)
                if val["valid"]:
                    print(f"  [OK] DATEV-Export gültig: {val['zeilen']} Buchungszeilen")
                else:
                    print(f"  [!!] DATEV-Export ungültig:")
                    for f in val["fehler"]:
                        print(f"       {f}")
                if val["warnungen"]:
                    for w in val["warnungen"]:
                        print(f"  [??] {w}")
        else:
            print("  Keine exportierbaren Belege (fehlende Kontierung)")

    # Bewertung
    print("\n" + "=" * 70)
    if overall_ocr >= 90 and (kontierung_total == 0 or kont_pct >= 80):
        print("BEWERTUNG: BEREIT FÜR KUNDEN-PILOT")
    elif overall_ocr >= 70:
        print("BEWERTUNG: NACHBESSERUNG NÖTIG — Einzelfehler analysieren")
    else:
        print("BEWERTUNG: NICHT BEREIT — OCR-Genauigkeit zu niedrig")
    print("=" * 70)


if __name__ == "__main__":
    full = "--full" in sys.argv
    run_pilot(full_pipeline=full)
