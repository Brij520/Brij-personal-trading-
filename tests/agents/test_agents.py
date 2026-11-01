"""Agent behaviour: schema validity, honest failure modes, committee logic."""

from __future__ import annotations

import pytest

from backend.agents.base import AgentContext, AgentFinding
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
from backend.services.context_memo import record_finding, get_findings
from backend.services.orchestrator import AGENT_REGISTRY


@pytest.fixture()
def ctx(registry, settings):
    context = AgentContext(registry=registry, settings=settings, symbol="RELIANCE")
    yield context
    context.cache.clear()


def run(agent, ctx):
    finding = agent.run(ctx)
    agent.validate(finding)
    return finding


def test_all_fourteen_agents_registered():
    assert len(AGENT_REGISTRY) == 14
    for name in (
        "market_intelligence", "fundamental_research", "valuation", "technical_analysis",
        "swing_trading", "intraday", "options", "news_sentiment", "forensic_accounting",
        "risk_management", "bull_research", "bear_research", "portfolio_manager",
        "research_committee",
    ):
        assert name in AGENT_REGISTRY


@pytest.mark.parametrize(
    "agent_cls",
    [FundamentalResearchAgent, ValuationAgent, TechnicalAnalysisAgent,
     ForensicAccountingAgent, NewsSentimentAgent, SwingTradingAgent],
)
def test_agents_emit_valid_findings(agent_cls, ctx):
    finding = run(agent_cls(), ctx)
    assert -100 <= finding.score <= 100
    assert 0 <= finding.confidence <= 1
    assert finding.headline
    if finding.stance != "INSUFFICIENT_DATA":
        assert finding.evidence, "directional findings must cite evidence"


def test_market_agent_declares_unavailable_inputs(ctx):
    finding = run(MarketIntelligenceAgent(), ctx)
    joined = " ".join(finding.limitations).lower()
    assert "vix" in joined
    assert "global" in joined
    assert any("fii" in x.lower() for x in finding.limitations)


def test_technical_confidence_is_capped_by_data_quality(ctx):
    from backend.agents.helpers import bundle_from

    bundle = bundle_from(ctx)
    finding = run(TechnicalAnalysisAgent(), ctx)
    # Confidence may never exceed the quality of the data behind it.
    assert finding.confidence <= bundle.data_quality["score"] / 100 + 1e-9


def test_valuation_never_claims_a_target_price(ctx):
    finding = run(ValuationAgent(), ctx)
    text = (finding.headline + " " + " ".join(finding.limitations)).lower()
    assert "target price" in text or "not a forecast" in text
    assert "recommend" not in finding.headline.lower()


def test_forensic_agent_is_negative_only(ctx):
    finding = run(ForensicAccountingAgent(), ctx)
    assert finding.score <= 0


def test_bank_valuation_uses_book_value_not_dcf(bank_bundle, registry, settings):
    context = AgentContext(registry=registry, settings=settings, symbol="HDFCBANK")
    context.cache["bundle"] = bank_bundle
    context.cache["bundle:HDFCBANK"] = bank_bundle
    finding = run(ValuationAgent(), context)
    assert "bank_valuation" in finding.metrics
    assert "dcf" not in finding.metrics
    assert any("book value" in x.lower() for x in finding.limitations)


def test_options_agent_refuses_missing_contract(registry, settings):
    context = AgentContext(registry=registry, settings=settings, symbol="POLYCAB")
    finding = run(OptionsIntelligenceAgent(), context)
    assert finding.metrics.get("fno_enabled") is not True
    assert "FNO_ENABLED" in " ".join(finding.limitations) or "no listed F&O" in finding.headline


def test_options_agent_marks_fno_disabled(ctx):
    finding = run(OptionsIntelligenceAgent(), ctx)
    assert finding.metrics["fno_enabled"] is False
    assert any("disabled" in w.lower() for w in finding.warnings)


def test_risk_agent_cannot_be_overridden(ctx):
    finding = run(RiskManagementAgent(), ctx)
    assert finding.metrics["override_allowed"] is False
    assert "veto" in finding.metrics


def test_news_agent_separates_facts_from_opinions(ctx):
    finding = run(NewsSentimentAgent(), ctx)
    assert "facts" in finding.metrics and "opinions" in finding.metrics
    assert finding.metrics["fact_sentiment"] is not None


def test_portfolio_agent_reports_missing_data(ctx):
    finding = run(PortfolioManagerAgent(), ctx)
    assert finding.stance == "INSUFFICIENT_DATA"
    assert any("import" in x.lower() for x in finding.limitations)


def test_intraday_agent_is_paper_only(ctx):
    finding = run(IntradayResearchAgent(), ctx)
    assert finding.metrics["paper_mode"] is True
    assert finding.metrics["execution"] == "disabled"


def test_bull_and_bear_are_adversarial(ctx):
    bull = run(BullResearcherAgent(), ctx)
    record_finding(ctx, bull)
    bear = run(BearResearcherAgent(), ctx)
    assert bull.stance in {"BULLISH", "NEUTRAL", "INSUFFICIENT_DATA"}
    assert bear.stance in {"BEARISH", "NEUTRAL", "INSUFFICIENT_DATA"}
    # The bear must either attack specific claims or concede none exist.
    assert bear.metrics["attacks"] or bear.metrics["concessions"]


def test_committee_requires_two_agents(registry, settings):
    context = AgentContext(registry=registry, settings=settings, symbol="RELIANCE")
    finding = run(ResearchCommitteeAgent(), context)
    assert finding.metrics["classification"] == "INSUFFICIENT DATA"


def test_committee_caps_synthetic_data(registry, settings):
    """Synthetic data must never yield STRONG RESEARCH CANDIDATE."""
    from backend.services.orchestrator import run_research

    report = run_research("RELIANCE", registry=registry, settings=settings, lookback=500)
    assert report.classification != "STRONG RESEARCH CANDIDATE"
    assert report.classification in {
        "RESEARCH CANDIDATE", "WATCHLIST", "AVOID", "INSUFFICIENT DATA", "NO TRADE"
    }


def test_committee_respects_risk_veto(registry, settings, ctx):
    from backend.agents.base import AgentFinding

    # Build a synthetic panel where risk vetoes and everything else is bullish.
    for name in ("fundamental_research", "technical_analysis", "valuation"):
        record_finding(ctx, AgentFinding(
            agent=name, symbol="RELIANCE", headline="bullish", stance="BULLISH",
            score=80, confidence=0.9,
            evidence=[{"claim": "x", "source": "test"}]))
    record_finding(ctx, AgentFinding(
        agent="risk_management", symbol="RELIANCE", headline="veto", stance="NEUTRAL",
        score=0, confidence=0.95, metrics={"veto": True}, evidence=[]))
    finding = run(ResearchCommitteeAgent(), ctx)
    assert finding.metrics["classification"] == "NO TRADE"
    assert finding.metrics["risk_veto"] is True


def test_agent_validation_rejects_empty_headline(ctx):
    agent = TechnicalAnalysisAgent()
    with pytest.raises(Exception):
        agent.validate(AgentFinding(agent="x", headline="   ", stance="NEUTRAL"))


def test_directional_finding_requires_evidence(ctx):
    agent = TechnicalAnalysisAgent()
    with pytest.raises(Exception):
        agent.validate(AgentFinding(agent="x", headline="ok", stance="BULLISH"))
