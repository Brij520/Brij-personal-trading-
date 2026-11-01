"""AGENT 08 — News and Sentiment.

Hard rule: **facts and opinions are never mixed into one number.** The agent
reports verified-style factual items (filings/announcements) separately from
commentary, and computes sentiment only over the factual bucket. If no factual
item exists, the stance is INSUFFICIENT_DATA regardless of how positive the
commentary looks.

Fact/opinion classification uses the ``kind`` field supplied by the provider.
In demo mode the items are synthetic and labelled accordingly.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.core.provenance import Freshness, Verification, utcnow


class NewsSentimentAgent(BaseAgent):
    name = "news_sentiment"
    responsibility = "News monitoring with strict fact/opinion separation"
    requires = ("news",)

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        try:
            res = ctx.registry.news(bundle.symbol, limit=20)
            items = res.value
        except Exception as exc:  # noqa: BLE001
            return AgentFinding(
                agent=self.name,
                symbol=bundle.symbol,
                headline="News feed unavailable",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=[f"No news provider returned data: {exc}"],
                data_quality=bundle.data_quality,
                metrics={"facts": [], "opinions": []},
            )

        now = utcnow()
        facts = [i for i in items if i.kind == "FACT"]
        opinions = [i for i in items if i.kind != "FACT"]
        recent_facts = [i for i in facts if (now - i.published_at) <= timedelta(days=14)]
        is_syn = any(i.provenance.is_synthetic for i in items)

        def render(item) -> dict[str, object]:
            return {
                "headline": item.headline,
                "published_at": item.published_at.isoformat(),
                "category": item.category,
                "kind": item.kind,
                "sentiment": item.sentiment,
                "source": item.source,
                "synthetic": item.provenance.is_synthetic,
                "summary": item.summary,
            }

        evidence: list[Evidence] = []
        for item in recent_facts[:6]:
            evidence.append(
                Evidence(
                    claim=item.headline,
                    value=item.sentiment,
                    source=item.source,
                    source_url=item.url,
                    as_of=item.published_at.date().isoformat(),
                    freshness=Freshness.SYNTHETIC if is_syn else Freshness.DELAYED,
                    verification=Verification.UNVERIFIED_SYNTHETIC
                    if is_syn
                    else Verification.UNVERIFIED,
                    is_synthetic=is_syn,
                )
            )

        if not recent_facts:
            return AgentFinding(
                agent=self.name,
                symbol=bundle.symbol,
                headline=(
                    f"No factual news in the last 14 days "
                    f"({len(opinions)} opinion items ignored for scoring)"
                ),
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.1,
                evidence=evidence,
                limitations=[
                    "Sentiment is deliberately not scored without factual items: "
                    "opinion volume is not evidence."
                ],
                data_quality=bundle.data_quality,
                metrics={
                    "facts": [render(i) for i in facts],
                    "opinions": [render(i) for i in opinions],
                    "fact_count_14d": 0,
                },
            )

        fact_sentiment = float(np.mean([i.sentiment for i in recent_facts]))
        opinion_sentiment = (
            float(np.mean([i.sentiment for i in opinions])) if opinions else 0.0
        )
        divergence = fact_sentiment - opinion_sentiment
        categories = Counter(i.category for i in recent_facts)

        score = float(np.clip(fact_sentiment * 60, -60, 60))
        # Recency weight: items within 3 days count fully, older decay.
        recent_weight = sum(
            1.0 if (now - i.published_at) <= timedelta(days=3) else 0.5 for i in recent_facts
        ) / max(len(recent_facts), 1)
        confidence = self._quality_cap(bundle.data_quality["score"]) * (
            0.35 + 0.35 * min(len(recent_facts), 4) / 4 + 0.2 * recent_weight
        )
        stance = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "NEUTRAL"

        warnings: list[str] = []
        if abs(divergence) > 0.4:
            warnings.append(
                f"Commentary sentiment ({opinion_sentiment:+.2f}) diverges from factual "
                f"news sentiment ({fact_sentiment:+.2f}). The gap is itself information."
            )
        if is_syn:
            warnings.append("All news items are synthetic demonstration text.")

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=(
                f"{len(recent_facts)} factual item(s) in 14 days, net sentiment "
                f"{fact_sentiment:+.2f}; {len(opinions)} opinion item(s) excluded from scoring"
            ),
            stance=stance,
            score=score,
            confidence=round(confidence, 3),
            evidence=evidence,
            risks=warnings,
            limitations=[
                "No exchange-filing full text, no transcript analysis, no entity "
                "resolution across sources — classification relies on the provider's "
                "FACT/OPINION label.",
                "Sentiment is a keyword-scored provider field, not a trained model.",
                "Absence of news in this feed is not evidence that nothing happened.",
            ],
            data_quality=bundle.data_quality,
            metrics={
                "facts": [render(i) for i in facts],
                "opinions": [render(i) for i in opinions],
                "fact_sentiment": round(fact_sentiment, 3),
                "opinion_sentiment": round(opinion_sentiment, 3),
                "divergence": round(divergence, 3),
                "fact_count_14d": len(recent_facts),
                "categories": dict(categories),
            },
            warnings=warnings,
        )
