"""AGENT 10 — Risk Management (central veto).

This agent is the only one that can stop a proposal, and its rejection cannot be
overridden by any other agent, by the committee, or by the UI. The API exposes
``overridable: false`` on every decision.

It also runs portfolio-level checks: concentration, sector limits, heat and the
daily loss limit. It never places, modifies or cancels an order.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from, risk_limits_from
from backend.analytics.risk import (
    Holding,
    TradeProposal,
    check_exposure,
    concentration,
    validate_proposal,
)
from backend.core.provenance import Freshness, Verification


class RiskManagementAgent(BaseAgent):
    name = "risk_management"
    responsibility = "Position sizing, exposure limits and the right to reject"
    requires = ("risk_limits", "portfolio")

    def run(self, ctx: AgentContext) -> AgentFinding:
        limits = risk_limits_from(ctx)
        bundle = bundle_from(ctx)
        frame = bundle.technical_frame
        atr = float(frame["atr14"].dropna().iloc[-1]) if frame["atr14"].notna().any() else 0.0
        close = float(frame["close"].iloc[-1])
        is_syn = bundle.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else bundle.series.meta.freshness
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED
        )

        # Illustrative proposal derived from the technical structure so the risk
        # agent has something concrete to vet even when no strategy fired.
        stop = round(close - 2 * atr, 2) if atr else round(close * 0.95, 2)
        target = round(close + 4 * atr, 2) if atr else round(close * 1.10, 2)
        proposal = TradeProposal(
            symbol=bundle.symbol,
            side="LONG",
            entry=round(close, 2),
            stop_loss=stop,
            target=target,
            sector=bundle.instrument.sector,
            atr=atr,
            strategy="technical-reference",
            rationale="Reference plan used for risk vetting, not a recommendation.",
        )
        decision = validate_proposal(proposal, limits)

        holdings = self._holdings(ctx)
        exposure = check_exposure(holdings, limits) if holdings else {
            "total_value": 0.0,
            "breaches": [],
            "sector_exposure": [],
            "single_stock": [],
            "concentration": {},
            "note": "No portfolio imported; portfolio-level checks not run.",
        }

        score = 0.0
        risks: list[str] = []
        if not decision.approved:
            score -= 25
            risks.extend(decision.reasons)
        risks.extend(decision.warnings)
        if exposure.get("breaches"):
            score -= 10 * len(exposure["breaches"])
            risks.extend(exposure["breaches"])
        vol = float(frame["vol20"].dropna().iloc[-1]) if frame["vol20"].notna().any() else 0.0
        if vol > 0.45:
            score -= 12
            risks.append(f"Annualised volatility of {vol * 100:.0f}% is very high for a retail position.")

        limits_payload = {
            "capital_assumed": limits.capital,
            "max_risk_per_trade_pct": limits.max_position_risk_pct,
            "max_portfolio_heat_pct": limits.max_portfolio_heat_pct,
            "max_single_stock_pct": limits.max_single_stock_pct,
            "max_sector_pct": limits.max_sector_pct,
            "min_reward_risk": limits.min_reward_risk,
            "daily_loss_limit_pct": limits.daily_loss_limit_pct,
        }
        evidence = [
            Evidence(
                claim=(
                    f"Reference plan: entry {proposal.entry:.2f}, stop {proposal.stop_loss:.2f}, "
                    f"target {proposal.target:.2f} — reward-to-risk {decision.reward_risk}"
                ),
                value=decision.reward_risk,
                source="risk engine",
                as_of=str(bundle.series.meta.period_end),
                freshness=freshness,
                verification=verification,
                is_synthetic=is_syn,
            ),
            Evidence(
                claim=(
                    f"Position sizing at {limits.max_position_risk_pct}% risk: "
                    f"{decision.quantity} shares, INR {decision.position_value:,.0f} exposure, "
                    f"INR {decision.risk_amount:,.0f} at risk"
                ),
                value=decision.quantity,
                source="risk engine",
                freshness=freshness,
                verification=verification,
                is_synthetic=is_syn,
            ),
        ]
        if exposure.get("total_value"):
            evidence.append(
                Evidence(
                    claim=(
                        f"Portfolio value INR {exposure['total_value']:,.0f}; "
                        f"{len(exposure.get('breaches', []))} limit breach(es)"
                    ),
                    value=exposure["total_value"],
                    source="portfolio exposure model",
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=(
                f"Risk {'approves' if decision.approved else 'REJECTS'} the reference plan "
                f"({decision.reward_risk} R, {decision.risk_pct_capital}% of capital at risk)"
                if decision.reward_risk is not None
                else "Risk could not size the reference plan"
            ),
            stance="NEUTRAL",  # risk is not directional; it is a control
            score=float(np.clip(score, -100, 0)),
            confidence=0.95,
            evidence=evidence,
            risks=risks,
            limitations=[
                "Capital is a platform default, not Brij's actual account size. Set it "
                "explicitly before using any size output.",
                "Correlation between simultaneous positions is not modelled; heat is a "
                "sum of individual risks, which understates joint drawdown.",
                "No broker margin or margin-pledge data is available.",
            ],
            data_quality=bundle.data_quality,
            metrics={
                "decision": decision.to_dict(),
                "exposure": exposure,
                "limits": limits_payload,
                "volatility_pct": round(vol * 100, 2),
                "veto": not decision.approved,
                "override_allowed": False,
            },
            warnings=[
                "Risk approval is a controls check. It is not a recommendation and it is "
                "not authorisation to trade. The platform places no orders."
            ],
        )

    # --------------------------------------------------------------- helpers
    def _holdings(self, ctx: AgentContext) -> list[Holding]:
        """Holdings come from the journal store if the user imported a portfolio."""
        store = ctx.cache.get("journal_store")
        if store is None:
            return []
        try:
            rows = store.list_holdings()
        except Exception:  # noqa: BLE001
            return []
        out: list[Holding] = []
        for row in rows:
            try:
                price = float(ctx.registry.quote(row["symbol"]).value.last_price)
            except Exception:  # noqa: BLE001
                price = float(row["avg_price"])
            out.append(
                Holding(
                    symbol=row["symbol"],
                    quantity=float(row["quantity"]),
                    avg_price=float(row["avg_price"]),
                    last_price=price,
                    sector=row.get("sector") or "Unknown",
                )
            )
        return out


def concentration_note(holdings: list[Holding]) -> dict[str, Any]:
    return concentration([h.value for h in holdings])
