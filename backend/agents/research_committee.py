"""AGENT 14 — Final Research Committee.

Aggregates every earlier finding into one classification and one thesis.

Deliberate design choices:

* **Agreement is not evidence.** The committee does not simply average scores.
  It looks for *independent* corroboration: which findings rest on primary
  financial data vs. which are interpretations of the same price series.
* **Risk has a veto.** A risk rejection forces ``NO TRADE`` regardless of how
  attractive the rest of the case is.
* **Data quality caps the classification.** With synthetic or thin data the
  best possible outcome is ``WATCHLIST``.
* **Insufficient data is a valid answer** and must be used when it applies.

Classifications: STRONG RESEARCH CANDIDATE, RESEARCH CANDIDATE, WATCHLIST,
AVOID, INSUFFICIENT DATA, NO TRADE.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.core.provenance import Freshness, Verification
from backend.services.context_memo import get_findings

CLASSIFICATIONS = (
    "STRONG RESEARCH CANDIDATE",
    "RESEARCH CANDIDATE",
    "WATCHLIST",
    "AVOID",
    "INSUFFICIENT DATA",
    "NO TRADE",
)

#: Weights per agent and whether its evidence is *independent* of price data.
WEIGHTS: dict[str, tuple[float, str]] = {
    "fundamental_research": (0.22, "fundamental"),
    "valuation": (0.18, "fundamental"),
    "forensic_accounting": (0.12, "fundamental"),
    "technical_analysis": (0.16, "price"),
    "swing_trading": (0.08, "price"),
    "news_sentiment": (0.08, "news"),
    "options": (0.06, "derivatives"),
    "market_intelligence": (0.10, "price"),
}


class ResearchCommitteeAgent(BaseAgent):
    name = "research_committee"
    responsibility = "Aggregate findings, verify sources and classify the research"
    requires = ("all_findings",)

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        findings = get_findings(ctx)
        is_syn = bundle.is_synthetic
        quality = bundle.data_quality

        present = {k: v for k, v in findings.items() if k in WEIGHTS}
        if "fundamental_research" not in present and "technical_analysis" not in present:
            return AgentFinding(
                agent=self.name,
                symbol=bundle.symbol,
                headline="Insufficient data across the committee to reach a classification",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=["Neither the fundamental nor the technical agent produced a finding."],
                data_quality=quality,
                metrics={"classification": "INSUFFICIENT DATA", "agents": []},
            )

        # -------------------------------------------------- weighted evidence
        contributions: list[dict[str, Any]] = []
        total_weight = 0.0
        weighted_score = 0.0
        for agent_name, (weight, evidence_type) in WEIGHTS.items():
            finding = present.get(agent_name)
            if finding is None:
                continue
            # Confidence scales the contribution: a low-confidence finding barely counts.
            effective = weight * finding.confidence
            weighted_score += finding.score * effective
            total_weight += effective
            contributions.append(
                {
                    "agent": agent_name,
                    "stance": finding.stance,
                    "score": round(finding.score, 1),
                    "confidence": round(finding.confidence, 3),
                    "weight": weight,
                    "effective_weight": round(effective, 3),
                    "evidence_type": evidence_type,
                    "headline": finding.headline,
                }
            )

        composite = weighted_score / total_weight if total_weight else 0.0
        corroboration = self._corroboration(present)

        risk = findings.get("risk_management")
        risk_veto = bool(risk and risk.metrics.get("veto"))
        forensic = findings.get("forensic_accounting")
        critical_flags = forensic.metrics.get("critical_count", 0) if forensic else 0
        valuation = findings.get("valuation")
        upside = valuation.metrics.get("upside_pct") if valuation else None

        # ------------------------------------------------------ classification
        classification, rationale = self._classify(
            composite=composite,
            corroboration=corroboration,
            quality_score=quality["score"],
            risk_veto=risk_veto,
            critical_flags=critical_flags,
            upside=upside,
            present=present,
            is_synthetic=is_syn,
        )

        stance_map = {
            "STRONG RESEARCH CANDIDATE": ("BULLISH", min(100.0, composite * 1.0 + 15)),
            "RESEARCH CANDIDATE": ("BULLISH", min(80.0, composite + 5)),
            "WATCHLIST": ("NEUTRAL", composite * 0.5),
            "AVOID": ("BEARISH", max(-100.0, composite - 15)),
            "NO TRADE": ("NEUTRAL", composite * 0.3),
            "INSUFFICIENT DATA": ("INSUFFICIENT_DATA", 0.0),
        }
        stance, score = stance_map[classification]

        # ---------------------------------------------------------- the thesis
        bull = findings.get("bull_research")
        bear = findings.get("bear_research")
        thesis = self._thesis(bundle, classification, present, composite, corroboration)
        invalidation = (
            bull.metrics.get("thesis_invalidation", []) if bull else []
        ) or ["No explicit thesis was built, so there is nothing to invalidate."]

        evidence = [
            Evidence(
                claim=(
                    f"Committee composite score {composite:+.1f} from "
                    f"{len(present)} agent finding(s); independent corroboration {corroboration['groups']}"
                ),
                value=composite,
                source="research committee aggregation",
                as_of=str(bundle.series.meta.period_end),
                freshness=Freshness.SYNTHETIC if is_syn else bundle.series.meta.freshness,
                verification=Verification.UNVERIFIED_SYNTHETIC
                if is_syn
                else Verification.CROSS_CHECKED,
                is_synthetic=is_syn,
            )
        ]
        for agent_name in ("fundamental_research", "technical_analysis"):
            f = present.get(agent_name)
            if f and f.evidence:
                evidence.append(f.evidence[0])

        data_limitations = list(quality.get("notes", []))
        data_limitations.extend(
            [
                "Committee agreement is not independent evidence: several agents read "
                "the same price series.",
                "No primary-source verification (annual report, filing text, transcript) "
                "was performed in this run.",
            ]
        )
        if is_syn:
            data_limitations.append(
                "All underlying data is synthetic. The classification demonstrates the "
                "method; it says nothing about the real company."
            )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=f"{classification}: {rationale}",
            stance=stance,  # type: ignore[arg-type]
            score=float(np.clip(score, -100, 100)),
            confidence=min(0.85, self._quality_cap(quality["score"]) * (0.5 + 0.5 * corroboration["ratio"])),
            evidence=evidence,
            risks=(bear.risks if bear else [])
            + (
                list(risk.metrics.get("decision", {}).get("reasons", []))
                if risk_veto and risk
                else []
            ),
            limitations=data_limitations,
            data_quality=quality,
            metrics={
                "classification": classification,
                "rationale": rationale,
                "composite_score": round(composite, 2),
                "total_effective_weight": round(total_weight, 3),
                "corroboration": corroboration,
                "contributions": contributions,
                "risk_veto": risk_veto,
                "critical_forensic_flags": critical_flags,
                "valuation_upside_pct": upside,
                "thesis": thesis,
                "bull_case": bull.metrics.get("narrative") if bull else None,
                "bear_case": bear.metrics.get("narrative") if bear else None,
                "bull_concessions": bear.metrics.get("concessions") if bear else [],
                "thesis_invalidation": invalidation,
                "allowed_classifications": list(CLASSIFICATIONS),
                "agreement_warning": (
                    "Agent agreement is not independent evidence. Independent "
                    "corroboration is measured by evidence type below."
                ),
            },
            warnings=[
                "This is a research classification, not investment advice, and not an "
                "instruction to trade. No order is placed by this platform."
            ],
        )

    # ---------------------------------------------------------------- helpers
    def _corroboration(self, present: dict[str, AgentFinding]) -> dict[str, Any]:
        """Count distinct evidence *types* that agree on direction."""
        types: dict[str, float] = {}
        for agent_name, finding in present.items():
            evidence_type = WEIGHTS.get(agent_name, (0, "other"))[1]
            if finding.stance in {"BULLISH", "BEARISH"}:
                types.setdefault(evidence_type, 0.0)
                types[evidence_type] += finding.score * finding.confidence
        positive = [k for k, v in types.items() if v > 0]
        negative = [k for k, v in types.items() if v < 0]
        majority = max(len(positive), len(negative))
        return {
            "groups": f"{len(positive)} bullish / {len(negative)} bearish evidence groups",
            "bullish_groups": positive,
            "bearish_groups": negative,
            "ratio": majority / 4.0 if types else 0.0,
            "distinct_types": len(types),
        }

    def _classify(
        self,
        *,
        composite: float,
        corroboration: dict[str, Any],
        quality_score: int,
        risk_veto: bool,
        critical_flags: int,
        upside: float | None,
        present: dict[str, AgentFinding],
        is_synthetic: bool,
    ) -> tuple[str, str]:
        if len(present) < 2:
            return "INSUFFICIENT DATA", "fewer than two agents produced a usable finding"
        if quality_score < 40:
            return "INSUFFICIENT DATA", (
                f"data quality score {quality_score}/100 is too low to classify the company"
            )
        if risk_veto:
            return "NO TRADE", (
                "the risk agent rejected the reference plan; its veto cannot be overridden"
            )

        bullish_groups = len(corroboration.get("bullish_groups", []))
        bearish_groups = len(corroboration.get("bearish_groups", []))
        # Synthetic data can never produce a "strong" candidate: the evidence is
        # generated, not observed.
        ceiling = "WATCHLIST" if is_synthetic else "STRONG RESEARCH CANDIDATE"

        if critical_flags >= 1:
            return "AVOID", (
                f"{critical_flags} high-severity forensic flag(s) make the accounting "
                "unreliable regardless of the operating metrics"
            )
        if composite <= -30 and bearish_groups >= 2:
            return "AVOID", "combined evidence is clearly negative across independent groups"
        if composite >= 45 and bullish_groups >= 3 and (upside is None or upside > 0):
            if ceiling == "WATCHLIST":
                return "WATCHLIST", (
                    "the evidence is strong, but it rests on synthetic demonstration data, "
                    "which caps the classification at watchlist"
                )
            return "STRONG RESEARCH CANDIDATE", (
                "fundamentals, valuation and price evidence all point the same way"
            )
        if composite >= 22 and bullish_groups >= 2 and (upside is None or upside > -20):
            return ("RESEARCH CANDIDATE" if ceiling != "WATCHLIST" else "WATCHLIST"), (
                "positive evidence from more than one independent group, with caveats"
            )
        if composite <= -12 or bearish_groups > bullish_groups:
            return "WATCHLIST", "the case is mixed with a negative tilt; needs another look"
        return "WATCHLIST", "evidence is mixed and does not justify a research candidate"

    def _thesis(
        self,
        bundle,
        classification: str,
        present: dict[str, AgentFinding],
        composite: float,
        corroboration: dict[str, Any],
    ) -> dict[str, Any]:
        fund = present.get("fundamental_research")
        tech = present.get("technical_analysis")
        val = present.get("valuation")
        return {
            "symbol": bundle.symbol,
            "company": bundle.fundamentals.company_name,
            "sector": bundle.fundamentals.sector,
            "classification": classification,
            "one_line": (
                f"{bundle.fundamentals.company_name} ({bundle.fundamentals.sector}) — "
                f"{classification.lower()}. Composite {composite:+.0f}/100 with "
                f"{corroboration['groups']}."
            ),
            "fundamental_view": fund.headline if fund else "not assessed",
            "technical_view": tech.headline if tech else "not assessed",
            "valuation_view": val.headline if val else "not assessed",
            "what_would_change_our_mind": [
                "Two consecutive quarters showing the opposite revenue trend.",
                "A forensic flag appearing or clearing (auditor, pledge, related party).",
                "Price closing decisively through the level named in the technical finding.",
                "Valuation moving more than 20% relative to the same assumptions.",
            ],
        }
