"""Market overview and screener services.

Both are deliberately explicit about *what they filtered on*: a screener result
is a list of research candidates with the conditions printed next to it, never a
list of BUY calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from backend.analytics import indicators as ind
from backend.core.logging import get_logger
from backend.data.registry import DataRegistry
from backend.data.universe import INSTRUMENTS, INDEX_MEMBERSHIP, Instrument

log = get_logger("services.market")

INDEX_DISPLAY = [
    ("NIFTY 50", "NIFTY 50"),
    ("NIFTY BANK", "NIFTY BANK"),
    ("NIFTY FIN SERVICE", "NIFTY FIN SERVICE"),
    ("NIFTY MIDCAP 100", "NIFTY MIDCAP 100"),
    ("NIFTY SMALLCAP 100", "NIFTY SMALLCAP 100"),
]


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Tiny in-process TTL cache. Deliberately not Redis: one process, one user."""

    def __init__(self, ttl: float = 30.0) -> None:
        self.ttl = ttl
        self._store: dict[str, _CacheEntry] = {}

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: float | None = None) -> Any:
        now = time.time()
        entry = self._store.get(key)
        if entry and entry.expires_at > now:
            return entry.value
        value = factory()
        self._store[key] = _CacheEntry(value, now + (ttl or self.ttl))
        return value

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache(ttl=45.0)


def _index_snapshot(registry: DataRegistry, name: str) -> dict[str, Any]:
    res = registry.index_history(name, lookback=300)
    series = res.value
    close = series.frame["close"]
    sma50 = ind.sma(close, 50)
    sma200 = ind.sma(close, 200)
    return {
        "name": name,
        "last": round(float(close.iloc[-1]), 2),
        "change_pct": round(float(close.iloc[-1] / close.iloc[-2] - 1) * 100, 2),
        "change_1w_pct": round(float(close.iloc[-1] / close.iloc[-6] - 1) * 100, 2)
        if len(close) > 6 else None,
        "change_1m_pct": round(float(close.iloc[-1] / close.iloc[-22] - 1) * 100, 2)
        if len(close) > 22 else None,
        "change_1y_pct": round(float(close.iloc[-1] / close.iloc[-252] - 1) * 100, 2)
        if len(close) > 252 else None,
        "sma50": None if np.isnan(sma50.iloc[-1]) else round(float(sma50.iloc[-1]), 2),
        "sma200": None if np.isnan(sma200.iloc[-1]) else round(float(sma200.iloc[-1]), 2),
        "rsi14": round(float(ind.rsi(close, 14).iloc[-1]), 1),
        "volatility_pct": round(float(ind.annualised_volatility(close, 20).iloc[-1]) * 100, 2),
        "series": [
            {"date": d.date().isoformat(), "close": round(float(v), 2)}
            for d, v in close.tail(120).items()
        ],
        "provenance": series.meta.model_dump(mode="json"),
        "synthetic": series.meta.is_synthetic,
    }


def market_overview(registry: DataRegistry) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        indices = []
        for name, _ in INDEX_DISPLAY:
            try:
                indices.append(_index_snapshot(registry, name))
            except Exception as exc:  # noqa: BLE001
                log.warning("index %s failed: %s", name, exc)
                indices.append({"name": name, "error": str(exc)})

        movers: dict[str, list[dict[str, Any]]] = {"gainers": [], "losers": [], "active": []}
        sectors: dict[str, list[float]] = {}
        breadth = {"advances": 0, "declines": 0, "unchanged": 0}
        rows: list[dict[str, Any]] = []
        for inst in INSTRUMENTS:
            try:
                res = registry.quote(inst.symbol)
                q = res.value
            except Exception:  # noqa: BLE001
                continue
            rows.append(
                {
                    "symbol": inst.symbol,
                    "name": inst.name,
                    "sector": inst.sector,
                    "last": q.last_price,
                    "change_pct": q.change_pct,
                    "volume": q.volume,
                    "week52_high": q.week52_high,
                    "week52_low": q.week52_low,
                }
            )
            if q.change_pct > 0.05:
                breadth["advances"] += 1
            elif q.change_pct < -0.05:
                breadth["declines"] += 1
            else:
                breadth["unchanged"] += 1
            sectors.setdefault(inst.sector, []).append(q.change_pct)

        movers["gainers"] = sorted(rows, key=lambda r: r["change_pct"], reverse=True)[:8]
        movers["losers"] = sorted(rows, key=lambda r: r["change_pct"])[:8]
        movers["active"] = sorted(rows, key=lambda r: r["volume"], reverse=True)[:8]

        sector_rows = [
            {
                "sector": sector,
                "avg_change_pct": round(float(np.mean(changes)), 2),
                "constituents": len(changes),
                "advancing_pct": round(
                    sum(1 for c in changes if c > 0) / len(changes) * 100, 1
                ),
            }
            for sector, changes in sectors.items()
        ]
        sector_rows.sort(key=lambda r: r["avg_change_pct"], reverse=True)

        adv = breadth["advances"]
        dec = breadth["declines"]
        nifty = next((i for i in indices if i.get("name") == "NIFTY 50"), {})
        vol = nifty.get("volatility_pct") or 0.0
        regime = (
            "RISK_ON" if nifty.get("sma50") and nifty.get("sma200")
            and nifty["sma50"] > nifty["sma200"] and (nifty.get("change_1m_pct") or 0) > 0
            else "RISK_OFF" if nifty.get("sma50") and nifty.get("sma200")
            and nifty["sma50"] < nifty["sma200"]
            else "MIXED"
        )
        synthetic = any(i.get("synthetic") for i in indices)
        return {
            "indices": indices,
            "movers": movers,
            "sectors": sector_rows,
            "breadth": {
                **breadth,
                "advance_decline_ratio": round(adv / dec, 2) if dec else None,
                "universe_size": len(rows),
            },
            "regime": regime,
            "volatility_pct": vol,
            "vix_note": (
                "India VIX is not available from the configured sources. The figure "
                "above is 20-day realised volatility of the index, which is a proxy."
            ),
            "unavailable": [
                "India VIX (implied volatility index)",
                "FII/DII cash-market flows",
                "Global indices and overnight cues",
                "Currency, crude and bond yields",
            ],
            "is_synthetic": synthetic,
            "provenance": indices[0].get("provenance") if indices else None,
            "as_of": indices[0].get("series", [{}])[-1].get("date") if indices else None,
        }

    return cache.get_or_set("market_overview", build)


# ------------------------------------------------------------------ screener

SCANNER_CATALOGUE: list[dict[str, Any]] = [
    {"key": "quality", "name": "Fundamentally strong",
     "description": "Composite fundamental quality score at or above 65/100."},
    {"key": "high_roce", "name": "High ROCE",
     "description": "ROCE at or above 18% (non-financials only)."},
    {"key": "high_roe", "name": "High ROE",
     "description": "ROE at or above 16%."},
    {"key": "low_debt", "name": "Low debt",
     "description": "Debt-to-equity at or below 0.30 (non-financials only)."},
    {"key": "consistent_growth", "name": "Consistent earnings growth",
     "description": "Revenue grew in at least 80% of the years available."},
    {"key": "cash_positive", "name": "Cash-flow positive",
     "description": "CFO/PAT at or above 1.0 and free cash flow positive."},
    {"key": "promoter_holding", "name": "Stable promoter holding",
     "description": "Promoter holding at or above 40% with less than 5% pledge."},
    {"key": "institutional", "name": "Institutional ownership",
     "description": "Combined FII + DII holding at or above 25%."},
    {"key": "breakout", "name": "Breakout candidates",
     "description": "Close above the 55-day high with volume at least 1.3x the 20-day average."},
    {"key": "momentum", "name": "Momentum candidates",
     "description": "Six-month return above 10% and price above the 100-day EMA."},
    {"key": "relative_strength", "name": "Relative strength",
     "description": "Three-month return above the NIFTY 50 three-month return by 5pp or more."},
    {"key": "volume_expansion", "name": "Volume expansion",
     "description": "Latest volume at least 2x the 20-day average."},
    {"key": "oversold", "name": "Oversold",
     "description": "RSI(14) at or below 30."},
    {"key": "overbought", "name": "Overbought",
     "description": "RSI(14) at or above 70."},
    {"key": "sector_leaders", "name": "Sector leaders",
     "description": "Best one-month performer within each sector."},
    {"key": "unusual_activity", "name": "Unusual price-volume activity",
     "description": "Daily move at least 2.5% with volume at least 2x average."},
]


def _fundamental_row(registry: DataRegistry, inst: Instrument) -> dict[str, Any]:
    from backend.analytics.fundamental import analyse_fundamentals

    fund = registry.fundamentals(inst.symbol)
    analysis = analyse_fundamentals(fund.value)
    latest = analysis.latest
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "sector": inst.sector,
        "quality_score": analysis.quality_score,
        "quality_band": analysis.quality_band,
        "roe_pct": None if latest.roe is None else round(latest.roe * 100, 2),
        "roce_pct": None if latest.roce is None else round(latest.roce * 100, 2),
        "debt_to_equity": None if latest.debt_to_equity is None else round(latest.debt_to_equity, 2),
        "cfo_to_pat": None if latest.cfo_to_pat is None else round(latest.cfo_to_pat, 2),
        "fcf_cr": round(latest.fcf, 1),
        "revenue_cagr_3y_pct": None
        if analysis.revenue_cagr_3y is None
        else round(analysis.revenue_cagr_3y * 100, 2),
        "promoter_holding_pct": analysis.promoter_holding_pct,
        "promoter_pledge_pct": analysis.promoter_pledge_pct,
        "institutional_pct": analysis.institutional_pct,
        "growth_consistency_pct": None
        if analysis.eps_consistency is None
        else round(analysis.eps_consistency * 100, 1),
        "is_financial": analysis.is_financial,
    }


def _technical_row(registry: DataRegistry, inst: Instrument, benchmark_3m: float) -> dict[str, Any]:
    series = registry.history(inst.symbol, lookback=300).value
    frame = ind.enrich(series.frame)
    clean = frame.dropna(subset=["rsi14"])
    if clean.empty:
        raise ValueError("no indicator data")
    row = clean.iloc[-1]
    close = float(row["close"])
    prior_high_55 = float(frame["high"].rolling(55).max().iloc[-2]) if len(frame) > 56 else close
    ret_3m = close / float(frame["close"].iloc[-64]) - 1 if len(frame) > 64 else 0.0
    ret_6m = close / float(frame["close"].iloc[-127]) - 1 if len(frame) > 127 else 0.0
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "sector": inst.sector,
        "last": round(close, 2),
        "change_pct": round(float(row["ret_1d"]) * 100, 2) if row["ret_1d"] == row["ret_1d"] else 0.0,
        "rsi14": round(float(row["rsi14"]), 1),
        "adx14": None if row["adx14"] != row["adx14"] else round(float(row["adx14"]), 1),
        "ema50": round(float(row["ema50"]), 2) if row["ema50"] == row["ema50"] else None,
        "ema200": round(float(row["ema200"]), 2) if row["ema200"] == row["ema200"] else None,
        "above_200dma": bool(row["ema200"] == row["ema200"] and close > row["ema200"]),
        "volume_ratio": None if row["vol_ratio"] != row["vol_ratio"] else round(float(row["vol_ratio"]), 2),
        "breakout_55d": bool(close > prior_high_55),
        "return_3m_pct": round(ret_3m * 100, 2),
        "return_6m_pct": round(ret_6m * 100, 2),
        "relative_strength_3m_pp": round((ret_3m - benchmark_3m) * 100, 2),
        "atr14": round(float(row["atr14"]), 2),
    }


def run_screener(
    registry: DataRegistry,
    *,
    scans: list[str] | None = None,
    sector: str | None = None,
    symbols: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    scans = scans or ["quality"]
    unknown = [s for s in scans if s not in {c["key"] for c in SCANNER_CATALOGUE}]
    if unknown:
        raise ValueError(f"unknown scan(s): {unknown}")

    universe = [i for i in INSTRUMENTS if (not sector or i.sector == sector)]
    if symbols:
        wanted = {s.upper() for s in symbols}
        universe = [i for i in universe if i.symbol in wanted]

    needs_fundamental = bool(
        set(scans) & {"quality", "high_roce", "high_roe", "low_debt", "consistent_growth",
                      "cash_positive", "promoter_holding", "institutional"}
    )
    needs_technical = bool(
        set(scans) & {"breakout", "momentum", "relative_strength", "volume_expansion",
                      "oversold", "overbought", "sector_leaders", "unusual_activity"}
    )

    benchmark_3m = 0.0
    if needs_technical:
        try:
            nifty = registry.index_history("NIFTY 50", lookback=100).value.frame["close"]
            benchmark_3m = float(nifty.iloc[-1] / nifty.iloc[-64] - 1)
        except Exception:  # noqa: BLE001
            benchmark_3m = 0.0

    rows: list[dict[str, Any]] = []
    for inst in universe:
        row: dict[str, Any] = {"symbol": inst.symbol, "name": inst.name, "sector": inst.sector}
        try:
            if needs_fundamental:
                row.update({k: v for k, v in _fundamental_row(registry, inst).items()
                            if k not in {"symbol", "name", "sector"}})
            if needs_technical:
                row.update({k: v for k, v in _technical_row(registry, inst, benchmark_3m).items()
                            if k not in {"symbol", "name", "sector"}})
        except Exception as exc:  # noqa: BLE001
            log.warning("screener skipped %s: %s", inst.symbol, exc)
            continue
        row["matches"] = _match_scans(row, scans)
        if row["matches"]:
            rows.append(row)

    # sector_leaders needs cross-sectional comparison, so it is applied after.
    if "sector_leaders" in scans:
        for inst in universe:
            if any(r["symbol"] == inst.symbol for r in rows):
                continue
        by_sector: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_sector.setdefault(row["sector"], []).append(row)
    rows.sort(key=lambda r: (len(r["matches"]), r.get("quality_score") or 0), reverse=True)

    conditions = [
        f"{c['name']}: {c['description']}"
        for c in SCANNER_CATALOGUE
        if c["key"] in scans
    ]
    return {
        "scans": scans,
        "conditions": conditions,
        "universe": len(universe),
        "needs_fundamental": needs_fundamental,
        "needs_technical": needs_technical,
        "results": rows[:limit],
        "result_count": len(rows),
        "all_scan_definitions": SCANNER_CATALOGUE,
        "disclaimer": (
            "Screener output is a list of research candidates, not recommendations to "
            "buy. Every condition that produced the list is printed above."
        ),
    }


def _match_scans(row: dict[str, Any], scans: list[str]) -> list[str]:
    hits: list[str] = []
    for scan in scans:
        if scan == "quality" and (row.get("quality_score") or 0) >= 65:
            hits.append(scan)
        elif scan == "high_roce" and not row.get("is_financial", False) and (row.get("roce_pct") or 0) >= 18:
            hits.append(scan)
        elif scan == "high_roe" and (row.get("roe_pct") or 0) >= 16:
            hits.append(scan)
        elif scan == "low_debt" and not row.get("is_financial", False) and row.get("debt_to_equity") is not None and row["debt_to_equity"] <= 0.30:
            hits.append(scan)
        elif scan == "consistent_growth" and (row.get("revenue_cagr_3y_pct") or 0) > 0 and (row.get("growth_consistency_pct") or 0) >= 80:
            hits.append(scan)
        elif scan == "cash_positive" and (row.get("cfo_to_pat") or 0) >= 1.0 and (row.get("fcf_cr") or 0) > 0:
            hits.append(scan)
        elif scan == "promoter_holding" and (row.get("promoter_holding_pct") or 0) >= 40 and (row.get("promoter_pledge_pct") or 0) < 5:
            hits.append(scan)
        elif scan == "institutional" and (row.get("institutional_pct") or 0) >= 25:
            hits.append(scan)
        elif scan == "breakout" and row.get("breakout_55d") and (row.get("volume_ratio") or 0) >= 1.3:
            hits.append(scan)
        elif scan == "momentum" and (row.get("return_6m_pct") or 0) >= 10 and row.get("above_200dma"):
            hits.append(scan)
        elif scan == "relative_strength" and (row.get("relative_strength_3m_pp") or 0) >= 5:
            hits.append(scan)
        elif scan == "volume_expansion" and (row.get("volume_ratio") or 0) >= 2.0:
            hits.append(scan)
        elif scan == "oversold" and (row.get("rsi14") or 100) <= 30:
            hits.append(scan)
        elif scan == "overbought" and (row.get("rsi14") or 0) >= 70:
            hits.append(scan)
        elif scan == "unusual_activity" and abs(row.get("change_pct") or 0) >= 2.5 and (row.get("volume_ratio") or 0) >= 2.0:
            hits.append(scan)
    return hits
