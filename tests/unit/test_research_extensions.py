from __future__ import annotations

from backend.agents.options_intelligence import Leg, research_margin_estimate, structure_summary
from backend.services.market import run_screener


def test_option_payoff_includes_transparent_margin_estimate():
    summary = structure_summary(
        [
            Leg("SELL", "CE", 100.0, 5.0),
            Leg("BUY", "CE", 110.0, 1.5),
        ],
        spot=100.0,
        lot_size=50,
    )

    estimate = summary["margin_estimate"]
    assert estimate["estimated_margin"] > 0
    assert estimate["method"]
    assert estimate["warning"].startswith("Research estimate only")
    assert estimate["unbounded_risk"] is False


def test_naked_short_call_is_flagged_as_unbounded_research_risk():
    estimate = research_margin_estimate([Leg("SELL", "CE", 100.0, 5.0)], 100.0, 50)
    assert estimate["unbounded_risk"] is True
    assert estimate["estimated_margin"] > 0


def test_sector_leader_scan_returns_named_top_one_month_performers(registry):
    result = run_screener(registry, scans=["sector_leaders"], limit=200)

    assert result["result_count"] > 0
    assert all(row["is_sector_leader"] for row in result["results"])
    assert all(row["sector_leader_rank"] == 1 for row in result["results"])
    assert all("sector_leader_rationale" in row for row in result["results"])
    assert len({row["sector"] for row in result["results"]}) == result["result_count"]
