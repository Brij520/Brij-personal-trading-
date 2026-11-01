"""Agent contract shared by all fourteen agents.

Every agent declares:

* ``name``, ``responsibility``, ``version``
* an **input schema** (:class:`AgentInput` + the context fields it reads)
* an **output schema** (:class:`AgentFinding`)
* validation rules on its own output (see :meth:`BaseAgent.validate`)
* failure handling (it raises :class:`AgentError`, never returns a fake result)
* logging with the run id

Agents do not talk to brokers, do not place orders and cannot bypass the risk
agent. An agent may only *describe* and *score*; the committee decides.
"""

from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.logging import get_logger
from backend.core.provenance import Freshness, Verification, utcnow

log = get_logger("agents")

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
Stance = Literal["BULLISH", "NEUTRAL", "BEARISH", "INSUFFICIENT_DATA"]


class Evidence(BaseModel):
    """One auditable statement supporting a finding."""

    model_config = ConfigDict(extra="forbid")

    claim: str
    value: float | None = None
    unit: str | None = None
    source: str
    source_url: str | None = None
    as_of: str | None = None
    freshness: Freshness = Freshness.UNKNOWN
    verification: Verification = Verification.UNVERIFIED
    is_synthetic: bool = False

    def label(self) -> str:
        return f"{self.claim} [{self.source}]"


class AgentFinding(BaseModel):
    """The universal agent output."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    symbol: str | None = None
    headline: str
    stance: Stance = "INSUFFICIENT_DATA"
    #: -100 (strongly negative) .. +100 (strongly positive)
    score: float = 0.0
    #: 0..1, capped by the underlying data quality
    confidence: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    #: Things the agent explicitly could not check.
    limitations: list[str] = Field(default_factory=list)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    generated_by: str = "deterministic-rule-engine"
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    generated_at: datetime = Field(default_factory=utcnow)
    duration_ms: float = 0.0
    agent_version: str = "0.1.0"

    def model_post_init(self, __context: Any) -> None:
        self.score = float(max(-100.0, min(100.0, self.score)))
        self.confidence = float(max(0.0, min(1.0, self.confidence)))

    def summary(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "symbol": self.symbol,
            "headline": self.headline,
            "stance": self.stance,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 3),
            "evidence_count": len(self.evidence),
            "risks": self.risks,
            "limitations": self.limitations,
            "data_quality": self.data_quality,
            "metrics": self.metrics,
            "generated_by": self.generated_by,
            "agent_version": self.agent_version,
        }


class AgentInput(BaseModel):
    """Declared inputs, so a run can be reproduced from the payload alone."""

    model_config = ConfigDict(extra="allow")

    symbol: str | None = None
    as_of: datetime = Field(default_factory=utcnow)
    data_mode: str = "demo"
    notes: list[str] = Field(default_factory=list)


class AgentError(RuntimeError):
    """Raised when an agent cannot produce a trustworthy finding."""

    def __init__(self, agent: str, message: str) -> None:
        super().__init__(f"{agent}: {message}")
        self.agent = agent
        self.message = message


@dataclass
class AgentContext:
    """Everything an agent may read. Assembled once per research run."""

    registry: Any
    settings: Any
    symbol: str | None = None
    lookback: int = 750
    #: Cached artefacts filled by the orchestrator so agents share one fetch.
    cache: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, factory) -> Any:
        if key not in self.cache:
            self.cache[key] = factory()
        return self.cache[key]


class BaseAgent(abc.ABC):
    name: str = "base"
    responsibility: str = ""
    version: str = "0.1.0"
    #: Data this agent needs. Used by the orchestrator for pre-flight checks.
    requires: tuple[str, ...] = ()

    @abc.abstractmethod
    def run(self, ctx: AgentContext) -> AgentFinding:  # pragma: no cover - abstract
        ...

    # --------------------------------------------------------------- helpers
    def _quality_cap(self, quality_score: float) -> float:
        """Confidence can never exceed the quality of the data behind it."""
        return max(0.05, min(1.0, quality_score / 100.0))

    def validate(self, finding: AgentFinding) -> AgentFinding:
        """Output validation applied to every finding."""
        if not finding.headline.strip():
            raise AgentError(self.name, "empty headline")
        if not -100 <= finding.score <= 100:
            raise AgentError(self.name, f"score out of range: {finding.score}")
        if finding.stance != "INSUFFICIENT_DATA" and not finding.evidence:
            raise AgentError(
                self.name,
                "a directional stance requires at least one piece of evidence",
            )
        return finding

    def safe_run(self, ctx: AgentContext) -> AgentFinding:
        """Run with logging, timing and uniform failure handling."""
        start = time.perf_counter()
        try:
            finding = self.run(ctx)
            finding = self.validate(finding)
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("agent %s failed", self.name)
            raise AgentError(self.name, f"unexpected failure: {exc}") from exc
        finding.agent = self.name
        finding.agent_version = self.version
        finding.duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            "agent complete",
            extra={
                "agent": self.name,
                "symbol": finding.symbol,
                "duration_ms": finding.duration_ms,
                "status": finding.stance,
            },
        )
        return finding
