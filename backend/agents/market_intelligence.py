"""AGENT 01 — Market Intelligence.

Assesses the market regime that any other agent's output must be read in.

Inputs: index history for NIFTY 50/BANK/FIN/MIDCAP/SMALLCAP and the universe of
constituent price series (for breadth and sector performance).

Outputs: direction, breadth, sector strength, volatility regime, risk level and
the list of things this agent could **not** verify (global indices, FII/DII
flows, events) rather than inventing them.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.agents.base import AgentContext, AgentError, AgentFinding, BaseAgent, Evidence
from backend.analytics import indicators as ind
from backend.core.provenance import Freshness, Verification
from backend.data.universe import INDEX_MEMBERSHIP, INSTRUMENTS, MIDCAP, NIFTY50, SMALLCAP

INDEX_LIST = ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", MIDCAP, SMALLCAP]


class MarketIntelligenceAgent(BaseAgent):
    name = "market_intelligence"
    responsibility = "Market regime, breadth, sector rotation and market risk"
    requires = ("index_history", "universe_prices")

    def run(self, ctx: AgentContext) -> AgentFinding:
        registry = ctx.registry
        indices: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for name in INDEX_LIST:
            try:
                res = registry.index_history(name, lookback=300)
                series = res.value
                close = series.frame["close"]
                indices[name] = {
                    "index": name,
                    "last": round(float(close.iloc[-1]), 2),
                    "change_1d_pct": round(float(close.iloc[-1] / close.iloc[-2] - 1) * 100, 2),
                    "change_1w_pct": round(float(close.iloc[-1] / close.iloc[-6] - 1) * 100, 2)
                    if len(close) > 6 else None,
                    "change_1m_pct": round(float(close.iloc[-1] / close.iloc[-22] - 1) * 100, 2)
                    if len(close) > 22 else None,
                    "change_3m_pct": round(float(close.iloc[-1] / close.iloc[-64] - 1) * 100, 2)
                    if len(close) > 64 else None,
                    "dma50": round(float(ind.sma(close, 50).iloc[-1]), 2),
                    "dma200": round(float(ind.sma(close, 200).iloc[-1]), 2),
                    "above_200dma": bool(close.iloc[-1] > ind.sma(close, 200).iloc[-1]),
                    "rsi14": round(float(ind.rsi(close, 14).iloc[-1]), 1),
                    "realised_vol_20d_pct": round(
                        float(ind.annualised_volatility(close, 20).iloc[-1]) * 100, 2
                    ),
                    "synthetic": series.meta.is_synthetic,
                }
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {exc}")

        if not indices:
            raise AgentError(self.name, "no index data available; cannot assess the market")

        breadth = self._breadth(registry)
        sectors = self._sector_performance(registry)

        nifty = indices.get("NIFTY 50", next(iter(indices.values())))
        vol = nifty.get("realised_vol_20d_pct") or 0.0
        # A volatility proxy is computed, not fetched. India VIX itself is not
        # available without the derivatives feed, and we say so.
        vol_regime = "LOW" if vol < 12 else "NORMAL" if vol < 18 else "ELEVATED" if vol < 26 else "HIGH"

        score = 0.0
        evidence: list[Evidence] = []
        notes: list[str] = []

        if nifty.get("above_200dma"):
            score += 15
            notes.append("NIFTY 50 is above its 200-day average (primary uptrend intact).")
        else:
            score -= 20
            notes.append("NIFTY 50 is below its 200-day average (primary trend broken).")
        one_m = nifty.get("change_1m_pct")
        if one_m is not None:
            score += float(np.clip(one_m * 0.6, -15, 15))
            notes.append(f"One-month change {one_m:+.2f}%.")
        if nifty.get("dma50") and nifty.get("dma200"):
            if nifty["dma50"] > nifty["dma200"]:
                score += 8
                notes.append("50-DMA above 200-DMA (golden-cross structure).")
            else:
                score -= 8
                notes.append("50-DMA below 200-DMA (death-cross structure).")
        if vol_regime in {"ELEVATED", "HIGH"}:
            score -= 10
        if breadth.get("available"):
            adv_ratio = breadth["advance_decline_ratio"]
            if adv_ratio is not None:
                if adv_ratio > 1.5:
                    score += 10
                    notes.append(f"Breadth positive: {adv_ratio:.2f} advancers per decliner.")
                elif adv_ratio < 0.67:
                    score -= 10
                    notes.append(f"Breadth negative: {adv_ratio:.2f} advancers per decliner.")

        quality_score = 55 if nifty.get("synthetic") else 80
        confidence = self._quality_cap(quality_score) * (0.9 if breadth.get("available") else 0.7)
        score = float(np.clip(score, -100, 100))
        stance = "BULLISH" if score >= 15 else "BEARISH" if score <= -15 else "NEUTRAL"

        worst = "LOW"
        if vol_regime in {"ELEVATED"}:
            worst = "MEDIUM"
        if vol_regime == "HIGH" or (nifty.get("change_1m_pct") or 0) < -8:
            worst = "HIGH"
        if not nifty.get("above_200dma"):
            worst = "MEDIUM" if worst == "LOW" else worst

        meta = registry.index_history("NIFTY 50", lookback=5).value.meta
        for key in ("last",):
            evidence.append(
                Evidence(
                    claim=f"{nifty['index']} level {nifty['last']:,.2f}",
                    value=nifty["last"],
                    source=meta.source,
                    as_of=str(meta.period_end),
                    freshness=meta.freshness,
                    verification=meta.verification,
                    is_synthetic=meta.is_synthetic,
                )
            )
        if breadth.get("available"):
            evidence.append(
                Evidence(
                    claim=(
                        f"Market breadth {breadth['advances']} advancing vs "
                        f"{breadth['declines']} declining of {breadth['total']} stocks"
                    ),
                    value=breadth["advance_decline_ratio"],
                    source="computed from universe price series",
                    freshness=Freshness.SYNTHETIC if nifty.get("synthetic") else Freshness.EOD,
                    verification=Verification.UNVERIFIED_SYNTHETIC
                    if nifty.get("synthetic")
                    else Verification.CROSS_CHECKED,
                    is_synthetic=bool(nifty.get("synthetic")),
                )
            )

        limitations = [
            "India VIX is not fetched. The volatility figure here is 20-day realised "
            "volatility of the index, which is a proxy, not the implied-vol index.",
            "Global indices (US, Asia) and their overnight moves are not available in "
            "this build, so global cues are not assessed.",
            "FII/DII cash-market flows and derivatives positioning require exchange "
            "data feeds not implemented here; institutional activity is not assessed.",
            "No economic calendar is integrated: RBI policy, budget and data-release "
            "dates are not known to this agent.",
        ]
        if failures:
            limitations.extend(failures)
        if nifty.get("synthetic"):
            limitations.append(
                "All index levels and breadth figures are SYNTHETIC demonstration data."
            )

        return AgentFinding(
            agent=self.name,
            headline=(
                f"Market regime {stance.lower()}: {notes[0] if notes else 'no dominant signal'}"
            ),
            stance=stance,
            score=score,
            confidence=confidence,
            evidence=evidence,
            risks=[
                f"Volatility regime {vol_regime} (20-day realised {vol:.1f}%).",
                "Concentration risk if leadership narrows to one or two heavyweights.",
            ],
            limitations=limitations,
            data_quality={"score": quality_score, "band": "MODERATE" if quality_score < 70 else "HIGH"},
            metrics={
                "indices": indices,
                "breadth": breadth,
                "sector_performance": sectors,
                "volatility_regime": vol_regime,
                "market_risk": worst,
                "notes": notes,
            },
        )

    # ------------------------------------------------------------------ parts
    def _breadth(self, registry) -> dict[str, Any]:
        advances = declines = unchanged = 0
        changes: list[float] = []
        for inst in INSTRUMENTS:
            try:
                series = registry.history(inst.symbol, lookback=10).value
                close = series.frame["close"]
                if len(close) < 2:
                    continue
                chg = float(close.iloc[-1] / close.iloc[-2] - 1)
                changes.append(chg)
                if chg > 0.0005:
                    advances += 1
                elif chg < -0.0005:
                    declines += 1
                else:
                    unchanged += 1
            except Exception:  # noqa: BLE001 - partial breadth is still useful
                continue
        total = advances + declines + unchanged
        return {
            "available": total > 0,
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "total": total,
            "advance_decline_ratio": round(advances / declines, 2) if declines else None,
            "pct_above_20dma": None,  # requires a separate pass; declared unavailable
        }

    def _sector_performance(self, registry) -> list[dict[str, Any]]:
        buckets: dict[str, list[float]] = {}
        for inst in INSTRUMENTS:
            try:
                close = registry.history(inst.symbol, lookback=70).value.frame["close"]
                if len(close) < 25:
                    continue
                chg_1m = float(close.iloc[-1] / close.iloc[-22] - 1) * 100
                buckets.setdefault(inst.sector, []).append(chg_1m)
            except Exception:  # noqa: BLE001
                continue
        rows = [
            {
                "sector": sector,
                "avg_1m_pct": round(float(np.mean(vals)), 2),
                "constituents": len(vals),
                "breadth_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
            }
            for sector, vals in buckets.items()
        ]
        rows.sort(key=lambda r: r["avg_1m_pct"], reverse=True)
        return rows
