"""Fundamental analytics: ratio identities and honest handling of gaps."""

from __future__ import annotations

import pytest

from backend.analytics.fundamental import analyse_fundamentals, cagr, percentile_rank


def test_ratios_are_internally_consistent(bundle):
    a = bundle.analysis
    latest = a.latest
    fin = bundle.fundamentals.latest
    assert latest.revenue == fin.revenue
    assert latest.fcf == pytest.approx(fin.cfo - fin.capex)
    if latest.ebitda_margin is not None:
        assert latest.ebitda_margin == pytest.approx(fin.ebitda / fin.revenue, rel=1e-6)
    if latest.debt_to_equity is not None:
        assert latest.debt_to_equity == pytest.approx(fin.total_debt / fin.equity, rel=1e-6)


def test_financial_institutions_have_no_roce(bank_bundle):
    assert bank_bundle.analysis.is_financial
    assert bank_bundle.analysis.latest.roce is None
    assert bank_bundle.analysis.latest.roa is not None


def test_quality_score_bounded(bundle, bank_bundle):
    for b in (bundle, bank_bundle):
        assert 0 <= b.analysis.quality_score <= 100
        assert b.analysis.quality_band in {"STRONG", "GOOD", "AVERAGE", "WEAK"}


def test_score_has_explanations(bundle):
    a = bundle.analysis
    # Every score component must be attributable to a stated reason.
    assert len(a.strengths) + len(a.concerns) > 0 or a.insufficient


def test_cagr_handles_non_positive_inputs():
    assert cagr(100, 200, 3) == pytest.approx((2 ** (1 / 3)) - 1)
    assert cagr(-100, 200, 3) is None
    assert cagr(0, 200, 3) is None
    assert cagr(100, 200, 0) is None


def test_percentile_rank():
    assert percentile_rank([1, 2, 3], 3) == pytest.approx(83.3, abs=0.2)
    assert percentile_rank([], 5) == 50.0


def test_history_covers_every_year(bundle):
    assert len(bundle.analysis.ratios) == len(bundle.fundamentals.annual)
    assert bundle.analysis.ratios[0].fiscal_year == bundle.fundamentals.annual[0].fiscal_year
