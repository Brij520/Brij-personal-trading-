"""AGENT 05 — Swing Trading Research (4-8 week horizon).

Scans the platform's strategy set for the current symbol, keeps only signals
that fired recently, and constructs an illustrative trade plan with entry,
invalidation, stop and targets. Every plan is submitted to the risk agent for
vetting; this agent cannot approve its own trade.

Output plans are research artefacts. They are never orders.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from, risk_limits_from
from backend.analytics import indicators as ind
from backend.analytics.risk import RiskLimits, TradeProposal, validate_proposal
from backend.core.provenance import Freshness, Verification
from backend.strategies.library import STRATEGIES


class SwingTradingAgent(BaseAgent):
    name = "swing_trading"
    responsibility = "4-8 week swing setups with explicit invalidation and risk check"
    requires = ("ohlcv", "risk_limits")

    RECENT_SIGNAL_BARS = 5

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        frame = bundle.technical_frame
        meta = bundle.series.meta
        is_syn = meta.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else meta.freshness
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED
        )
        limits: RiskLimits = risk_limits_from(ctx)
        close = float(frame["close"].iloc[-1])
        atr = float(frame["atr14"].dropna().iloc[-1]) if frame["atr14"].notna().any() else close * 0.02
        sr = ind.support_resistance(frame, close)

        candidates: list[dict[str, Any]] = []
        for key, spec in STRATEGIES.items():
            if spec.family != "swing":
                continue
            try:
                signals = spec.signal_fn(frame)
            except Exception:  # noqa: BLE001 - one broken strategy must not kill the scan
                continue
            recent = signals.tail(self.RECENT_SIGNAL_BARS)
            fired = recent[recent["entry_signal"].fillna(False)]
            if fired.empty:
                continue
            last = fired.iloc[-1]
            raw_stop = float(last["stop"])
            raw_target = float(last["target"])
            plan = self._build_plan(key, spec.name, close, raw_stop, raw_target, atr, sr)
            decision = validate_proposal(
                TradeProposal(
                    symbol=bundle.symbol,
                    side="LONG",
                    entry=plan["entry"],
                    stop_loss=plan["stop_loss"],
                    target=plan["target"],
                    sector=bundle.instrument.sector,
                    atr=atr,
                    strategy=spec.name,
                ),
                limits,
            )
            plan["risk_check"] = decision.to_dict()
            plan["strategy_key"] = key
            plan["regime"] = spec.regime
            plan["invalidation"] = spec.invalidation
            candidates.append(plan)

        candidates.sort(key=lambda c: (c["risk_check"]["approved"], c["risk_check"]["reward_risk"] or 0), reverse=True)
        approved = [c for c in candidates if c["risk_check"]["approved"]]

        evidence: list[Evidence] = []
        for c in candidates[:4]:
            evidence.append(
                Evidence(
                    claim=(
                        f"{c['strategy']}: entry {c['entry']:.2f}, stop {c['stop_loss']:.2f}, "
                        f"target {c['target']:.2f}, R:R {c['risk_check']['reward_risk']}"
                    ),
                    value=c["risk_check"]["reward_risk"],
                    source=f"strategy signal on {meta.source}",
                    as_of=str(meta.period_end),
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            )

        if not candidates:
            return AgentFinding(
                agent=self.name,
                symbol=bundle.symbol,
                headline="No swing setup from the strategy library in the last 5 sessions",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.3,
                evidence=[],
                limitations=[
                    "A filtered scan finding nothing is a valid result; it is not a "
                    "failure and must not be padded with a forced setup."
                ],
                data_quality=bundle.data_quality,
                metrics={"candidates": [], "price": round(close, 2)},
            )

        best = approved[0] if approved else candidates[0]
        score = 35.0 if approved else -10.0
        stance = "BULLISH" if approved else "NEUTRAL"
        headline = (
            f"{len(approved)} risk-approved swing setup(s) of {len(candidates)} fired; "
            f"best: {best['strategy']} at {best['entry']:.2f} "
            f"R:R {best['risk_check']['reward_risk']}"
            if candidates
            else "No setups"
        )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=headline,
            stance=stance,
            score=score,
            confidence=self._quality_cap(bundle.data_quality["score"]) * (0.85 if approved else 0.4),
            evidence=evidence,
            risks=[
                "Signals are generated on end-of-day data; intraday gaps can invalidate "
                "the entry before it fills.",
                "Strategy edges are regime dependent and were not re-optimised for this "
                "symbol — check the backtest for the specific stock.",
            ],
            limitations=[
                "Only end-of-day positioning; no order-book or delivery data.",
                "No corporate-action adjustment of the price series in this release.",
                "Position size uses default platform capital, not Brij's actual capital.",
            ]
            + (["Price data is synthetic demonstration data."] if is_syn else []),
            data_quality=bundle.data_quality,
            metrics={
                "price": round(close, 2),
                "atr14": round(atr, 2),
                "support": sr["support"],
                "resistance": sr["resistance"],
                "candidates": candidates,
                "approved_count": len(approved),
                "capital_assumed": limits.capital,
            },
            warnings=[
                "Research candidate only. No order is placed or staged by this platform."
            ],
        )

    # ------------------------------------------------------------------ plan
    def _build_plan(
        self,
        key: str,
        name: str,
        close: float,
        raw_stop: float,
        raw_target: float,
        atr: float,
        sr: dict[str, list[float]],
    ) -> dict[str, Any]:
        # Entry: next bar above the close, i.e. assume a fill at market on the
        # following session. Stop is structure-based but never tighter than
        # 0.8 ATR (noise) and never wider than 12% (risk discipline).
        entry = round(close, 2)
        stop = raw_stop if np.isfinite(raw_stop) else close - 2 * atr
        stop = min(stop, entry - 0.8 * atr)
        stop = max(stop, entry * 0.88)
        if sr.get("support"):
            nearest = sr["support"][0]
            if entry * 0.88 < nearest * 0.985 < entry - 0.8 * atr:
                stop = round(nearest * 0.985, 2)
        stop = round(stop, 2)
        risk_per_share = entry - stop
        target = raw_target if np.isfinite(raw_target) else entry + 2.5 * risk_per_share
        # Respect the nearest resistance cluster as a realistic first target.
        if sr.get("resistance"):
            nearest_res = sr["resistance"][0]
            if entry < nearest_res < entry + 2.0 * risk_per_share:
                target = round(nearest_res, 2)
        target = round(max(target, entry + 1.5 * risk_per_share), 2)
        return {
            "strategy": name,
            "entry": entry,
            "entry_note": "indicative fill at the next session's price; not an order",
            "stop_loss": stop,
            "target": target,
            "risk_per_share": round(risk_per_share, 2),
            "atr": round(atr, 2),
            "stop_in_atr": round(risk_per_share / atr, 2) if atr else None,
            "holding_period": "4-8 weeks (research horizon)",
        }
