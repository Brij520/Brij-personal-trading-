"""AGENTS 11 & 12 — Bull Researcher and Bear Researcher.

The two agents are deliberately asymmetric and adversarial.

* The **bull** must build the strongest *evidence-based* case, but it is capped:
  it may not cite a fact absent from the bundle, and its score is limited by the
  quality of the evidence it uses.
* The **bear** attacks the bull's specific claims, item by item, and must also
  state which parts of the bull case it *cannot* refute.

Agreement between them is not evidence. The committee is told, explicitly, not
to treat a debate consensus as verification.

If an LLM provider is configured it writes the prose; otherwise a deterministic
narrative builder produces the text from the same metrics. The numeric scores
never come from the LLM.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.core.llm import narrate
from backend.core.provenance import Freshness, Verification
from backend.services.context_memo import get_findings


class BullResearcherAgent(BaseAgent):
    name = "bull_research"
    responsibility = "Construct the strongest evidence-based bullish thesis"
    requires = ("fundamentals", "valuation", "technical", "news")

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        a = bundle.analysis
        latest = a.latest
        t = bundle.technical_frame.dropna(subset=["rsi14"]).iloc[-1]
        close = float(t["close"])
        ema200 = float(t["ema200"])
        f = bundle.fundamentals
        is_syn = bundle.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else Freshness.EOD
        verification = Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED

        pillars: list[dict[str, Any]] = []
        score = 0.0

        def pillar(name: str, points: float, claim: str, value: float | None = None) -> None:
            nonlocal score
            pillars.append({"pillar": name, "points": round(points, 1), "claim": claim})
            score += points

        if a.revenue_cagr_3y is not None and a.revenue_cagr_3y > 0.10:
            pillar(
                "Growth",
                min(20, a.revenue_cagr_3y * 100),
                f"Revenue compounded at {a.revenue_cagr_3y * 100:.1f}% over three years.",
                a.revenue_cagr_3y * 100,
            )
        if latest.roe is not None and latest.roe > 0.15:
            pillar("Returns", min(18, (latest.roe - 0.10) * 150),
                   f"ROE of {latest.roe * 100:.1f}% signals capital efficiency.", latest.roe * 100)
        if not a.is_financial and latest.roce is not None and latest.roce > 0.15:
            pillar("Moat", min(15, (latest.roce - 0.12) * 100),
                   f"ROCE of {latest.roce * 100:.1f}% above the cost of capital.", latest.roce * 100)
        if latest.cfo_to_pat is not None and latest.cfo_to_pat >= 1.0:
            pillar("Cash conversion", 10,
                   f"Cash flow covers profit at {latest.cfo_to_pat:.2f}x.", latest.cfo_to_pat)
        if latest.fcf > 0 and not a.is_financial:
            pillar("Self-funding", 8, f"Free cash flow of INR {latest.fcf:,.0f} crore.")
        if close > ema200:
            pillar("Trend", 10, f"Price is above the 200-DMA ({ema200:,.2f}).")
        elif close > ema200 * 0.92:
            pillar("Trend proximity", 4, "Price is consolidating near the 200-DMA.")
        if bundle.data_quality["score"] >= 70:
            pillar("Data quality", 3,
                   f"Data quality score {bundle.data_quality['score']}/100.")

        score = float(np.clip(score, 0, 100)) * 0.85  # never fully confident
        limitations = [
            "Only evidence present in the research bundle is used. Management guidance, "
            "order books, market share and competitive dynamics are absent.",
            "A thesis built from reported numbers cannot see what the numbers omit.",
        ]
        if is_syn:
            limitations.append("All inputs are synthetic demonstration data.")
        if a.insufficient:
            limitations.extend(a.insufficient)

        narrative_prompt = (
            "Metrics:\n" + "\n".join(f"{i+1}. {p['claim']}" for i, p in enumerate(pillars))
            + f"\nCompany: {f.company_name}, sector {f.sector}."
        )
        fallback = (
            f"The bull case rests on {len(pillars)} pillars: "
            + "; ".join(p["claim"].rstrip(".") for p in pillars[:3])
            + "."
            + (
                " The weakest link is that all of this is inferred from reported "
                "numbers rather than verified business developments."
                if pillars
                else " No pillar currently reaches a meaningful threshold."
            )
        )
        text = narrate(_llm(), narrative_prompt, fallback)

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=(
                f"Bull case: {len(pillars)} supporting pillars, conviction "
                f"{score:.0f}/100"
            ),
            stance="BULLISH" if score >= 35 else "NEUTRAL" if pillars else "INSUFFICIENT_DATA",
            score=score,
            confidence=self._quality_cap(bundle.data_quality["score"]) * 0.85,
            evidence=[
                Evidence(
                    claim=p["claim"],
                    value=p.get("value"),
                    source=f.provenance.source,
                    as_of=f.provenance.reporting_period,
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
                for p in pillars[:6]
            ]
            or [
                Evidence(
                    claim="No metric reached the threshold for a bullish pillar.",
                    source=f.provenance.source,
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            ],
            risks=[
                "Bull case ignores competitive response, regulation and execution risk.",
                "Growth extrapolation is the most common source of thesis failure.",
            ],
            limitations=limitations,
            data_quality=bundle.data_quality,
            metrics={
                "pillars": pillars,
                "narrative": text["text"],
                "generated_by": text["generated_by"],
                "thesis_invalidation": _invalidation(bundle),
            },
            generated_by=text["generated_by"],
        )


class BearResearcherAgent(BaseAgent):
    name = "bear_research"
    responsibility = "Challenge the bullish thesis with evidence"
    requires = ("fundamentals", "valuation", "technical", "forensics")

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        a = bundle.analysis
        latest = a.latest
        t = bundle.technical_frame.dropna(subset=["rsi14"]).iloc[-1]
        close = float(t["close"])
        ema200 = float(t["ema200"])
        f = bundle.fundamentals
        is_syn = bundle.is_synthetic
        prior = get_findings(ctx)
        bull = prior.get("bull_research")
        freshness = Freshness.SYNTHETIC if is_syn else Freshness.EOD
        verification = Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED

        attacks: list[dict[str, Any]] = []
        score = 0.0

        def attack(target: str, severity: float, claim: str) -> None:
            nonlocal score
            attacks.append({"challenges": target, "severity": round(severity, 1), "claim": claim})
            score += severity

        # Numbers-based attacks.
        if latest.debt_to_equity is not None and latest.debt_to_equity > 1.0 and not a.is_financial:
            attack("Balance sheet", 15,
                   f"Debt-to-equity of {latest.debt_to_equity:.2f} leaves little room if "
                   "rates rise or demand slows.")
        if latest.interest_coverage is not None and latest.interest_coverage < 3 and not a.is_financial:
            attack("Debt servicing", 12,
                   f"Interest coverage of {latest.interest_coverage:.1f}x is thin for a "
                   "cyclical business.")
        if latest.cfo_to_pat is not None and latest.cfo_to_pat < 0.8 and not a.is_financial:
            attack("Earnings quality", 15,
                   f"Profit is not converting to cash (CFO/PAT {latest.cfo_to_pat:.2f}).")
        if a.revenue_cagr_3y is not None and a.revenue_cagr_3y < 0.06:
            attack("Growth", 12,
                   f"Revenue CAGR of {a.revenue_cagr_3y * 100:.1f}% is below nominal GDP, so "
                   "market share is likely being lost.")
        if a.margin_trend == "deteriorating":
            attack("Margins", 12, "Operating margins are trending down across the series.")
        if f.promoter_pledge_pct > 5:
            attack("Governance", 15, f"Promoter pledge at {f.promoter_pledge_pct:.1f}% of holding.")
        if f.auditor_qualification:
            attack("Governance", 18, f"Auditor qualification: {f.auditor_qualification}")
        if latest.roe is not None and latest.roe < 0.10:
            attack("Returns", 12, f"ROE of {latest.roe * 100:.1f}% is below the cost of equity.")
        if close < ema200:
            attack("Price structure", 12,
                   f"Price is below the 200-DMA ({ema200:,.2f}); the trend is not supportive.")
        if a.is_financial:
            attack("Data gap", 8,
                   "Asset-quality metrics for this lender are not available; the bull "
                   "case cannot be verified on the variables that matter most.")

        forensic = prior.get("forensic_accounting")
        if forensic:
            critical = forensic.metrics.get("critical_count", 0) if forensic.metrics else 0
            if critical:
                attack("Accounting", 10 * critical,
                       f"{critical} high-severity accounting flags raised by the forensic agent.")

        valuation = prior.get("valuation")
        if valuation and valuation.stance == "BEARISH":
            attack("Valuation", 15,
                   f"The valuation agent concludes the opposite of the bull case: {valuation.headline}.")

        # What the bear cannot refute — stated explicitly.
        concessions: list[str] = []
        if a.revenue_cagr_3y and a.revenue_cagr_3y > 0.12:
            concessions.append(
                f"Revenue growth of {a.revenue_cagr_3y * 100:.1f}% is genuine in the reported data."
            )
        if latest.roe and latest.roe > 0.18:
            concessions.append(f"ROE of {latest.roe * 100:.1f}% is objectively strong.")
        if latest.cfo_to_pat and latest.cfo_to_pat >= 1.0 and not a.is_financial:
            concessions.append("Cash conversion is genuinely strong.")
        if not concessions:
            concessions.append("No part of the bull case survives challenge on the available data.")

        score = float(np.clip(score, 0, 100)) * 0.85
        targets = [p["claim"] for p in (bull.metrics.get("pillars", []) if bull else [])][:3]
        prompt = (
            "Bull claims to challenge:\n"
            + ("\n".join(f"- {t_}" for t_ in targets) if targets else "- none supplied")
            + "\nBear evidence:\n"
            + "\n".join(f"{i+1}. {x['claim']}" for i, x in enumerate(attacks))
        )
        fallback = (
            f"The bear case is strongest on {len(attacks)} points: "
            + "; ".join(x["claim"].rstrip(".") for x in attacks[:3])
            + ". "
            + (
                "Even so, one point must be conceded: "
                + concessions[0].rstrip(".")
                + "."
            )
        )
        text = narrate(_llm(), prompt, fallback)

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=(
                f"Bear case: {len(attacks)} challenges, "
                f"{len(concessions)} point(s) conceded, conviction {score:.0f}/100"
            ),
            stance="BEARISH" if score >= 35 else "NEUTRAL" if attacks else "INSUFFICIENT_DATA",
            score=score,
            confidence=self._quality_cap(bundle.data_quality["score"]) * 0.85,
            evidence=[
                Evidence(
                    claim=x["claim"],
                    value=x["severity"],
                    source="derived from reported statements and price data",
                    as_of=f.provenance.reporting_period,
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
                for x in attacks[:6]
            ]
            or [
                Evidence(
                    claim=(
                        "No bearish attack reached significance on the available data; "
                        "absence of evidence is not a clean bill of health."
                    ),
                    source="derived from reported statements",
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            ],
            risks=concessions,
            limitations=[
                "The bear agent sees only the same bundle as the bull agent; both may "
                "miss the same external risks.",
                "Attacks are threshold-based and cannot assess management intent.",
            ]
            + (["All inputs are synthetic demonstration data."] if is_syn else []),
            data_quality=bundle.data_quality,
            metrics={
                "attacks": attacks,
                "concessions": concessions,
                "challenged_claims": targets,
                "narrative": text["text"],
                "generated_by": text["generated_by"],
            },
            generated_by=text["generated_by"],
        )


def _llm():
    from backend.core.llm import build_llm

    return build_llm()


def _invalidation(bundle) -> list[str]:
    """Concrete conditions that would break the bullish thesis."""
    out = []
    latest = bundle.analysis.latest
    if latest.ebitda_margin:
        out.append(
            f"EBITDA margin falling below {latest.ebitda_margin * 100 * 0.8:.1f}% "
            "(a 20% compression) would break the earnings trajectory."
        )
    out.append("Two consecutive quarters of negative revenue growth.")
    out.append("Promoter selling or a pledge increase above 10% of holding.")
    out.append("Thesis is invalid if the valuation gap closes without earnings following through.")
    return out
