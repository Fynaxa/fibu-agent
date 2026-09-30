"""Tests für tools/cost_tracker.py — API-Kosten-Tracking."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.cost_tracker import _estimate_cost, log_api_call, get_costs, check_budget


def test_estimate_cost():
    # 1000 input + 500 output tokens with Sonnet pricing
    cost = _estimate_cost("claude-sonnet-4-6", 1000, 500)
    assert cost > 0
    assert cost < 0.01  # Should be very small for few tokens


def test_estimate_cost_scales():
    small = _estimate_cost("claude-sonnet-4-6", 100, 50)
    large = _estimate_cost("claude-sonnet-4-6", 100_000, 50_000)
    assert large > small


def test_log_and_get_costs():
    with tempfile.TemporaryDirectory() as tmpdir:
        costs_file = Path(tmpdir) / "costs.jsonl"
        with patch("tools.cost_tracker.COSTS_FILE", costs_file):
            log_api_call("BLG-001", "ocr_vision", "claude-sonnet-4-6", 5000, 300)
            log_api_call("BLG-002", "ocr_text", "claude-sonnet-4-6", 3000, 200)

            result = get_costs("today")
            assert result["calls"] == 2
            assert result["total_eur"] > 0
            assert "ocr_vision" in result["by_operation"]


def test_budget_check():
    with tempfile.TemporaryDirectory() as tmpdir:
        costs_file = Path(tmpdir) / "costs.jsonl"
        with patch("tools.cost_tracker.COSTS_FILE", costs_file):
            # Fresh start — budget should be OK
            assert check_budget() is True
