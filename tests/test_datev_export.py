"""Tests für tools/datev_export.py und tools/datev_validate.py."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.datev_export import export_buchungsstapel, _format_datum, _format_betrag
from tools.datev_validate import validate_datev_csv


def test_format_datum():
    assert _format_datum("2026-04-08") == "0804"
    assert _format_datum("2026-12-31") == "3112"
    assert _format_datum(None) == ""
    assert _format_datum("invalid") == ""


def test_format_betrag():
    assert _format_betrag(100.00) == "100,00"
    assert _format_betrag(1234.56) == "1234,56"
    assert _format_betrag(0.99) == "0,99"
    assert _format_betrag(None) == "0,00"


def test_export_and_validate():
    belege = [
        {
            "bruttobetrag": 100.00,
            "waehrung": "EUR",
            "soll_konto": "4920",
            "haben_konto": "1200",
            "steuerschluessel": "9",
            "belegdatum": "2026-04-08",
            "rechnungsnummer": "RE-001",
            "buchungstext": "Vodafone Mobilfunk",
        },
        {
            "bruttobetrag": 47.50,
            "waehrung": "EUR",
            "soll_konto": "4930",
            "haben_konto": "1200",
            "steuerschluessel": "9",
            "belegdatum": "2026-04-10",
            "rechnungsnummer": "RE-002",
            "buchungstext": "Viking Büromaterial",
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_buchungsstapel(belege, output_dir=Path(tmpdir))
        assert path.exists()
        assert path.suffix == ".csv"

        # Validate the exported file
        result = validate_datev_csv(path)
        assert result["valid"] is True, f"Validation errors: {result['fehler']}"
        assert result["zeilen"] == 2


def test_validate_missing_file():
    result = validate_datev_csv(Path("/nonexistent/file.csv"))
    assert result["valid"] is False
    assert "nicht gefunden" in result["fehler"][0]


def test_empty_export():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_buchungsstapel([], output_dir=Path(tmpdir))
        assert path.exists()
        result = validate_datev_csv(path)
        # Valid structure but no data rows
        assert result["zeilen"] == 0
