"""AGENT 02 — Fundamental Research.

Turns the reported statements in the bundle into a quality assessment with
explicit strengths, concerns and gaps. Delegates the arithmetic to
``backend.analytics.fundamental`` so the numbers are computed in exactly one
place.
"""

from __future__ import annotations

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.core.provenance import Freshness, Verification


class FundamentalResearchAgent(BaseAgent):
    name = "fundamental_research"
    responsibility = "Business quality and financial risk from reported statements"
    requires = ("fundamentals", "statements")

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        a = bundle.analysis
        f = bundle.fundamentals
        latest = a.latest
        is_syn = bundle.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else Freshness.EOD
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.VERIFIED_PRIMARY
        )

        def ev(claim: str, value: float | None, unit: str | None = None) -> Evidence:
            return Evidence(
                claim=claim,
                value=None if value is None else round(float(value), 2),
                unit=unit,
                source=f.provenance.source,
                as_of=f.provenance.reporting_period,
                freshness=freshness,
                verification=verification,
                is_synthetic=is_syn,
            )

        evidence: list[Evidence] = [
            ev(f"Revenue INR {latest.revenue:,.0f} crore in {latest.fiscal_year}",
               latest.revenue, "crore"),
            ev(f"EBITDA margin {latest.ebitda_margin * 100:.1f}%" if latest.ebitda_margin else
               "EBITDA margin unavailable", (latest.ebitda_margin or 0) * 100, "%"),
            ev(f"Net margin {latest.net_margin * 100:.1f}%" if latest.net_margin else
               "Net margin unavailable", (latest.net_margin or 0) * 100, "%"),
            ev(f"ROE {latest.roe * 100:.1f}%" if latest.roe else "ROE unavailable",
               (latest.roe or 0) * 100, "%"),
            ev(f"CFO/PAT {latest.cfo_to_pat:.2f}" if latest.cfo_to_pat else "CFO/PAT unavailable",
               latest.cfo_to_pat or 0),
        ]
        if a.revenue_cagr_3y is not None:
            evidence.append(ev(f"3-year revenue CAGR {a.revenue_cagr_3y * 100:.1f}%",
                               a.revenue_cagr_3y * 100, "%"))
        if not a.is_financial and latest.roce is not None:
            evidence.append(ev(f"ROCE {latest.roce * 100:.1f}%", latest.roce * 100, "%"))

        # Map the quality score (0-100, 50 neutral) onto an agent score.
        score = float(np.clip((a.quality_score - 50) * 2.0, -100, 100))
        stance = "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL"

        limitations = list(a.insufficient)
        limitations += [
            "Only reported annual statements are used. Segment results, order books, "
            "management guidance and conference-call commentary are not ingested.",
            "Quarterly seasonality is not modelled beyond the reported quarters.",
        ]
        if a.is_financial:
            limitations.append(
                "For lenders, asset quality (GNPA/NNPA), NIM, credit cost and provision "
                "coverage are the primary drivers and are not in this dataset."
            )
        if is_syn:
            limitations.append("The underlying statements are synthetic demonstration data.")

        headline = (
            f"{f.company_name}: {a.quality_band.lower()} fundamentals "
            f"(score {a.quality_score}/100, ROE "
            f"{(latest.roe or 0) * 100:.1f}%, revenue CAGR "
            f"{(a.revenue_cagr_3y or 0) * 100:.1f}%)"
        )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=headline,
            stance=stance,
            score=score,
            confidence=self._quality_cap(bundle.data_quality["score"]),
            evidence=evidence,
            risks=a.concerns,
            limitations=limitations,
            data_quality=bundle.data_quality,
            metrics={
                "quality_score": a.quality_score,
                "quality_band": a.quality_band,
                "is_financial": a.is_financial,
                "ratios_history": [r.as_dict() for r in a.ratios],
                "revenue_cagr_3y_pct": None if a.revenue_cagr_3y is None else round(a.revenue_cagr_3y * 100, 2),
                "revenue_cagr_5y_pct": None if a.revenue_cagr_5y is None else round(a.revenue_cagr_5y * 100, 2),
                "pat_cagr_3y_pct": None if a.pat_cagr_3y is None else round(a.pat_cagr_3y * 100, 2),
                "margin_trend": a.margin_trend,
                "leverage_trend": a.leverage_trend,
                "cash_quality": a.cash_quality,
                "strengths": a.strengths,
                "concerns": a.concerns,
                "promoter_holding_pct": a.promoter_holding_pct,
                "promoter_pledge_pct": a.promoter_pledge_pct,
                "institutional_pct": a.institutional_pct,
                "quarterly": [
                    {
                        "period": q.period,
                        "revenue": q.revenue,
                        "ebitda": q.ebitda,
                        "pat": q.pat,
                        "eps": q.eps,
                    }
                    for q in f.quarterly
                ],
            },
        )
