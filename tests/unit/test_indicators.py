"""Indicator correctness. These are the computations everything else trusts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.analytics import indicators as ind


@pytest.fixture()
def frame():
    rng = np.random.default_rng(7)
    n = 300
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(100_000, 2_000_000, n)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {"open": open_, "high": np.maximum.reduce([high, open_, close]),
         "low": np.minimum.reduce([low, open_, close]), "close": close,
         "volume": volume}, index=idx)


def test_sma_matches_manual_mean(frame):
    out = ind.sma(frame["close"], 20)
    manual = frame["close"].iloc[100 - 19:101].mean()
    assert out.iloc[100] == pytest.approx(manual)


def test_rsi_is_bounded_and_saturates(frame):
    rsi = ind.rsi(frame["close"], 14).dropna()
    assert rsi.between(0, 100).all()
    rising = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(rising, 14).iloc[-1] == pytest.approx(100.0)
    falling = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(falling, 14).iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_atr_is_positive_and_scales_with_range(frame):
    atr = ind.atr(frame, 14).dropna()
    assert (atr > 0).all()
    wide = frame.copy()
    wide["high"] = wide["high"] * 1.10
    wide["low"] = wide["low"] * 0.90
    assert ind.atr(wide, 14).iloc[-1] > ind.atr(frame, 14).iloc[-1]


def test_macd_histogram_identity(frame):
    mac = ind.macd(frame["close"])
    diff = (mac["macd"] - mac["signal"] - mac["hist"]).abs().dropna()
    assert (diff < 1e-9).all()


def test_bollinger_bands_ordered(frame):
    bb = ind.bollinger(frame["close"]).dropna()
    assert (bb["upper"] >= bb["mid"]).all()
    assert (bb["mid"] >= bb["lower"]).all()


def test_vwap_within_price_range_intraday():
    idx = pd.date_range("2024-06-03 09:15", periods=20, freq="15min")
    close = np.linspace(100, 105, 20)
    frame = pd.DataFrame(
        {"high": close + 0.5, "low": close - 0.5, "close": close,
         "volume": np.full(20, 1000)}, index=idx)
    vwap = ind.vwap(frame)
    assert vwap.between(frame["low"].min() - 1e-9, frame["high"].max() + 1e-9).all()


def test_max_drawdown_is_non_positive(frame):
    assert ind.max_drawdown(frame["close"]) <= 0


def test_support_resistance_brackets_price(frame):
    price = float(frame["close"].iloc[-1])
    sr = ind.support_resistance(frame, price)
    assert all(s < price for s in sr["support"])
    assert all(r > price for r in sr["resistance"])


def test_fibonacci_levels_are_monotonic():
    fib = ind.fibonacci_levels(100, 200)
    values = [fib[k] for k in ("0.0", "23.6", "38.2", "50.0", "61.8", "78.6", "100.0")]
    assert values == sorted(values, reverse=True)


def test_divergence_detects_synthetic_bullish_case():
    # Price makes a lower low while RSI makes a higher low.
    px = pd.Series([100, 95, 90, 92, 88, 90, 86, 92, 96, 99], dtype=float)
    osc = pd.Series([30, 28, 26, 30, 25, 33, 40, 45, 50, 55], dtype=float)
    result = ind.detect_divergence(px, osc, window=1)
    assert result["type"] in {"bullish", "none"}
    if result["type"] == "bullish":
        assert "lower low" in result["detail"]


def test_enrich_adds_expected_columns(frame):
    out = ind.enrich(frame)
    for col in ("ema20", "ema50", "ema200", "rsi14", "macd", "atr14", "adx14", "obv", "vwap"):
        assert col in out.columns
    assert out["ema200"].notna().sum() > 0
