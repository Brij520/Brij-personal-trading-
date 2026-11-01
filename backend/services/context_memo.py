"""Memo of agent findings produced during a single research run.

Agents that need earlier results (the bear needs the bull's pillars, the
committee needs everything) read from here. Keeping this in the run context
means no global state and no cross-request leakage.
"""

from __future__ import annotations

from backend.agents.base import AgentContext, AgentFinding

KEY = "findings"


def record_finding(ctx: AgentContext, finding: AgentFinding) -> None:
    findings = ctx.cache.setdefault(KEY, {})
    findings[finding.agent] = finding


def get_findings(ctx: AgentContext) -> dict[str, AgentFinding]:
    return ctx.cache.setdefault(KEY, {})


def get_finding(ctx: AgentContext, agent: str) -> AgentFinding | None:
    return get_findings(ctx).get(agent)
