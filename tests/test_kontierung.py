"""Tests für tools/kontierung.py — regelbasierte Kontierung."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.kontierung import _regel_match
from tools.config import load_rules


def _beleg(lieferant="", verwendungszweck=""):
    return {"lieferant": lieferant, "verwendungszweck": verwendungszweck}


rules = load_rules("SKR03")


def test_telekom_match():
    result = _regel_match(_beleg(lieferant="Telekom Deutschland"), rules)
    assert result is not None
    assert result["soll_konto"] == "4920"
    assert result["methode"] == "regel"


def test_vodafone_match():
    result = _regel_match(_beleg(lieferant="Vodafone GmbH"), rules)
    assert result is not None
    assert result["soll_konto"] == "4920"


def test_buero_match():
    result = _regel_match(_beleg(lieferant="Viking Bürobedarf"), rules)
    assert result is not None
    assert result["soll_konto"] == "4930"


def test_miete_match():
    result = _regel_match(_beleg(verwendungszweck="Büromiete März 2026"), rules)
    assert result is not None
    assert result["soll_konto"] == "4210"


def test_strom_match():
    result = _regel_match(_beleg(lieferant="Stadtwerke München Strom"), rules)
    assert result is not None
    assert result["soll_konto"] in ("4230", "4240")


def test_tanken_match():
    result = _regel_match(_beleg(lieferant="Shell Tankstelle"), rules)
    assert result is not None
    assert result["soll_konto"] == "4530"


def test_kein_match():
    result = _regel_match(_beleg(lieferant="XYZ Unbekannter Laden 12345"), rules)
    assert result is None


def test_barkauf_haben_konto():
    result = _regel_match(_beleg(lieferant="Viking Bürobedarf", verwendungszweck="Barzahlung Kasse"), rules)
    assert result is not None
    assert result["haben_konto"] == "1000"


def test_konfidenz_hoch():
    result = _regel_match(_beleg(lieferant="Telekom"), rules)
    assert result is not None
    assert result["konfidenz"] == 0.95
