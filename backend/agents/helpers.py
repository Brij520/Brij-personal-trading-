"""Shared helpers for agents (bundle caching, evidence builders, formatting)."""

from __future__ import annotations

from typing import Any

from backend.agents.base import AgentContext
from backend.analytics.risk import RiskLimits
from backend.services.research_context import ResearchBundle, build_bundle


def bundle_from(ctx: AgentContext) -> ResearchBundle:
    """Get (and cache) the research bundle for the run's symbol."""
    if not ctx.symbol:
        raise ValueError("this agent requires a symbol")
    return ctx.get(
        f"bundle:{ctx.symbol}",
        lambda: build_bundle(ctx.registry, ctx.symbol, lookback=ctx.lookback),
    )


def risk_limits_from(ctx: AgentContext) -> RiskLimits:
    settings = ctx.settings
    return ctx.get(
        "risk_limits",
        lambda: RiskLimits(
            capital=float(getattr(settings, "capital", 20_000.0) or 20_000.0),
            max_position_risk_pct=settings.max_position_risk_pct,
            max_portfolio_heat_pct=settings.max_portfolio_heat_pct,
            max_single_stock_pct=settings.max_single_stock_pct,
            max_sector_pct=settings.max_sector_pct,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            min_reward_risk=settings.min_reward_risk,
        ),
    )


def news_from(ctx: AgentContext) -> list[Any]:
    bundle = bundle_from(ctx)
    res = ctx.registry.news(bundle.symbol, limit=12)
    return res.value


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}%"


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1e5:
        return f"INR {value / 1e5:,.1f} lakh crore"
    return f"INR {value:,.0f} crore"
