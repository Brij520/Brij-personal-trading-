"""Multi-agent research orchestration.

Runs the agent pipeline in dependency order, records findings, and produces a
single report object. Failure of one agent does not abort the run: the failure is
recorded and the committee sees one fewer finding (which itself lowers
confidence). Only a failure to build the underlying research bundle aborts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.agents.base import AgentContext, AgentError, AgentFinding, BaseAgent
from backend.agents.debate import BearResearcherAgent, BullResearcherAgent
from backend.agents.forensic_accounting import ForensicAccountingAgent
from backend.agents.fundamental_research import FundamentalResearchAgent
from backend.agents.intraday import IntradayResearchAgent
from backend.agents.market_intelligence import MarketIntelligenceAgent
from backend.agents.news_sentiment import NewsSentimentAgent
from backend.agents.options_intelligence import OptionsIntelligenceAgent
from backend.agents.portfolio_manager import PortfolioManagerAgent
from backend.agents.research_committee import ResearchCommitteeAgent
from backend.agents.risk_management import RiskManagementAgent
from backend.agents.swing_trading import SwingTradingAgent
from backend.agents.technical_analysis import TechnicalAnalysisAgent
from backend.agents.valuation import ValuationAgent
from backend.core.config import Settings, get_settings
from backend.core.logging import get_logger, new_request_id
from backend.core.provenance import utcnow
from backend.data.registry import DataRegistry, get_registry
from backend.services.context_memo import record_finding
from backend.services.research_context import ResearchBundle, build_bundle

log = get_logger("orchestrator")

#: Execution order matters: the bear needs the bull, the committee needs all.
PIPELINE: tuple[type[BaseAgent], ...] = (
    MarketIntelligenceAgent,
    FundamentalResearchAgent,
    ValuationAgent,
    TechnicalAnalysisAgent,
    ForensicAccountingAgent,
    NewsSentimentAgent,
    OptionsIntelligenceAgent,
    SwingTradingAgent,
    IntradayResearchAgent,
    BullResearcherAgent,
    BearResearcherAgent,
    RiskManagementAgent,
    PortfolioManagerAgent,
    ResearchCommitteeAgent,
)

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {cls.name: cls for cls in PIPELINE}

DISCLAIMER = (
    "BRIJ TRADING INTELLIGENCE produces research artefacts for personal study. "
    "Nothing here is investment advice, a recommendation, or an instruction to "
    "trade. No order is placed, modified or cancelled by this platform. Data may "
    "be delayed, incomplete or (in demo mode) synthetic."
)


@dataclass
class ResearchReport:
    symbol: str
    generated_at: datetime
    run_id: str
    duration_ms: float
    findings: dict[str, AgentFinding]
    failures: list[dict[str, str]]
    bundle_summary: dict[str, Any]
    safety: dict[str, Any]
    data_mode: str
    disclaimer: str = DISCLAIMER

    @property
    def committee(self) -> AgentFinding | None:
        return self.findings.get("research_committee")

    @property
    def classification(self) -> str:
        committee = self.committee
        if committee is None:
            return "INSUFFICIENT DATA"
        return str(committee.metrics.get("classification", "INSUFFICIENT DATA"))

    def _finding(self, name: str) -> dict[str, Any] | None:
        finding = self.findings.get(name)
        return finding.model_dump(mode="json") if finding is not None else None

    @property
    def limitations(self) -> list[str]:
        """Every distinct caveat any agent raised, de-duplicated and ordered.

        A research run is only honest if its caveats travel with its
        conclusions, so they are promoted to the top level of the payload.
        """
        seen: dict[str, None] = {}
        for finding in self.findings.values():
            for item in finding.limitations:
                seen.setdefault(item, None)
        return list(seen)

    def to_dict(self, include_metrics: bool = True) -> dict[str, Any]:
        committee = self.committee
        risk = self.findings.get("risk_management")
        return {
            "symbol": self.symbol,
            "generated_at": self.generated_at.isoformat(),
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "classification": self.classification,
            "confidence": round(committee.confidence, 4) if committee else 0.0,
            "summary": committee.headline if committee else "No committee finding was produced.",
            "data_mode": self.data_mode,
            "bundle": self.bundle_summary,
            "data_quality": self.bundle_summary.get("data_quality", {}),
            "committee": (
                {
                    "classification": committee.metrics.get("classification"),
                    "rationale": committee.metrics.get("rationale"),
                    "composite_score": committee.metrics.get("composite_score"),
                    "corroboration": committee.metrics.get("corroboration"),
                    "contributions": committee.metrics.get("contributions"),
                    "confidence": committee.confidence,
                    "stance": committee.stance,
                    "headline": committee.headline,
                    "limitations": committee.limitations,
                }
                if committee
                else None
            ),
            "risk": (
                {
                    "decision": (risk.metrics or {}).get("decision"),
                    "headline": risk.headline,
                    "stance": risk.stance,
                    "limitations": risk.limitations,
                }
                if risk
                else None
            ),
            "debate": {
                "bull": {
                    "headline": self.findings["bull_research"].headline,
                    "stance": self.findings["bull_research"].stance,
                    "score": self.findings["bull_research"].score,
                    "narrative": (self.findings["bull_research"].metrics or {}).get("narrative"),
                    "pillars": (self.findings["bull_research"].metrics or {}).get("pillars"),
                }
                if "bull_research" in self.findings
                else None,
                "bear": {
                    "headline": self.findings["bear_research"].headline,
                    "stance": self.findings["bear_research"].stance,
                    "score": self.findings["bear_research"].score,
                    "narrative": (self.findings["bear_research"].metrics or {}).get("narrative"),
                    "attacks": (self.findings["bear_research"].metrics or {}).get("attacks"),
                }
                if "bear_research" in self.findings
                else None,
            },
            "limitations": self.limitations,
            "safety": self.safety,
            "findings": {
                name: (f.model_dump(mode="json") if include_metrics else f.summary())
                for name, f in self.findings.items()
            },
            "failures": self.failures,
            "disclaimer": self.disclaimer,
        }


def run_research(
    symbol: str,
    *,
    registry: DataRegistry | None = None,
    settings: Settings | None = None,
    lookback: int = 750,
    only: list[str] | None = None,
    journal_store: Any = None,
) -> ResearchReport:
    """Run the agent pipeline for one symbol and return the full report."""
    settings = settings or get_settings()
    registry = registry or get_registry()
    run_id = new_request_id()
    started = time.perf_counter()
    started_at = utcnow()

    bundle: ResearchBundle = build_bundle(registry, symbol, lookback=lookback)
    ctx = AgentContext(
        registry=registry,
        settings=settings,
        symbol=bundle.symbol,
        lookback=lookback,
    )
    ctx.cache["bundle"] = bundle
    ctx.cache[f"bundle:{bundle.symbol}"] = bundle
    if journal_store is not None:
        ctx.cache["journal_store"] = journal_store

    findings: dict[str, AgentFinding] = {}
    failures: list[dict[str, str]] = []
    for factory in PIPELINE:
        agent = factory()
        if only and agent.name not in only:
            continue
        # Agents that need a portfolio still run; they report "none imported".
        try:
            finding = agent.safe_run(ctx)
        except AgentError as exc:
            failures.append({"agent": agent.name, "error": exc.message})
            log.warning("agent %s failed: %s", agent.name, exc.message)
            continue
        findings[agent.name] = finding
        record_finding(ctx, finding)

    return ResearchReport(
        symbol=bundle.symbol,
        generated_at=started_at,
        run_id=run_id,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        findings=findings,
        failures=failures,
        bundle_summary={
            "company": bundle.fundamentals.company_name,
            "sector": bundle.fundamentals.sector,
            "industry": bundle.fundamentals.industry,
            "price": round(bundle.price, 2),
            "bars": len(bundle.series),
            "first_bar": str(bundle.series.frame.index[0].date()),
            "last_bar": str(bundle.series.frame.index[-1].date()),
            "data_quality": bundle.data_quality,
            "is_synthetic": bundle.is_synthetic,
            "warnings": bundle.warnings,
            "provenance": bundle.series.meta.model_dump(mode="json"),
        },
        safety=settings.safety_snapshot(),
        data_mode=settings.data_mode,
    )


def run_single_agent(
    agent_name: str,
    symbol: str,
    *,
    registry: DataRegistry | None = None,
    settings: Settings | None = None,
) -> AgentFinding:
    if agent_name not in AGENT_REGISTRY:
        raise KeyError(f"unknown agent {agent_name!r}; available: {sorted(AGENT_REGISTRY)}")
    settings = settings or get_settings()
    registry = registry or get_registry()
    bundle = build_bundle(registry, symbol)
    ctx = AgentContext(registry=registry, settings=settings, symbol=bundle.symbol)
    ctx.cache["bundle"] = bundle
    ctx.cache[f"bundle:{bundle.symbol}"] = bundle
    return AGENT_REGISTRY[agent_name]().safe_run(ctx)


def describe_agents() -> list[dict[str, Any]]:
    """Catalogue for the API and docs: responsibilities and declared inputs."""
    out = []
    for cls in PIPELINE:
        out.append(
            {
                "name": cls.name,
                "responsibility": cls.responsibility,
                "requires": list(cls.requires),
                "version": cls.version,
                "output_schema": "AgentFinding",
            }
        )
    return out
