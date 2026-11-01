"""Strategy modules.

Every strategy exposes the same contract::

    STRATEGY = StrategySpec(
        key=..., name=..., description=..., signal_fn=..., ...

    )

and ``signal_fn(frame) -> DataFrame`` with ``entry_signal``, ``stop``,
``target`` columns. Stops and targets are structural (swing lows, ATR multiples
or recent ranges) and never derived from future bars.

A strategy being present here means it is *implementable and testable*. It does
not mean it is profitable. Every backtest is reported with costs, slippage and
an out-of-sample check before anything is considered usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from backend.analytics import indicators as ind


@dataclass(frozen=True)
class StrategySpec:
    key: str
    name: str
    family: str
    description: str
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame]
    #: Honest statement of the regime in which the idea is supposed to work.
    regime: str
    invalidation: str
    parameters: dict[str, float]
    anti_lookahead: str = (
        "All indicators use data up to and including bar t; execution happens at "
        "the open of bar t+1 in the backtester."
    )

    def summary(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "family": self.family,
            "description": self.description,
            "regime": self.regime,
            "invalidation": self.invalidation,
            "parameters": self.parameters,
            "anti_lookahead": self.anti_lookahead,
        }


def _empty_like(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_signal": pd.Series(False, index=frame.index),
            "stop": pd.Series(np.nan, index=frame.index),
            "target": pd.Series(np.nan, index=frame.index),
        }
    )


# ------------------------------------------------------------ 1. trend follow

def trend_following(frame: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """EMA fast/slow crossover continuation.

    Long only when the slow EMA is rising (regime filter) and price is above it.
    Horizontal-EMA whipsaw is reduced with a 0.3% buffer on the cross.
    """
    out = _empty_like(frame)
    ema_fast = ind.ema(frame["close"], fast)
    ema_slow = ind.ema(frame["close"], slow)
    atr = ind.atr(frame, 14)
    rising = ema_slow.diff(10) > 0
    cross = (ema_fast > ema_slow * 1.003) & (ema_fast.shift(1) <= ema_slow.shift(1) * 1.003)
    signal = cross & rising & (frame["close"] > ema_slow)
    out["entry_signal"] = signal.fillna(False)
    out["stop"] = (frame["close"] - 2.0 * atr).round(2)
    out["target"] = (frame["close"] + 5.0 * atr).round(2)
    return out


# ---------------------------------------------------------------- 2. breakout

def breakout(frame: pd.DataFrame, lookback: int = 55, atr_mult_stop: float = 2.0) -> pd.DataFrame:
    """Donchian channel breakout with a volume confirmation filter."""
    out = _empty_like(frame)
    prior_high = frame["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    atr = ind.atr(frame, 14)
    vol_ok = frame["volume"] > frame["volume"].rolling(20, min_periods=20).mean() * 1.3
    close_above = frame["close"] > prior_high
    out["entry_signal"] = (close_above & vol_ok).fillna(False)
    out["stop"] = (frame["close"] - atr_mult_stop * atr).round(2)
    out["target"] = (frame["close"] + 3 * (frame["close"] - out["stop"])).round(2)
    return out


# ---------------------------------------------------------------- 3. pullback

def pullback(frame: pd.DataFrame) -> pd.DataFrame:
    """Buy the dip inside an uptrend.

    Conditions: price above a rising EMA200, RSI(14) dipped below 45 and has
    turned back up, and price is holding above the EMA50.
    """
    out = _empty_like(frame)
    ema50 = ind.ema(frame["close"], 50)
    ema200 = ind.ema(frame["close"], 200)
    rsi = ind.rsi(frame["close"], 14)
    atr = ind.atr(frame, 14)
    uptrend = (frame["close"] > ema200) & (ema200.diff(20) > 0)
    dip = (rsi.shift(1) < 45) & (rsi > rsi.shift(1)) & (frame["close"] > ema50 * 0.99)
    out["entry_signal"] = (uptrend & dip).fillna(False)
    out["stop"] = (np.minimum(frame["close"] - 2 * atr, frame["low"].rolling(10).min() * 0.995)).round(2)
    out["target"] = (frame["close"] + 4 * atr).round(2)
    return out


# ------------------------------------------------------------- 4. momentum/RS

def momentum(frame: pd.DataFrame, lookback: int = 126, threshold: float = 0.10) -> pd.DataFrame:
    """Absolute momentum: enter after a sustained 6-month return, trend-confirmed."""
    out = _empty_like(frame)
    ret = frame["close"].pct_change(lookback)
    ema100 = ind.ema(frame["close"], 100)
    atr = ind.atr(frame, 14)
    cond = (ret > threshold) & (frame["close"] > ema100) & (ret.shift(1) <= threshold)
    out["entry_signal"] = cond.fillna(False)
    out["stop"] = (frame["close"] - 2.5 * atr).round(2)
    out["target"] = (frame["close"] + 5 * atr).round(2)
    return out


# ------------------------------------------------------------ 5. mean revert

def mean_reversion(frame: pd.DataFrame, window: int = 20, z_entry: float = -2.0) -> pd.DataFrame:
    """Bollinger lower-band reversion, only when the longer trend is not broken."""
    out = _empty_like(frame)
    bb = ind.bollinger(frame["close"], window)
    z = (frame["close"] - bb["mid"]) / (bb["upper"] - bb["mid"]).replace(0, np.nan) * 2
    rsi = ind.rsi(frame["close"], 14)
    not_broken = frame["close"] > ind.ema(frame["close"], 200) * 0.93
    cond = (z < z_entry) & (rsi < 35) & not_broken
    out["entry_signal"] = cond.fillna(False)
    out["stop"] = (frame["close"] * 0.965).round(2)
    out["target"] = bb["mid"].round(2)
    return out


# ------------------------------------------------------- 6. MA cross (classic)

def ma_crossover(frame: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    out = _empty_like(frame)
    ma_f = ind.sma(frame["close"], fast)
    ma_s = ind.sma(frame["close"], slow)
    atr = ind.atr(frame, 14)
    cross = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
    out["entry_signal"] = cross.fillna(False)
    out["stop"] = (frame["close"] - 2 * atr).round(2)
    out["target"] = (frame["close"] + 4 * atr).round(2)
    return out


# ------------------------------------------------------- 7. volume breakout

def volume_breakout(frame: pd.DataFrame, lookback: int = 20, vol_mult: float = 2.0) -> pd.DataFrame:
    out = _empty_like(frame)
    prior = frame["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    vol_spike = frame["volume"] > frame["volume"].rolling(20).mean() * vol_mult
    cond = (frame["close"] > prior) & vol_spike
    atr = ind.atr(frame, 14)
    out["entry_signal"] = cond.fillna(False)
    out["stop"] = (frame["low"].rolling(5).min() * 0.998).round(2)
    out["target"] = (frame["close"] + 3 * atr).round(2)
    return out


# ------------------------------------------------ 8. opening range breakout

def opening_range_breakout(
    frame: pd.DataFrame, or_minutes: int = 15, atr_mult: float = 1.5
) -> pd.DataFrame:
    """Intraday ORB. Requires an intraday frame (5m/15m).

    The opening range is the first ``or_minutes`` of the session; entry is a
    close above that range with volume expansion.
    """
    out = _empty_like(frame)
    if not isinstance(frame.index, pd.DatetimeIndex):
        return out
    per_day = frame.groupby(frame.index.normalize())
    bars_per_or = max(1, or_minutes // 15)
    or_high = pd.Series(index=frame.index, dtype=float)
    or_low = pd.Series(index=frame.index, dtype=float)
    for _, group in per_day:
        head = group.iloc[:bars_per_or]
        or_high.loc[group.index] = float(head["high"].max())
        or_low.loc[group.index] = float(head["low"].min())
    atr = ind.atr(frame, 14)
    # Only consider bars after the opening range itself.
    position_in_day = frame.groupby(frame.index.normalize()).cumcount()
    cond = (position_in_day >= bars_per_or) & (frame["close"] > or_high) & (frame["volume"] > frame["volume"].rolling(10).mean())
    out["entry_signal"] = cond.fillna(False)
    out["stop"] = (or_low).round(2)
    out["target"] = (frame["close"] + atr_mult * 2 * (frame["close"] - or_low)).round(2)
    return out


STRATEGIES: dict[str, StrategySpec] = {
    "trend_following": StrategySpec(
        key="trend_following",
        name="Trend Following (EMA 50/200)",
        family="swing",
        description=(
            "Enter on a fresh EMA50/EMA200 bullish cross while EMA200 is rising, "
            "with a 0.3% buffer to avoid whipsaw. Stop 2 ATR below, target 5 ATR."
        ),
        signal_fn=trend_following,
        regime="Persistent directional trends; performs poorly in ranges.",
        invalidation="Close below EMA200 or a 2 ATR adverse move.",
        parameters={"fast": 50, "slow": 200, "stop_atr": 2.0, "target_atr": 5.0},
    ),
    "breakout": StrategySpec(
        key="breakout",
        name="Donchian Breakout (55-day)",
        family="swing",
        description=(
            "55-day high breakout confirmed by volume at least 1.3x the 20-day "
            "average. Stop 2 ATR; target 3R."
        ),
        signal_fn=breakout,
        regime="Low-volatility consolidation followed by expansion.",
        invalidation="Fall back below the breakout level.",
        parameters={"lookback": 55, "stop_atr": 2.0, "target_r": 3.0},
    ),
    "pullback": StrategySpec(
        key="pullback",
        name="Trend Pullback (RSI reset)",
        family="swing",
        description=(
            "Buy a controlled dip inside an established uptrend: RSI(14) under 45 "
            "and turning up while price holds the EMA50 and EMA200 is rising."
        ),
        signal_fn=pullback,
        regime="Established uptrends with orderly corrections.",
        invalidation="Close below the 10-day low or the EMA200.",
        parameters={"rsi_dip": 45, "fast_ema": 50, "slow_ema": 200},
    ),
    "momentum": StrategySpec(
        key="momentum",
        name="Absolute Momentum (6-month)",
        family="swing",
        description=(
            "Enter when the 126-day return crosses above 10% with price above the "
            "EMA100. Captures intermediate-term persistence."
        ),
        signal_fn=momentum,
        regime="Broad bullish phases with sector leadership.",
        invalidation="Momentum decays below zero or price loses EMA100.",
        parameters={"lookback": 126, "threshold_pct": 10},
    ),
    "mean_reversion": StrategySpec(
        key="mean_reversion",
        name="Bollinger Mean Reversion",
        family="swing",
        description=(
            "Buy 2-sigma lower-band tags with RSI under 35 in a market whose "
            "long-term trend is not broken. Target the 20-day mean."
        ),
        signal_fn=mean_reversion,
        regime="Range-bound, low-trend markets. Structurally exposed in crashes.",
        invalidation="A close below the 7-day low, or the trend filter breaking.",
        parameters={"window": 20, "z_entry": -2.0},
    ),
    "ma_crossover": StrategySpec(
        key="ma_crossover",
        name="SMA 20/50 Crossover (baseline)",
        family="swing",
        description="Classic SMA 20/50 cross. Included mainly as a naive baseline.",
        signal_fn=ma_crossover,
        regime="Trending markets; whipsaws badly in chop.",
        invalidation="Reverse cross.",
        parameters={"fast": 20, "slow": 50},
    ),
    "volume_breakout": StrategySpec(
        key="volume_breakout",
        name="Volume Breakout (20-day, 2x volume)",
        family="swing",
        description=(
            "20-day high with volume at least 2x the 20-day average. A stricter "
            "variant of the Donchian breakout."
        ),
        signal_fn=volume_breakout,
        regime="News or earnings-driven expansion.",
        invalidation="Immediate loss of the breakout level.",
        parameters={"lookback": 20, "vol_mult": 2.0},
    ),
    "opening_range_breakout": StrategySpec(
        key="opening_range_breakout",
        name="Opening Range Breakout (15 min)",
        family="intraday",
        description=(
            "Intraday: break of the first 15 minutes' range with volume "
            "confirmation. Requires an intraday frame. Paper research only."
        ),
        signal_fn=opening_range_breakout,
        regime="Trending sessions with a clear open.",
        invalidation="Return inside the opening range.",
        parameters={"or_minutes": 15, "target_mult": 1.5},
    ),
}


def get_strategy(key: str) -> StrategySpec:
    if key not in STRATEGIES:
        raise KeyError(f"unknown strategy {key!r}; available: {sorted(STRATEGIES)}")
    return STRATEGIES[key]


def list_strategies() -> list[dict[str, object]]:
    return [spec.summary() for spec in STRATEGIES.values()]
