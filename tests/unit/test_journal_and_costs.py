"""Journal lifecycle, review guardrails and the Indian cost model."""

from __future__ import annotations

from datetime import date

import pytest

from backend.backtesting.costs import CostConfig
from backend.core.errors import NotFoundError, ValidationError
from backend.journal.analytics import (
    MIN_SAMPLE,
    build_review,
    discipline_checks,
    mistake_analysis,
    performance_summary,
    strategy_breakdown,
)


def test_trade_lifecycle(journal):
    trade = journal.add_trade({
        "symbol": "tcs", "entry_price": 760, "quantity": 50,
        "entry_date": "2026-10-01", "stop_loss": 720, "target": 860,
        "strategy": "trend_following", "thesis": "above 200dma",
    })
    assert trade.symbol == "TCS" and trade.mode == "PAPER" and trade.status == "OPEN"
    closed = journal.close_trade(trade.id, {"exit_price": 840, "exit_date": "2026-10-20"})
    assert closed.status == "CLOSED"
    assert closed.pnl == pytest.approx((840 - 760) * 50)
    assert closed.pnl_pct == pytest.approx((840 / 760 - 1) * 100, abs=0.01)
    assert closed.r_multiple == pytest.approx(((840 - 760) * 50) / ((760 - 720) * 50), rel=1e-6)


def test_cannot_close_twice(journal):
    trade = journal.add_trade({"symbol": "INFY", "entry_price": 1500,
                               "quantity": 10, "entry_date": "2026-10-01"})
    journal.close_trade(trade.id, {"exit_price": 1550})
    with pytest.raises(ValidationError):
        journal.close_trade(trade.id, {"exit_price": 1600})


def test_invalid_trade_rejected(journal):
    with pytest.raises(ValidationError):
        journal.add_trade({"symbol": "X", "entry_price": -5, "quantity": 1,
                           "entry_date": "2026-01-01"})
    with pytest.raises(ValidationError):
        journal.add_trade({"symbol": "X", "entry_price": 5, "quantity": 1,
                           "entry_date": "2026-01-01", "side": "SIDEWAYS"})


def test_missing_trade_raises(journal):
    with pytest.raises(NotFoundError):
        journal.close_trade(999, {"exit_price": 100})


def test_short_trade_pnl_direction(journal):
    trade = journal.add_trade({"symbol": "X", "entry_price": 100, "quantity": 10,
                               "entry_date": "2026-01-01", "side": "SHORT"})
    closed = journal.close_trade(trade.id, {"exit_price": 90})
    assert closed.pnl == pytest.approx(100)


def test_holdings_upsert_is_idempotent(journal):
    journal.upsert_holdings([{"symbol": "tcs", "quantity": 10, "avg_price": 700}])
    journal.upsert_holdings([{"symbol": "TCS", "quantity": 20, "avg_price": 750}])
    rows = journal.list_holdings()
    assert len(rows) == 1 and rows[0]["quantity"] == 20


def test_performance_summary_needs_closed_trades(journal):
    summary = performance_summary([])
    assert summary["closed_trades"] == 0
    assert "note" in summary


def test_performance_statistics(journal):
    for symbol, entry, exit_price in [("A", 100, 110), ("B", 100, 90), ("C", 100, 120)]:
        t = journal.add_trade({"symbol": symbol, "entry_price": entry, "quantity": 10,
                               "entry_date": "2026-01-01", "stop_loss": 95})
        journal.close_trade(t.id, {"exit_price": exit_price})
    summary = performance_summary(journal.list_trades())
    assert summary["closed_trades"] == 3
    assert summary["win_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert summary["total_pnl"] == pytest.approx(200.0)
    assert summary["sample_warning"]


def test_discipline_flags_missing_stop(journal):
    journal.add_trade({"symbol": "A", "entry_price": 100, "quantity": 1,
                       "entry_date": "2026-01-01"})
    findings = discipline_checks(journal.list_trades())
    assert any("stop-loss" in f["check"] for f in findings)


def test_mistake_tagging(journal):
    t = journal.add_trade({"symbol": "A", "entry_price": 100, "quantity": 1,
                           "entry_date": "2026-01-01", "stop_loss": 95})
    journal.close_trade(t.id, {"exit_price": 90, "mistakes": "moved stop, oversize"})
    out = mistake_analysis(journal.list_trades())
    tags = {m["mistake"] for m in out["tagged_mistakes"]}
    assert tags == {"moved stop", "oversize"}


def test_review_guardrail_blocks_auto_strategy_change(journal):
    review = build_review(journal.list_trades(), "monthly", today=date(2026, 11, 1))
    assert all(p["approved_automatically"] is False for p in review["proposals"])
    assert any("guardrail" in g.lower() or "never" in g.lower() for g in review["guardrails"])
    assert MIN_SAMPLE == 20


def test_review_rejects_unknown_period(journal):
    with pytest.raises(ValueError):
        build_review([], "yearly")


def test_cost_model_delivery_round_trip():
    cfg = CostConfig(segment="delivery", slippage_bps=0)
    charges = cfg.charges(100_000, "BUY")
    # STT 0.10% = 100, brokerage 0.03% = 30, exchange 0.00297% = 2.97
    assert charges["stt"] == pytest.approx(100.0)
    assert charges["brokerage"] == pytest.approx(30.0)
    assert charges["exchange"] == pytest.approx(2.97, abs=0.01)
    assert charges["gst"] > 0
    assert charges["stamp_duty"] == pytest.approx(15.0)


def test_intraday_stt_only_on_sell():
    cfg = CostConfig(segment="intraday", slippage_bps=0)
    assert cfg.charges(100_000, "BUY")["stt"] == 0.0
    assert cfg.charges(100_000, "SELL")["stt"] == pytest.approx(25.0)


def test_intraday_brokerage_flat_cap():
    cfg = CostConfig(segment="intraday", brokerage_flat=20.0, brokerage_pct=0.03)
    assert cfg.charges(1_000_000, "SELL")["brokerage"] == pytest.approx(20.0)


def test_slippage_direction():
    cfg = CostConfig(slippage_bps=10)
    assert cfg.slippage(100, "BUY") == pytest.approx(100.1)
    assert cfg.slippage(100, "SELL") == pytest.approx(99.9)


def test_round_trip_total_is_positive():
    total = CostConfig().round_trip_total(100_000, 110_000)
    assert total["total"] > 0
    assert 0.15 < total["pct_of_buy_value"] < 0.6


def test_liquidity_capacity():
    from backend.backtesting.costs import LiquidityConfig

    liq = LiquidityConfig(max_pct_of_bar_volume=2.0)
    check = liq.check(quantity=1_000, price=100, bar_volume=100_000)
    assert check["within_liquidity"] is True
    heavy = liq.check(quantity=10_000, price=1000, bar_volume=100_000)
    assert heavy["within_liquidity"] is False
