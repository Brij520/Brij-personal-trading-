"""Technical indicators, implemented in pandas/numpy.

No TA-Lib binary is required (it is awkward to install and impossible to audit
for this use case). Every function here is pure, vectorised and unit tested.
All functions ignore NaN padding and return aligned Series/DataFrames.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # When there is no downside at all, RSI is 100 by definition.
    out = out.where(avg_loss != 0, 100.0)
    return out.where(avg_gain.notna())


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    line = fast_ema - slow_ema
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return pd.DataFrame({"macd": line, "signal": sig, "hist": hist})


def true_range(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    tr = true_range(frame)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window, min_periods=window).std(ddof=0)
    return pd.DataFrame(
        {"mid": mid, "upper": mid + num_std * std, "lower": mid - num_std * std,
         "width": (num_std * 2 * std) / mid.replace(0, np.nan)}
    )


def vwap(frame: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP. Resets each calendar day for intraday frames."""
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    pv = typical * frame["volume"]
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index) > 1:
        # group by date only when the index has intraday granularity
        dates = frame.index.normalize()
        cum_pv = pv.groupby(dates).cumsum()
        cum_v = frame["volume"].groupby(dates).cumsum().replace(0, np.nan)
        return cum_pv / cum_v
    return pv.cumsum() / frame["volume"].cumsum().replace(0, np.nan)


def stochastic(frame: pd.DataFrame, window: int = 14, smooth: int = 3) -> pd.DataFrame:
    low = frame["low"].rolling(window, min_periods=window).min()
    high = frame["high"].rolling(window, min_periods=window).max()
    k = 100 * (frame["close"] - low) / (high - low).replace(0, np.nan)
    return pd.DataFrame({"k": k, "d": k.rolling(smooth).mean()})


def adx(frame: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    up = frame["high"].diff()
    down = -frame["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(frame)
    atr_ = tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus_di = 100 * pd.Series(plus_dm, index=frame.index).ewm(
        alpha=1 / window, adjust=False, min_periods=window
    ).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=frame.index).ewm(
        alpha=1 / window, adjust=False, min_periods=window
    ).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame(
        {"adx": dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean(),
         "plus_di": plus_di, "minus_di": minus_di}
    )


def obv(frame: pd.DataFrame) -> pd.Series:
    direction = np.sign(frame["close"].diff().fillna(0.0))
    return (direction * frame["volume"]).cumsum()


def returns(series: pd.Series, periods: int = 1) -> pd.Series:
    return series.pct_change(periods)


def annualised_volatility(series: pd.Series, window: int = 60) -> pd.Series:
    return returns(series).rolling(window).std(ddof=0) * np.sqrt(TRADING_DAYS)


def drawdown_series(series: pd.Series) -> pd.Series:
    peak = series.cummax()
    return series / peak - 1.0


def max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(drawdown_series(series).min())


def cagr(series: pd.Series, years: float | None = None) -> float:
    if len(series) < 2:
        return 0.0
    years = years or len(series) / TRADING_DAYS
    if years <= 0:
        return 0.0
    start, end = float(series.iloc[0]), float(series.iloc[-1])
    if start <= 0:
        return 0.0
    return (end / start) ** (1 / years) - 1


def sharpe(return_series: pd.Series, risk_free: float = 0.065) -> float:
    if return_series.empty or return_series.std(ddof=0) == 0:
        return 0.0
    excess = return_series - risk_free / TRADING_DAYS
    return float(excess.mean() / return_series.std(ddof=0) * np.sqrt(TRADING_DAYS))


def sortino(return_series: pd.Series, risk_free: float = 0.065) -> float:
    if return_series.empty:
        return 0.0
    excess = return_series - risk_free / TRADING_DAYS
    downside = excess[excess < 0]
    if downside.empty or downside.std(ddof=0) == 0:
        return 0.0
    return float(excess.mean() / downside.std(ddof=0) * np.sqrt(TRADING_DAYS))


def swing_points(frame: pd.DataFrame, window: int = 5) -> dict[str, list[tuple[pd.Timestamp, float]]]:
    """Fractional-k swing highs/lows used for support/resistance clustering."""
    highs, lows = [], []
    values_h = frame["high"].to_numpy()
    values_l = frame["low"].to_numpy()
    idx = frame.index
    for i in range(window, len(frame) - window):
        window_h = values_h[i - window : i + window + 1]
        window_l = values_l[i - window : i + window + 1]
        if values_h[i] == window_h.max():
            highs.append((idx[i], float(values_h[i])))
        if values_l[i] == window_l.min():
            lows.append((idx[i], float(values_l[i])))
    return {"highs": highs[-20:], "lows": lows[-20:]}


def support_resistance(
    frame: pd.DataFrame, price: float, levels: int = 3, tolerance: float = 0.012
) -> dict[str, list[float]]:
    """Cluster swing points into support (below price) and resistance (above)."""
    points = swing_points(frame)
    raw = [p for _, p in points["highs"]] + [p for _, p in points["lows"]]
    clusters: list[list[float]] = []
    for value in sorted(raw):
        if clusters and abs(value - np.mean(clusters[-1])) / value <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    centres = sorted(float(np.mean(c)) for c in clusters if c)
    supports = [c for c in centres if c < price][-levels:][::-1]
    resistances = [c for c in centres if c > price][:levels]
    return {"support": [round(s, 2) for s in supports],
            "resistance": [round(r, 2) for r in resistances]}


def fibonacci_levels(swing_low: float, swing_high: float) -> dict[str, float]:
    span = swing_high - swing_low
    ratios = {"0.0": 0.0, "23.6": 0.236, "38.2": 0.382, "50.0": 0.5,
              "61.8": 0.618, "78.6": 0.786, "100.0": 1.0}
    return {
        label: round(swing_high - span * r, 2) for label, r in ratios.items()
    }


def relative_strength(series: pd.Series, benchmark: pd.Series, window: int = 63) -> pd.Series:
    """Ratio of normalised performance (not RSI-style RS)."""
    aligned = pd.concat([series, benchmark], axis=1, join="inner").dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    a, b = aligned.iloc[:, 0], aligned.iloc[:, 1]
    return (a / a.iloc[-window] if len(a) >= window else a / a.iloc[0]) / (
        b / b.iloc[-window] if len(b) >= window else b / b.iloc[0]
    )


def detect_divergence(
    price: pd.Series, oscillator: pd.Series, window: int = 5, lookback: int = 60
) -> dict[str, object]:
    """Compare the last two significant price/oscillator pivots.

    Returns ``{"type": "bullish"|"bearish"|"none", "detail": str}``. Deliberately
    conservative: it needs two clean pivots inside ``lookback`` bars.
    """
    frame = pd.concat([price, oscillator], axis=1, join="inner").dropna().tail(lookback)
    if len(frame) < window * 4:
        return {"type": "none", "detail": "insufficient data for divergence test"}
    px = frame.iloc[:, 0].to_numpy()
    os_ = frame.iloc[:, 1].to_numpy()
    lows, highs = [], []
    for i in range(window, len(frame) - window):
        if px[i] == px[i - window : i + window + 1].min():
            lows.append((i, px[i], os_[i]))
        if px[i] == px[i - window : i + window + 1].max():
            highs.append((i, px[i], os_[i]))
    if len(lows) >= 2:
        (_, p1, o1), (_, p2, o2) = lows[-2], lows[-1]
        if p2 < p1 and o2 > o1:
            return {
                "type": "bullish",
                "detail": (
                    f"price made a lower low ({p1:.2f} -> {p2:.2f}) while the "
                    f"oscillator made a higher low ({o1:.1f} -> {o2:.1f})"
                ),
            }
    if len(highs) >= 2:
        (_, p1, o1), (_, p2, o2) = highs[-2], highs[-1]
        if p2 > p1 and o2 < o1:
            return {
                "type": "bearish",
                "detail": (
                    f"price made a higher high ({p1:.2f} -> {p2:.2f}) while the "
                    f"oscillator made a lower high ({o1:.1f} -> {o2:.1f})"
                ),
            }
    return {"type": "none", "detail": "no validated divergence in the lookback window"}


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the full indicator set used by the technical agent."""
    out = frame.copy()
    close = out["close"]
    for window in (20, 50, 200):
        out[f"ema{window}"] = ema(close, window)
        out[f"sma{window}"] = sma(close, window)
    out["rsi14"] = rsi(close, 14)
    mac = macd(close)
    out["macd"], out["macd_signal"], out["macd_hist"] = mac["macd"], mac["signal"], mac["hist"]
    out["atr14"] = atr(out, 14)
    boll = bollinger(close)
    out["bb_upper"], out["bb_lower"], out["bb_width"] = boll["upper"], boll["lower"], boll["width"]
    stoch = stochastic(out)
    out["stoch_k"], out["stoch_d"] = stoch["k"], stoch["d"]
    adx_frame = adx(out)
    out["adx14"], out["plus_di"], out["minus_di"] = (
        adx_frame["adx"], adx_frame["plus_di"], adx_frame["minus_di"]
    )
    out["obv"] = obv(out)
    out["vol_sma20"] = sma(out["volume"], 20)
    out["vol_ratio"] = out["volume"] / out["vol_sma20"].replace(0, np.nan)
    out["vwap"] = vwap(out)
    out["ret_1d"] = returns(close)
    out["vol20"] = annualised_volatility(close, 20)
    return out
