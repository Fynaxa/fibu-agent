"""Generiert realistische deutsche Rechnungen als PDF für Pilot-Tests.

Erzeugt 15 verschiedene Belegtypen, die typisch für eine kleine
Steuerkanzlei / KMU sind. Jeder Beleg hat bekannte Soll-Werte,
damit OCR-Genauigkeit und Kontierung gemessen werden können.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "testbelege"
EXPECTED_FILE = OUTPUT_DIR / "expected_results.json"

# ─── Testdaten: 15 realistische Rechnungen ────────────────

BELEGE = [
    {
        "id": "TB-001",
        "typ": "Telekommunikation",
        "firma": "Vodafone GmbH",
        "adresse": "Ferdinand-Braun-Platz 1\n40549 Düsseldorf",
        "rechnungsnr": "VF-2026-8834721",
        "datum": "2026-03-15",
        "positionen": [("Mobilfunk Red Business M 03/2026", 1, 39.99)],
        "mwst_satz": 19.0,
        "iban": "DE89370400440532013000",
        "expected_konto": "4920",
        "expected_bezeichnung": "Telefon",
    },
    {
        "id": "TB-002",
        "typ": "Büromaterial",
        "firma": "Viking Direkt GmbH",
        "adresse": "Limbecker Platz 1\n45127 Essen",
        "rechnungsnr": "VK-9912445",
        "datum": "2026-03-18",
        "positionen": [
            ("Kopierpapier A4, 5x500 Blatt", 2, 24.99),
            ("Ordner Leitz 1080, 10er Pack", 1, 18.50),
            ("Kugelschreiber Schneider K15, 50 Stk", 1, 12.90),
        ],
        "mwst_satz": 19.0,
        "iban": "DE44500105175426945826",
        "expected_konto": "4930",
        "expected_bezeichnung": "Bürobedarf",
    },
    {
        "id": "TB-003",
        "typ": "Miete",
        "firma": "Hausverwaltung Schneider GmbH",
        "adresse": "Kaiserstr. 45\n60329 Frankfurt am Main",
        "rechnungsnr": "MR-2026-03",
        "datum": "2026-03-01",
        "positionen": [("Gewerbemiete Büro EG links, März 2026", 1, 1250.00)],
        "mwst_satz": 0.0,
        "iban": "DE27100777770209299700",
        "expected_konto": "4210",
        "expected_bezeichnung": "Miete",
    },
    {
        "id": "TB-004",
        "typ": "Software",
        "firma": "Microsoft Ireland Operations Ltd.",
        "adresse": "One Microsoft Place\nDublin 18, Ireland",
        "rechnungsnr": "MS-INV-2026-E887231",
        "datum": "2026-03-20",
        "positionen": [("Microsoft 365 Business Basic, 5 User × 03/2026", 1, 54.50)],
        "mwst_satz": 19.0,
        "iban": "-",
        "expected_konto": "4964",
        "expected_bezeichnung": "EDV-Kosten / Software",
    },
    {
        "id": "TB-005",
        "typ": "Tankstelle",
        "firma": "Shell Deutschland GmbH",
        "adresse": "Shell Station Nr. 4412\nHauptstr. 88, 80331 München",
        "rechnungsnr": "4412-20260322-0847",
        "datum": "2026-03-22",
        "positionen": [("Super E10, 42.5 Liter", 1, 74.38)],
        "mwst_satz": 19.0,
        "iban": "-",
        "expected_konto": "4530",
        "expected_bezeichnung": "Kfz-Betriebskosten",
    },
    {
        "id": "TB-006",
        "typ": "Versicherung",
        "firma": "Allianz Versicherungs-AG",
        "adresse": "Königinstr. 28\n80802 München",
        "rechnungsnr": "AV-BH-2026-334509",
        "datum": "2026-03-25",
        "positionen": [("Betriebshaftpflichtversicherung Q2/2026", 1, 387.50)],
        "mwst_satz": 0.0,
        "iban": "DE13720400460577605505",
        "expected_konto": "4360",
        "expected_bezeichnung": "Versicherungen",
    },
    {
        "id": "TB-007",
        "typ": "Porto",
        "firma": "Deutsche Post AG",
        "adresse": "Charles-de-Gaulle-Str. 20\n53113 Bonn",
        "rechnungsnr": "DP-2026-FRA-88213",
        "datum": "2026-03-10",
        "positionen": [
            ("Briefmarken 0,85 EUR × 100", 1, 85.00),
            ("Einschreiben × 5", 1, 17.50),
        ],
        "mwst_satz": 19.0,
        "iban": "DE28370501980000077228",
        "expected_konto": "4910",
        "expected_bezeichnung": "Porto",
    },
    {
        "id": "TB-008",
        "typ": "Hosting",
        "firma": "Hetzner Online GmbH",
        "adresse": "Industriestr. 25\n91710 Gunzenhausen",
        "rechnungsnr": "HZ-R-2026-1934822",
        "datum": "2026-03-28",
        "positionen": [
            ("Cloud Server CX21, 03/2026", 1, 5.83),
            ("Domain example.de, 03/2026", 1, 0.83),
        ],
        "mwst_satz": 19.0,
        "iban": "DE33760700120750029500",
        "expected_konto": "4963",
        "expected_bezeichnung": "EDV-Kosten / Hosting",
    },
    {
        "id": "TB-009",
        "typ": "Strom",
        "firma": "Stadtwerke München GmbH",
        "adresse": "Emmy-Noether-Str. 2\n80992 München",
        "rechnungsnr": "SWM-S-2026-334122",
        "datum": "2026-03-05",
        "positionen": [("Stromabschlag März 2026, Gewerbe", 1, 189.00)],
        "mwst_satz": 19.0,
        "iban": "DE86701500000000123456",
        "expected_konto": "4240",
        "expected_bezeichnung": "Strom",
    },
    {
        "id": "TB-010",
        "typ": "Steuerberater",
        "firma": "Steuerkanzlei Dr. Weber & Partner",
        "adresse": "Leopoldstr. 12\n80802 München",
        "rechnungsnr": "WP-2026-0088",
        "datum": "2026-03-30",
        "positionen": [
            ("Finanzbuchhaltung Feb 2026", 1, 450.00),
            ("USt-Voranmeldung Feb 2026", 1, 85.00),
        ],
        "mwst_satz": 19.0,
        "iban": "DE54701500000003445566",
        "expected_konto": "4955",
        "expected_bezeichnung": "Steuerberatungskosten",
    },
    {
        "id": "TB-011",
        "typ": "Bewirtung",
        "firma": "Restaurant zum Goldenen Hirschen",
        "adresse": "Sendlinger Str. 34\n80331 München",
        "rechnungsnr": "KA-20260326-1923",
        "datum": "2026-03-26",
        "positionen": [
            ("3× Hauptgericht", 1, 58.50),
            ("3× Getränke", 1, 16.50),
            ("1× Dessert", 1, 8.90),
        ],
        "mwst_satz": 19.0,
        "iban": "-",
        "expected_konto": "4650",
        "expected_bezeichnung": "Bewirtungskosten",
    },
    {
        "id": "TB-012",
        "typ": "Reise",
        "firma": "Deutsche Bahn AG",
        "adresse": "Potsdamer Platz 2\n10785 Berlin",
        "rechnungsnr": "DB-E-2026-992134",
        "datum": "2026-03-12",
        "positionen": [("Fahrkarte München–Berlin, 1. Kl., Hin+Rück", 1, 241.80)],
        "mwst_satz": 19.0,
        "iban": "-",
        "expected_konto": "4660",
        "expected_bezeichnung": "Reisekosten",
    },
    {
        "id": "TB-013",
        "typ": "Bankgebühren",
        "firma": "Sparkasse München",
        "adresse": "Sparkassenstr. 2\n80331 München",
        "rechnungsnr": "SPK-K-2026-03",
        "datum": "2026-03-31",
        "positionen": [
            ("Kontoführung Geschäftskonto 03/2026", 1, 9.90),
            ("Buchungsposten (47 × 0,15 EUR)", 1, 7.05),
        ],
        "mwst_satz": 0.0,
        "iban": "-",
        "expected_konto": "4970",
        "expected_bezeichnung": "Nebenkosten des Geldverkehrs",
    },
    {
        "id": "TB-014",
        "typ": "Werbung",
        "firma": "Google Ireland Ltd.",
        "adresse": "Gordon House, Barrow Street\nDublin 4, Ireland",
        "rechnungsnr": "GGL-ADS-2026-DE-445891",
        "datum": "2026-03-31",
        "positionen": [("Google Ads Kampagne 'Kanzlei München', 03/2026", 1, 312.44)],
        "mwst_satz": 19.0,
        "iban": "-",
        "expected_konto": "4600",
        "expected_bezeichnung": "Werbekosten",
    },
    {
        "id": "TB-015",
        "typ": "Fremdleistung",
        "firma": "IT-Solutions Meier e.K.",
        "adresse": "Industriepark 7\n85748 Garching",
        "rechnungsnr": "ITM-2026-0134",
        "datum": "2026-03-29",
        "positionen": [
            ("Website-Wartung März 2026, 4h × 95 EUR", 1, 380.00),
            ("SSL-Zertifikat Erneuerung", 1, 29.00),
        ],
        "mwst_satz": 19.0,
        "iban": "DE77701204008374912001",
        "expected_konto": "4960",
        "expected_bezeichnung": "EDV-Kosten",
    },
]


def _netto_from_positionen(positionen: list[tuple]) -> float:
    return sum(preis * menge for _, menge, preis in positionen)


def _generate_pdf(beleg: dict, output_dir: Path) -> Path:
    """Generiert eine realistische deutsche Rechnung als PDF."""
    netto = _netto_from_positionen(beleg["positionen"])
    mwst_betrag = round(netto * beleg["mwst_satz"] / 100, 2)
    brutto = round(netto + mwst_betrag, 2)

    filename = f"{beleg['id']}_{beleg['typ'].replace(' ', '_').replace('/', '_')}.pdf"
    path = output_dir / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4

    # Header: Firmenname
    c.setFont("Helvetica-Bold", 16)
    c.drawString(25 * mm, h - 25 * mm, beleg["firma"])

    # Adresse
    c.setFont("Helvetica", 9)
    y = h - 33 * mm
    for line in beleg["adresse"].split("\n"):
        c.drawString(25 * mm, y, line)
        y -= 4 * mm

    # Empfänger
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, h - 52 * mm, "An:")
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, h - 57 * mm, "Demo GmbH")
    c.drawString(25 * mm, h - 62 * mm, "Musterstraße 1")
    c.drawString(25 * mm, h - 67 * mm, "80331 München")

    # Rechnungsnummer + Datum (rechts)
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 25 * mm, h - 52 * mm, f"Rechnungsnummer: {beleg['rechnungsnr']}")
    c.drawRightString(w - 25 * mm, h - 57 * mm, f"Rechnungsdatum: {beleg['datum']}")
    c.drawRightString(w - 25 * mm, h - 62 * mm, f"Fällig: {beleg['datum']}")

    # Titel
    c.setFont("Helvetica-Bold", 13)
    c.drawString(25 * mm, h - 82 * mm, "RECHNUNG")

    # Positionstabelle — Header
    y = h - 95 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(25 * mm, y, "Pos.")
    c.drawString(35 * mm, y, "Beschreibung")
    c.drawRightString(145 * mm, y, "Menge")
    c.drawRightString(170 * mm, y, "Einzelpreis")
    c.drawRightString(190 * mm, y, "Gesamt")
    y -= 2 * mm
    c.line(25 * mm, y, 190 * mm, y)
    y -= 5 * mm

    # Positionen
    c.setFont("Helvetica", 9)
    for i, (beschreibung, menge, preis) in enumerate(beleg["positionen"], 1):
        gesamt = round(menge * preis, 2)
        c.drawString(25 * mm, y, str(i))
        c.drawString(35 * mm, y, beschreibung[:55])
        c.drawRightString(145 * mm, y, str(menge))
        c.drawRightString(170 * mm, y, f"{preis:.2f} EUR")
        c.drawRightString(190 * mm, y, f"{gesamt:.2f} EUR")
        y -= 6 * mm

    # Summen
    y -= 5 * mm
    c.line(130 * mm, y + 3 * mm, 190 * mm, y + 3 * mm)
    c.setFont("Helvetica", 9)
    c.drawString(130 * mm, y, "Nettobetrag:")
    c.drawRightString(190 * mm, y, f"{netto:.2f} EUR")
    y -= 5 * mm

    if beleg["mwst_satz"] > 0:
        c.drawString(130 * mm, y, f"USt. {beleg['mwst_satz']:.0f}%:")
        c.drawRightString(190 * mm, y, f"{mwst_betrag:.2f} EUR")
        y -= 5 * mm
    else:
        c.drawString(130 * mm, y, "Umsatzsteuer: steuerfrei")
        y -= 5 * mm

    c.line(130 * mm, y + 3 * mm, 190 * mm, y + 3 * mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(130 * mm, y, "Bruttobetrag:")
    c.drawRightString(190 * mm, y, f"{brutto:.2f} EUR")

    # Zahlungshinweis
    y -= 20 * mm
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, y, "Bitte überweisen Sie den Betrag innerhalb von 14 Tagen auf folgendes Konto:")
    y -= 5 * mm
    if beleg["iban"] != "-":
        c.drawString(25 * mm, y, f"IBAN: {beleg['iban']}")
        y -= 4 * mm
    c.drawString(25 * mm, y, f"Verwendungszweck: {beleg['rechnungsnr']}")

    # Footer
    c.setFont("Helvetica", 7)
    c.drawString(25 * mm, 15 * mm, f"{beleg['firma']} · Steuernummer: 123/456/78901 · USt-IdNr.: DE123456789")

    c.save()
    return path


def generate_all() -> tuple[list[Path], list[dict]]:
    """Generiert alle Testbelege und die erwarteten Ergebnisse."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    expected = []

    for beleg in BELEGE:
        path = _generate_pdf(beleg, OUTPUT_DIR)
        paths.append(path)

        netto = _netto_from_positionen(beleg["positionen"])
        mwst_betrag = round(netto * beleg["mwst_satz"] / 100, 2)
        brutto = round(netto + mwst_betrag, 2)

        expected.append({
            "id": beleg["id"],
            "datei": path.name,
            "typ": beleg["typ"],
            "firma": beleg["firma"],
            "rechnungsnummer": beleg["rechnungsnr"],
            "belegdatum": beleg["datum"],
            "nettobetrag": netto,
            "mwst_satz": beleg["mwst_satz"],
            "mwst_betrag": mwst_betrag,
            "bruttobetrag": brutto,
            "expected_konto": beleg["expected_konto"],
            "expected_bezeichnung": beleg["expected_bezeichnung"],
        })

        print(f"  {beleg['id']} {beleg['typ']:25s} {brutto:>10.2f} EUR → {path.name}")

    # Erwartete Ergebnisse speichern
    EXPECTED_FILE.write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(paths)} Testbelege generiert in {OUTPUT_DIR}")
    print(f"Erwartete Ergebnisse: {EXPECTED_FILE}")
    return paths, expected


if __name__ == "__main__":
    generate_all()
