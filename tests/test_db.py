"""Tests für tools/db.py — SQLite-Datenbank."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_upsert_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("tools.db.DB_PATH", Path(tmpdir) / "test.db"):
            from tools import db
            db.init_db()

            db.upsert_beleg({
                "beleg_id": "BLG-TEST-001",
                "run_id": "RUN-001",
                "lieferant": "Test GmbH",
                "bruttobetrag": 119.00,
                "status": "neu",
            })

            beleg = db.get_beleg("BLG-TEST-001")
            assert beleg is not None
            assert beleg["lieferant"] == "Test GmbH"
            assert beleg["bruttobetrag"] == 119.00


def test_duplikat_check():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("tools.db.DB_PATH", Path(tmpdir) / "test.db"):
            from tools import db
            db.init_db()

            db.upsert_beleg({
                "beleg_id": "BLG-DUP-001",
                "rechnungsnummer": "RE-999",
                "lieferant": "Dup GmbH",
                "bruttobetrag": 50.00,
                "status": "exportiert",
            })

            assert db.check_duplikat("RE-999", "Dup GmbH", 50.00) is True
            assert db.check_duplikat("RE-999", "Dup GmbH", 51.00) is False
            assert db.check_duplikat("RE-000", "Dup GmbH", 50.00) is False


def test_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("tools.db.DB_PATH", Path(tmpdir) / "test.db"):
            from tools import db
            db.init_db()

            for i, status in enumerate(["exportiert", "exportiert", "rueckfrage", "fehler"]):
                db.upsert_beleg({
                    "beleg_id": f"BLG-STAT-{i}",
                    "bruttobetrag": 100.00,
                    "status": status,
                })

            stats = db.get_stats()
            assert stats["total"] == 4
            assert stats["exportiert"] == 2
            assert stats["rueckfragen"] == 1
            assert stats["fehler"] == 1


def test_run_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("tools.db.DB_PATH", Path(tmpdir) / "test.db"):
            from tools import db
            db.init_db()

            db.create_run("RUN-LIFE-001", mandant_id="M001")
            runs = db.get_runs()
            assert len(runs) == 1
            assert runs[0]["status"] == "laufend"

            db.finish_run("RUN-LIFE-001", {"total": 5, "exportiert": 3, "fehler": 1, "rueckfrage": 1})
            runs = db.get_runs()
            assert runs[0]["status"] == "abgeschlossen"
            assert runs[0]["belege_total"] == 5
