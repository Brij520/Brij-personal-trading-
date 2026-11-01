"""Valuation model behaviour: valid maths, honest failure modes."""

from __future__ import annotations

import pytest

from backend.analytics import valuation as val


def base_assumptions(**overrides):
    params = dict(
        revenue_growth_first_year=0.12, growth_fade_to=0.05, ebit_margin=0.15,
        wacc=0.12, terminal_growth=0.045, net_debt=1000.0, shares_outstanding=100.0,
    )
    params.update(overrides)
    return val.DCFAssumptions(**params)


def test_dcf_value_positive_and_upside_computed():
    result = val.run_dcf(base_assumptions(), start_revenue=10_000, current_price=2000)
    assert result.value_per_share is not None and result.value_per_share > 0
    # upside is computed from the unrounded value, so allow sub-paisa rounding.
    assert result.upside_pct == pytest.approx(
        (result.value_per_share / 2000 - 1) * 100, abs=0.02
    )
    assert not result.warnings


def test_dcf_rejects_wacc_below_terminal_growth():
    result = val.run_dcf(base_assumptions(wacc=0.03, terminal_growth=0.05), 10_000, 1000)
    assert result.value_per_share is None
    assert any("must exceed terminal growth" in w for w in result.warnings)


def test_higher_wacc_lowers_value():
    cheap = val.run_dcf(base_assumptions(wacc=0.10), 10_000, None)
    dear = val.run_dcf(base_assumptions(wacc=0.14), 10_000, None)
    assert cheap.value_per_share > dear.value_per_share


def test_higher_growth_raises_value():
    low = val.run_dcf(base_assumptions(revenue_growth_first_year=0.05), 10_000, None)
    high = val.run_dcf(base_assumptions(revenue_growth_first_year=0.20), 10_000, None)
    assert high.value_per_share > low.value_per_share


def test_terminal_value_share_warning_when_dominant():
    result = val.run_dcf(
        base_assumptions(revenue_growth_first_year=0.01, growth_fade_to=0.01,
                         terminal_growth=0.06, wacc=0.085),
        10_000, None,
    )
    assert result.terminal_share_of_value > 0.75
    assert any("Terminal value" in w for w in result.warnings)


def test_scenarios_ordered_bear_base_bull():
    a = base_assumptions()
    scenarios = {s.name: s for s in val.run_scenarios(a, 10_000, 1000)}
    assert set(scenarios) == {"BEAR", "BASE", "BULL"}
    assert (scenarios["BEAR"].value_per_share
            < scenarios["BASE"].value_per_share
            < scenarios["BULL"].value_per_share)


def test_bank_valuation_growth_cap_behaviour():
    # High retention but ROE above cost of equity should still produce a sane multiple.
    v = val.bank_valuation(price=500, book_value_per_share=250, roe=0.18,
                           cost_of_equity=0.135, dividend_per_share=2.0, payout_ratio=0.1)
    assert 0.2 < v.justified_pb < 8
    assert v.price_to_book == pytest.approx(2.0)
    assert any("sensitive" in n for n in v.notes)


def test_bank_valuation_flags_negative_spread():
    v = val.bank_valuation(price=100, book_value_per_share=100, roe=0.08,
                           cost_of_equity=0.135)
    assert v.justified_pb < 1


def test_ddm_skips_without_dividend():
    out = val.dividend_discount(0.0)
    assert out["value"] == 0.0
    assert "not applicable" in str(out["note"]).lower()


def test_residual_income_requires_book_value():
    assert val.residual_income(0.0, 0.2)["value"] == 0.0


def test_multiple_valuation_insufficient_without_peers():
    rows = val.multiple_valuation(
        price=100, eps=5, book_value_per_share=40, ebitda_per_share=10,
        net_debt_per_share=0, peers=[], history=[])
    assert all(r.verdict == "INSUFFICIENT" for r in rows)
