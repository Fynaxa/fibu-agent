"""Tests für tools/validate.py — Belegvalidierung."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate import validate


def _beleg(**overrides):
    base = {
        "belegdatum": "2026-04-08",
        "bruttobetrag": 100.00,
        "lieferant": "Test GmbH",
        "soll_konto": "4920",
        "rechnungsnummer": "RE-001",
    }
    base.update(overrides)
    return base


def test_valid_beleg():
    result = validate(_beleg())
    assert result["valid"] is True
    assert result["fehler"] == []


def test_missing_pflichtfeld():
    result = validate(_beleg(lieferant=None))
    assert result["valid"] is False
    assert any("lieferant" in f for f in result["fehler"])


def test_missing_belegdatum():
    result = validate(_beleg(belegdatum=""))
    assert result["valid"] is False
    assert any("belegdatum" in f for f in result["fehler"])


def test_betrag_negativ():
    result = validate(_beleg(bruttobetrag=-50.0))
    assert result["valid"] is False
    assert any("negativ" in f or "<= 0" in f for f in result["fehler"])


def test_betrag_zu_hoch():
    result = validate(_beleg(bruttobetrag=200_000.0))
    assert result["valid"] is False
    assert any("verdächtig hoch" in f for f in result["fehler"])


def test_mwst_plausibel():
    result = validate(_beleg(nettobetrag=84.03, mwst_satz=19.0, mwst_betrag=15.97))
    assert result["valid"] is True


def test_mwst_abweichung():
    result = validate(_beleg(nettobetrag=100.0, mwst_satz=19.0, mwst_betrag=25.0))
    assert result["valid"] is False
    assert any("MwSt-Abweichung" in f for f in result["fehler"])


def test_duplikat_in_run():
    bisherige = [_beleg()]
    result = validate(_beleg(), bisherige)
    assert result["valid"] is False
    assert any("Duplikat" in f for f in result["fehler"])


def test_kein_soll_konto():
    result = validate(_beleg(soll_konto=""))
    assert result["valid"] is False
    assert any("Soll-Konto" in f for f in result["fehler"])
