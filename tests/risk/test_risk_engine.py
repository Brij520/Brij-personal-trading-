"""Risk engine: sizing arithmetic, vetoes and the non-overridable contract."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.analytics.risk import (
    Holding,
    RiskLimits,
    TradeProposal,
    atr_based_sizing,
    beta_to_benchmark,
    check_exposure,
    concentration,
    daily_loss_check,
    kelly_fraction,
    risk_based_sizing,
    validate_proposal,
    value_at_risk,
)


@pytest.fixture()
def limits():
    return RiskLimits(capital=500_000, max_position_risk_pct=1.0,
                      max_portfolio_heat_pct=6.0, max_single_stock_pct=20.0,
                      min_reward_risk=1.5)


def test_sizing_puts_exactly_the_requested_risk_at_stake(limits):
    qty, detail = risk_based_sizing(500_000, entry=100, stop_loss=95, risk_pct=1.0)
    assert qty == 1000
    assert qty * 5 == pytest.approx(5000)


def test_sizing_respects_position_cap():
    qty, _ = risk_based_sizing(1_000_000, entry=100, stop_loss=99, risk_pct=2.0,
                               max_position_pct=5.0)
    assert qty * 100 <= 50_000


def test_sizing_rounds_to_lot_size():
    qty, _ = risk_based_sizing(500_000, entry=100, stop_loss=90, risk_pct=1.0, lot_size=25)
    assert qty % 25 == 0


def test_atr_sizing_uses_atr_multiple():
    stop, qty = atr_based_sizing(500_000, entry=100, atr=2.0, risk_pct=1.0, atr_multiple=2)
    assert stop == pytest.approx(96.0)
    assert qty == pytest.approx(1250, abs=1)


def test_kelly_is_capped_and_zero_without_edge():
    assert kelly_fraction(0.5, 2, 1) == pytest.approx(0.25)
    assert kelly_fraction(0.3, 1, 1) == 0.0
    assert kelly_fraction(0.5, 0, 1) == 0.0


def test_approved_trade_reports_sizes(limits):
    decision = validate_proposal(
        TradeProposal("TCS", "LONG", entry=100, stop_loss=95, target=115), limits)
    assert decision.approved
    assert decision.reward_risk == pytest.approx(3.0)
    assert decision.quantity > 0
    assert decision.overridable is False


def test_stop_on_wrong_side_rejected(limits):
    decision = validate_proposal(
        TradeProposal("X", "LONG", entry=100, stop_loss=101, target=110), limits)
    assert not decision.approved
    assert any("must be below entry" in r for r in decision.reasons)


def test_target_on_wrong_side_rejected(limits):
    decision = validate_proposal(
        TradeProposal("X", "SHORT", entry=100, stop_loss=105, target=110), limits)
    assert not decision.approved


def test_reward_risk_below_minimum_rejected(limits):
    decision = validate_proposal(
        TradeProposal("X", "LONG", entry=100, stop_loss=95, target=104), limits)
    assert not decision.approved
    assert any("Reward-to-risk" in r for r in decision.reasons)


def test_fno_always_rejected(limits):
    decision = validate_proposal(
        TradeProposal("X", "LONG", entry=100, stop_loss=95, target=120, is_fno=True), limits)
    assert not decision.approved
    assert any("F&O" in r or "FNO" in r for r in decision.reasons)


def test_portfolio_heat_blocks_new_trade(limits):
    decision = validate_proposal(
        TradeProposal("X", "LONG", entry=100, stop_loss=95, target=120), limits,
        open_risk_pct=5.9)
    assert not decision.approved
    assert any("portfolio heat" in r for r in decision.reasons)


def test_tight_stop_warns_about_noise(limits):
    decision = validate_proposal(
        TradeProposal("X", "LONG", entry=100, stop_loss=99.8, target=120, atr=2.0), limits)
    assert any("noise" in w or "ATR" in w for w in decision.warnings)


def test_exposure_detects_single_stock_breach(limits):
    holdings = [
        Holding("A", 100, 100, 100, "IT"),
        Holding("B", 10, 100, 100, "IT"),
    ]
    result = check_exposure(holdings, limits)
    assert result["total_value"] > 0
    assert any("A is" in b for b in result["breaches"])


def test_exposure_detects_sector_breach():
    limits = RiskLimits(capital=1_000_000, max_sector_pct=30, max_single_stock_pct=50)
    holdings = [
        Holding("A", 100, 100, 100, "Financials"),
        Holding("B", 100, 100, 100, "Financials"),
        Holding("C", 100, 100, 100, "IT"),
    ]
    result = check_exposure(holdings, limits)
    assert any("Financials" in b for b in result["breaches"])


def test_concentration_metrics():
    out = concentration([100, 0, 0, 0])
    assert out["hhi"] == pytest.approx(1.0)
    assert out["effective_holdings"] == pytest.approx(1.0)
    flat = concentration([25, 25, 25, 25])
    assert flat["effective_holdings"] == pytest.approx(4.0)


def test_var_requires_enough_history():
    short = pd.Series([0.01, -0.01] * 10)
    assert value_at_risk(short)["var_pct"] == 0.0
    import numpy as np

    rng = np.random.default_rng(11)
    returns = pd.Series(rng.normal(0.0003, 0.02, 500))
    out = value_at_risk(returns, confidence=0.95)
    assert out["var_pct"] > 0
    assert out["cvar_pct"] >= out["var_pct"]
    # 99% must be at least as severe as 95%.
    assert value_at_risk(returns, 0.99)["var_pct"] >= out["var_pct"]


def test_beta_of_series_against_itself_is_one():
    rng = pd.Series([0.001, -0.002, 0.003, -0.001] * 40)
    assert beta_to_benchmark(rng, rng) == pytest.approx(1.0)


def test_daily_loss_limit():
    limits = RiskLimits(capital=100_000, daily_loss_limit_pct=2)
    assert daily_loss_check(-1000, 100_000, limits)["breached"] is False
    assert daily_loss_check(-2500, 100_000, limits)["breached"] is True
