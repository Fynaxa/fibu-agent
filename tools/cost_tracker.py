"""API-Kosten-Tracking mit Budget-Cap.

Trackt Claude-API-Kosten pro Beleg und Run und stoppt die Verarbeitung,
wenn das konfigurierte Tages- oder Monatsbudget erreicht ist.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from tools.config import ROOT

logger = logging.getLogger(__name__)

COSTS_FILE = ROOT / "outbox" / "api_costs.jsonl"

# Claude Pricing (Stand April 2026, Sonnet 4)
# Input: $3/MTok, Output: $15/MTok
PRICING = {
    "claude-sonnet-4-6": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-sonnet-4-20250514": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-haiku-4-5-20251001": {"input_per_mtok": 0.80, "output_per_mtok": 4.00},
    "default": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
}

# Budget-Limits (konfigurierbar via .env, Defaults hier)
DAILY_BUDGET_EUR = float(_env) if (_env := __import__("os").environ.get("DAILY_BUDGET_EUR")) else 5.00
MONTHLY_BUDGET_EUR = float(_env) if (_env := __import__("os").environ.get("MONTHLY_BUDGET_EUR")) else 50.00
USD_EUR_RATE = 0.92  # Grober Umrechnungskurs


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Berechnet Kosten in EUR für einen API-Call."""
    pricing = PRICING.get(model, PRICING["default"])
    cost_usd = (
        (input_tokens / 1_000_000) * pricing["input_per_mtok"]
        + (output_tokens / 1_000_000) * pricing["output_per_mtok"]
    )
    return round(cost_usd * USD_EUR_RATE, 6)


def log_api_call(
    beleg_id: str | None,
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    mandant_id: str | None = None,
) -> dict:
    """Loggt einen API-Call mit Kosten."""
    cost_eur = _estimate_cost(model, input_tokens, output_tokens)
    entry = {
        "zeitstempel": datetime.now().isoformat(),
        "beleg_id": beleg_id,
        "mandant_id": mandant_id,
        "operation": operation,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_eur": cost_eur,
    }

    COSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COSTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("API-Kosten: %.4f EUR (%s, %s)", cost_eur, operation, model)
    return entry


def get_costs(period: str = "today") -> dict:
    """Aggregiert Kosten für einen Zeitraum.

    Args:
        period: "today", "month", oder "all"

    Returns:
        dict mit total_eur, calls, by_operation, budget_remaining
    """
    if not COSTS_FILE.exists():
        budget = DAILY_BUDGET_EUR if period == "today" else MONTHLY_BUDGET_EUR
        return {"total_eur": 0, "calls": 0, "by_operation": {}, "budget_eur": budget, "budget_remaining_eur": budget, "budget_exceeded": False}

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    total = 0.0
    calls = 0
    by_operation: dict[str, float] = {}

    for line in COSTS_FILE.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = entry.get("zeitstempel", "")

        if period == "today" and not ts.startswith(today_str):
            continue
        if period == "month" and not ts.startswith(month_str):
            continue

        cost = entry.get("cost_eur", 0)
        total += cost
        calls += 1
        op = entry.get("operation", "unknown")
        by_operation[op] = by_operation.get(op, 0) + cost

    budget = DAILY_BUDGET_EUR if period == "today" else MONTHLY_BUDGET_EUR
    return {
        "total_eur": round(total, 4),
        "calls": calls,
        "by_operation": {k: round(v, 4) for k, v in by_operation.items()},
        "budget_eur": budget,
        "budget_remaining_eur": round(budget - total, 4),
        "budget_exceeded": total >= budget,
    }


def check_budget() -> bool:
    """Prüft, ob das Budget noch ausreicht. Returns True wenn OK, False wenn erschöpft."""
    daily = get_costs("today")
    if daily["budget_exceeded"]:
        logger.warning("TAGESBUDGET ERSCHÖPFT: %.2f / %.2f EUR", daily["total_eur"], DAILY_BUDGET_EUR)
        return False

    monthly = get_costs("month")
    if monthly["budget_exceeded"]:
        logger.warning("MONATSBUDGET ERSCHÖPFT: %.2f / %.2f EUR", monthly["total_eur"], MONTHLY_BUDGET_EUR)
        return False

    return True


def get_summary() -> str:
    """Gibt eine lesbare Kostenzusammenfassung zurück."""
    daily = get_costs("today")
    monthly = get_costs("month")
    lines = [
        "═══ API-Kosten ═══",
        f"Heute:  {daily['total_eur']:.2f} / {DAILY_BUDGET_EUR:.2f} EUR ({daily['calls']} Calls)",
        f"Monat:  {monthly['total_eur']:.2f} / {MONTHLY_BUDGET_EUR:.2f} EUR ({monthly['calls']} Calls)",
    ]
    if daily.get("by_operation"):
        lines.append("Aufschlüsselung heute:")
        for op, cost in sorted(daily["by_operation"].items(), key=lambda x: -x[1]):
            lines.append(f"  {op:25s} {cost:.4f} EUR")
    return "\n".join(lines)
