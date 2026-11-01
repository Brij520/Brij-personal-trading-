"""Backtest engine: execution assumptions, bias guards and cost accounting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.backtesting.costs import CostConfig, LiquidityConfig
from backend.backtesting.engine import (
    BacktestConfig,
    compare,
    run_backtest,
    train_test_split_backtest,
    walk_forward,
)
from backend.data.providers.base import Series
from backend.core.provenance import DatasetMeta, Freshness, Verification
from backend.strategies.library import STRATEGIES, get_strategy


def make_series(n=800, trend=0.0006, seed=3, amplitude=0.01):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(trend, amplitude, n)))
    idx = pd.bdate_range("2021-01-04", periods=n)
    frame = pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.001, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.005, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.005, n))),
            "close": close,
            "volume": rng.integers(200_000, 2_000_000, n),
        },
        index=idx,
    )
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    meta = DatasetMeta(
        source="test-fixture", exchange="NSE", freshness=Freshness.HISTORICAL,
        verification=Verification.UNVERIFIED, rows=n,
        period_start=idx[0].date(), period_end=idx[-1].date(),
    )
    return Series(symbol="TEST", frame=frame, meta=meta)


def always_enter(frame):
    """Deterministic signal on every 50th bar, for execution-path testing."""
    signal = pd.Series(False, index=frame.index)
    signal.iloc[250::50] = True
    return pd.DataFrame(
        {
            "entry_signal": signal,
            "stop": frame["close"] * 0.97,
            "target": frame["close"] * 1.06,
        },
        index=frame.index,
    )


def test_backtest_returns_metrics_and_trades():
    result = run_backtest(make_series(), always_enter, BacktestConfig(warmup_bars=200), "test")
    assert result.metrics["trades"] > 0
    for key in ("cagr_pct", "max_drawdown_pct", "sharpe", "profit_factor", "exposure_pct"):
        assert key in result.metrics
    assert result.metrics["max_drawdown_pct"] <= 0


def test_no_lookahead_future_bars_do_not_change_earlier_signals():
    """Signals computed on bar t must not depend on bars after t."""
    spec = get_strategy("trend_following")
    series = make_series(900)
    full = spec.signal_fn(series.frame)
    truncated_frame = series.frame.iloc[:600]
    truncated = spec.signal_fn(truncated_frame)
    pd.testing.assert_series_equal(
        full["entry_signal"].iloc[:600], truncated["entry_signal"], check_names=False
    )


def test_execution_happens_at_next_open():
    series = make_series(400)
    signal = pd.Series(False, index=series.frame.index)
    signal.iloc[260] = True
    fn = lambda frame: pd.DataFrame(  # noqa: E731
        {"entry_signal": signal.reindex(frame.index).fillna(False),
         "stop": frame["close"] * 0.9, "target": frame["close"] * 1.2}, index=frame.index)
    result = run_backtest(series, fn, BacktestConfig(warmup_bars=200,
                                                     costs=CostConfig(slippage_bps=0)), "t")
    trade = result.trades[0]
    signal_date = series.frame.index[260]
    assert trade.entry_date > signal_date
    assert trade.entry_price == pytest.approx(float(series.frame["open"].iloc[261]), rel=1e-6)


def test_costs_reduce_pnl_versus_zero_cost():
    series = make_series()
    free = run_backtest(series, always_enter, BacktestConfig(
        costs=CostConfig(slippage_bps=0, brokerage_pct=0, gst_pct=0)), "t")
    costly = run_backtest(series, always_enter, BacktestConfig(
        costs=CostConfig(slippage_bps=20)), "t")
    assert costly.metrics["total_costs"] >= free.metrics["total_costs"]
    assert costly.metrics["final_equity"] <= free.metrics["final_equity"] + 1e-6


def test_stop_takes_priority_when_bar_spans_both_levels():
    # Build a bar that hits stop and target on the same day.
    series = make_series(320)
    idx = series.frame.index[260]
    frame = series.frame.copy()
    entry_ref = frame.loc[idx, "close"]
    frame.loc[idx, "high"] = entry_ref * 1.30
    frame.loc[idx, "low"] = entry_ref * 0.80
    meta = series.meta
    series2 = Series("TEST2", frame, meta)
    signal = pd.Series(False, index=frame.index)
    signal.iloc[259] = True
    fn = lambda f: pd.DataFrame(  # noqa: E731
        {"entry_signal": signal.reindex(f.index).fillna(False),
         "stop": f["close"] * 0.95, "target": f["close"] * 1.05}, index=f.index)
    result = run_backtest(series2, fn, BacktestConfig(warmup_bars=200,
                                                      costs=CostConfig(slippage_bps=0)), "t")
    assert result.trades
    assert result.trades[0].exit_reason == "stop"


def test_liquidity_filter_skips_oversized_orders():
    series = make_series(400)
    frame = series.frame.copy()
    frame["volume"] = 10  # absurdly thin market
    thin = Series("THIN", frame, series.meta)
    result = run_backtest(thin, always_enter,
                          BacktestConfig(liquidity=LiquidityConfig(max_pct_of_bar_volume=1.0),
                                         warmup_bars=200), "t")
    assert result.metrics["trades"] == 0 or result.warnings


def test_walk_forward_reports_stability():
    series = make_series(1500)
    out = walk_forward(series, STRATEGIES["breakout"].signal_fn,
                       BacktestConfig(warmup_bars=220), folds=3)
    assert out["available"]
    assert len(out["folds"]) == 3
    assert out["stability"]["verdict"] in {"consistent", "mixed", "fragile"}


def test_walk_forward_refuses_short_samples():
    out = walk_forward(make_series(400), STRATEGIES["breakout"].signal_fn,
                       BacktestConfig(warmup_bars=220), folds=4)
    assert out["available"] is False and out["reason"]


def test_train_test_split_returns_both_windows():
    series = make_series(1200)
    out = train_test_split_backtest(series, STRATEGIES["trend_following"].signal_fn,
                                    BacktestConfig(warmup_bars=220))
    assert "train" in out and "test" in out
    assert out["train"]["period"][1] <= out["test"]["period"][0]


def test_compare_sorts_by_sharpe():
    series = make_series(1200)
    config = BacktestConfig(warmup_bars=220)
    results = [run_backtest(series, s.signal_fn, config, s.name)
               for s in STRATEGIES.values() if s.family == "swing"]
    rows = compare(results)
    sharpes = [r["sharpe"] for r in rows]
    assert sharpes == sorted(sharpes, reverse=True)


def test_all_strategies_produce_valid_signals():
    frame = make_series(600).frame
    for key, spec in STRATEGIES.items():
        if spec.family == "intraday":
            continue
        signals = spec.signal_fn(frame)
        assert set(signals.columns) == {"entry_signal", "stop", "target"}
        assert signals.index.equals(frame.index)


def test_signal_requires_columns():
    series = make_series(300)
    with pytest.raises(ValueError):
        run_backtest(series, lambda f: pd.DataFrame(index=f.index), BacktestConfig(warmup_bars=100))


def test_equity_curve_reconciles_with_trade_pnl():
    """Final equity must equal capital + realised P&L, with no open position.

    A backtester that lets an open position appreciate while *also* leaving the
    purchase price in cash will show a rising equity curve and losing trades at
    the same time. That is precisely the bug this test exists to catch.
    """
    series = make_series(n=900, trend=0.0004, seed=17)
    config = BacktestConfig(initial_capital=1_000_000)
    result = run_backtest(series, get_strategy("ma_crossover").signal_fn, config, "ma")
    realised = sum(t.pnl for t in result.trades)
    assert result.metrics["final_equity"] == pytest.approx(
        1_000_000 + realised, rel=1e-9, abs=0.01
    )

    # An equity of exactly the initial capital is only possible with no trades;
    # any exposure must be reflected in the curve.
    if result.trades:
        assert result.equity_curve.iloc[-1] != pytest.approx(1_000_000, abs=0.01)


def test_all_losing_trades_cannot_produce_positive_return():
    """Two losing trades must not yield a +36% equity curve."""
    series = make_series(n=900, trend=0.0004, seed=23)

    def always_lose(frame: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=frame.index)
        # enter every 80 bars, stop just below the next open, target far away
        out["entry_signal"] = [i % 80 == 0 for i in range(len(frame))]
        out["stop"] = frame["close"].shift(1) * 0.985
        out["target"] = frame["close"].shift(1) * 1.60
        return out

    result = run_backtest(series, always_lose, BacktestConfig(), "always-lose")
    losing = [t for t in result.trades if t.pnl < 0]
    assert losing, "fixture should produce losing trades"
    if not [t for t in result.trades if t.pnl > 0]:
        assert result.metrics["total_return_pct"] < 0
        assert result.metrics["final_equity"] < 1_000_000
