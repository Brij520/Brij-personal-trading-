"""Shared research bundle: one fetch, many consumers.

Agents must not each hit the data layer. The orchestrator builds a
:class:`ResearchBundle` once per symbol, and every agent reads from it. That
guarantees a single consistent snapshot: same prices, same statements, same
timestamps, same data-quality verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from backend.analytics import indicators as ind
from backend.analytics.fundamental import FundamentalAnalysis, analyse_fundamentals
from backend.analytics.risk import RiskLimits
from backend.core.errors import ProviderUnavailable
from backend.core.provenance import DatasetMeta, assess_quality, utcnow
from backend.data.providers.base import Fundamentals, Series
from backend.data.registry import DataRegistry
from backend.data.universe import Instrument, get_instrument


@dataclass
class ResearchBundle:
    symbol: str
    instrument: Instrument
    series: Series
    quote: Any
    fundamentals: Fundamentals
    analysis: FundamentalAnalysis
    technical_frame: pd.DataFrame
    data_quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    price: float = 0.0
    built_at: datetime = field(default_factory=utcnow)

    @property
    def is_synthetic(self) -> bool:
        return self.series.meta.is_synthetic

    def latest_technical(self) -> dict[str, Any]:
        frame = self.technical_frame.dropna(subset=["rsi14"]).tail(1)
        if frame.empty:
            return {}
        row = frame.iloc[0]
        out: dict[str, Any] = {}
        for key in (
            "close", "ema20", "ema50", "ema200", "sma50", "rsi14", "macd",
            "macd_signal", "macd_hist", "atr14", "adx14", "plus_di", "minus_di",
            "bb_upper", "bb_lower", "bb_width", "stoch_k", "vol_ratio", "vol20",
        ):
            if key in frame.columns and pd.notna(row[key]):
                out[key] = round(float(row[key]), 4)
        return out


def build_bundle(
    registry: DataRegistry,
    symbol: str,
    *,
    lookback: int = 750,
    risk_limits: RiskLimits | None = None,
) -> ResearchBundle:
    symbol = symbol.upper().strip()
    instrument = get_instrument(symbol)
    if instrument is None:
        raise ProviderUnavailable(f"{symbol} is not in the supported universe.")

    hist = registry.history(symbol, lookback=lookback)
    quote_res = registry.quote(symbol)
    fund_res = registry.fundamentals(symbol)
    series: Series = hist.value  # type: ignore[assignment]
    fundamentals: Fundamentals = fund_res.value  # type: ignore[assignment]
    analysis = analyse_fundamentals(fundamentals)

    frame = ind.enrich(series.frame)
    warnings = list(hist.warnings) + list(quote_res.warnings) + list(fund_res.warnings)
    quality = assess_quality(series.meta, bars=len(series))
    if analysis.insufficient:
        quality["notes"].extend(analysis.insufficient)
        quality["score"] = max(0, quality["score"] - 5)

    return ResearchBundle(
        symbol=symbol,
        instrument=instrument,
        series=series,
        quote=quote_res.value,
        fundamentals=fundamentals,
        analysis=analysis,
        technical_frame=frame,
        data_quality=quality,
        warnings=sorted(set(warnings)),
        price=float(series.frame["close"].iloc[-1]),
    )


def market_meta(registry: DataRegistry, index_name: str, lookback: int = 400) -> dict[str, Any]:
    """Index history plus quality assessment for the market agent."""
    res = registry.index_history(index_name, lookback=lookback)
    series: Series = res.value  # type: ignore[assignment]
    return {
        "index": index_name,
        "series": series,
        "quality": assess_quality(series.meta, bars=len(series)),
        "warnings": res.warnings,
    }


def frame_meta(bundle: ResearchBundle) -> DatasetMeta:
    return bundle.series.meta
