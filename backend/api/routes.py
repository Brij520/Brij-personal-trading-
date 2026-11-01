"""HTTP API. Every route is read/research; none can transact.

Route groups
------------
* ``/api/system``    — status, safety flags, capability catalogue
* ``/api/market``    — indices, sectors, movers, breadth
* ``/api/universe``  — search and instrument metadata
* ``/api/stocks``    — quote, fundamentals, technical, valuation, options, news, chart
* ``/api/research``  — run the agent pipeline, export reports
* ``/api/agents``    — agent catalogue and single-agent runs
* ``/api/risk``      — sizing and validation (veto cannot be overridden)
* ``/api/backtest``  — backtest, walk-forward, comparison
* ``/api/screener``  — scanner with printed conditions
* ``/api/journal``   — paper trades, reviews, notes
* ``/api/portfolio`` — import and analyse holdings
"""

from __future__ import annotations

import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.agents.base import AgentError
from backend.analytics import indicators as ind
from backend.analytics import valuation as val
from backend.analytics.fundamental import analyse_fundamentals
from backend.analytics.risk import RiskLimits, TradeProposal, validate_proposal
from backend.api.schemas import (
    BacktestRequest,
    HoldingIn,
    NoteCreate,
    OptionChainRequest,
    PayoffRequest,
    PortfolioImport,
    PositionSizeRequest,
    ResearchRequest,
    StrategyCompareRequest,
    TradeClose,
    TradeCreate,
    TradeValidationRequest,
)
from backend.backtesting.costs import CostConfig
from backend.backtesting.engine import BacktestConfig, compare, run_backtest, train_test_split_backtest, walk_forward
from backend.core.config import get_settings
from backend.core.errors import BTIError, NotFoundError, ValidationError
from backend.core.provenance import utcnow
from backend.data.registry import get_registry
from backend.data.universe import INSTRUMENTS, SECTORS, get_instrument, search_instruments
from backend.journal.analytics import build_review, performance_summary, strategy_breakdown
from backend.journal.store import JournalStore
from backend.services.market import SCANNER_CATALOGUE, market_overview, run_screener
from backend.services.orchestrator import AGENT_REGISTRY, describe_agents, run_research
from backend.services.report_generator import export_report
from backend.strategies.library import STRATEGIES, get_strategy, list_strategies

router = APIRouter(prefix="/api")

DISCLAIMER = (
    "Research and education only. Not investment advice. No orders are placed. "
    "Data may be delayed or (in demo mode) synthetic."
)


@lru_cache(maxsize=1)
def journal() -> JournalStore:
    return JournalStore()


def _json_safe(value: Any) -> Any:
    """Recursively replace NaN/Inf and non-serialisable objects."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else round(value, 6)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    return value


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(content=_json_safe(payload))


# ------------------------------------------------------------------- system
@router.get("/system/status")
def system_status():
    settings = get_settings()
    registry = get_registry()
    return ok(
        {
            "app": settings.app_name,
            "version": settings.version,
            "owner": settings.owner,
            "environment": settings.environment,
            "data_mode": settings.data_mode,
            "safety": settings.safety_snapshot(),
            "providers": registry.health(),
            "coverage": {
                "instruments": len(INSTRUMENTS),
                "sectors": len(SECTORS),
                "agents": len(AGENT_REGISTRY),
                "strategies": len(STRATEGIES),
                "scanner_conditions": len(SCANNER_CATALOGUE),
            },
            "agents": describe_agents(),
            "strategies": list_strategies(),
            "limits": {
                "max_position_risk_pct": settings.max_position_risk_pct,
                "max_portfolio_heat_pct": settings.max_portfolio_heat_pct,
                "max_single_stock_pct": settings.max_single_stock_pct,
                "max_sector_pct": settings.max_sector_pct,
                "daily_loss_limit_pct": settings.daily_loss_limit_pct,
                "min_reward_risk": settings.min_reward_risk,
            },
            "llm": {
                "provider": settings.llm_provider,
                "mode": "deterministic rule engine" if settings.llm_provider == "none"
                else "provider configured",
            },
            "disclaimer": DISCLAIMER,
        }
    )


@router.get("/health")
def health():
    return ok({"status": "ok", "time": utcnow().isoformat()})


# ------------------------------------------------------------------- market
@router.get("/market/overview")
def get_market_overview():
    return ok(market_overview(get_registry()))


@router.get("/market/indices")
def get_indices():
    overview = market_overview(get_registry())
    return ok({"indices": overview["indices"], "regime": overview["regime"],
               "is_synthetic": overview["is_synthetic"]})


@router.get("/universe")
def universe(sector: str | None = None):
    rows = [
        {
            "symbol": i.symbol,
            "name": i.name,
            "sector": i.sector,
            "industry": i.industry,
            "exchange": i.exchange,
            "indices": list(i.indices),
            "fno": i.fno,
        }
        for i in INSTRUMENTS
        if not sector or i.sector == sector
    ]
    return ok({"instruments": rows, "sectors": SECTORS, "count": len(rows)})


@router.get("/universe/search")
def universe_search(q: str = Query(default="", max_length=40), limit: int = Query(default=15, le=50)):
    results = search_instruments(q, limit=limit)
    return ok(
        {
            "query": q,
            "results": [
                {
                    "symbol": i.symbol,
                    "name": i.name,
                    "sector": i.sector,
                    "industry": i.industry,
                    "fno": i.fno,
                }
                for i in results
            ],
        }
    )


# ------------------------------------------------------------------- stocks
def _require_symbol(symbol: str):
    inst = get_instrument(symbol)
    if inst is None:
        raise NotFoundError(f"{symbol.upper()} is not in the supported universe")
    return inst


@router.get("/stocks/{symbol}/quote")
def stock_quote(symbol: str):
    _require_symbol(symbol)
    res = get_registry().quote(symbol.upper())
    quote = res.value
    return ok(
        {
            "symbol": quote.symbol,
            "last_price": quote.last_price,
            "change": quote.change,
            "change_pct": quote.change_pct,
            "day_open": quote.day_open,
            "day_high": quote.day_high,
            "day_low": quote.day_low,
            "prev_close": quote.prev_close,
            "volume": quote.volume,
            "week52_high": quote.week52_high,
            "week52_low": quote.week52_low,
            "provenance": quote.provenance.model_dump(mode="json"),
            "warnings": res.warnings,
        }
    )


@router.get("/stocks/{symbol}/chart")
def stock_chart(symbol: str, timeframe: str = "1d", bars: int = Query(default=400, ge=50, le=3000)):
    if timeframe not in {"1d", "15m", "60m"}:
        raise ValidationError("timeframe must be 1d, 15m or 60m")
    _require_symbol(symbol)
    res = get_registry().history(symbol.upper(), timeframe=timeframe, lookback=bars)
    series = res.value
    frame = series.frame
    enriched = ind.enrich(frame)
    rows = []
    for ts, row in enriched.iterrows():
        rows.append(
            {
                "time": ts.isoformat(),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(row["volume"]),
                "ema20": None if row["ema20"] != row["ema20"] else round(float(row["ema20"]), 2),
                "ema50": None if row["ema50"] != row["ema50"] else round(float(row["ema50"]), 2),
                "ema200": None if row["ema200"] != row["ema200"] else round(float(row["ema200"]), 2),
                "vwap": None if row["vwap"] != row["vwap"] else round(float(row["vwap"]), 2),
            }
        )
    return ok(
        {
            "symbol": series.symbol,
            "timeframe": timeframe,
            "bars": rows,
            "provenance": series.meta.model_dump(mode="json"),
            "warnings": res.warnings,
        }
    )


@router.get("/stocks/{symbol}/fundamentals")
def stock_fundamentals(symbol: str):
    _require_symbol(symbol)
    res = get_registry().fundamentals(symbol.upper())
    fund = res.value
    analysis = analyse_fundamentals(fund)
    return ok(
        {
            "symbol": fund.symbol,
            "company_name": fund.company_name,
            "sector": fund.sector,
            "industry": fund.industry,
            "market_cap_cr": fund.market_cap,
            "analysis": analysis.summary(),
            "annual": [
                {
                    "fiscal_year": a.fiscal_year,
                    "period_end": a.period_end.isoformat(),
                    "revenue_cr": a.revenue,
                    "ebitda_cr": a.ebitda,
                    "pat_cr": a.pat,
                    "eps": a.eps,
                    "cfo_cr": a.cfo,
                    "capex_cr": a.capex,
                    "total_debt_cr": a.total_debt,
                    "equity_cr": a.equity,
                    "interest_cr": a.interest_expense,
                }
                for a in fund.annual
            ],
            "quarterly": [
                {
                    "period": q.period,
                    "period_end": q.period_end.isoformat(),
                    "revenue_cr": q.revenue,
                    "ebitda_cr": q.ebitda,
                    "pat_cr": q.pat,
                    "eps": q.eps,
                }
                for q in fund.quarterly
            ],
            "shareholding": {
                "promoter_pct": fund.promoter_holding_pct,
                "promoter_pledge_pct": fund.promoter_pledge_pct,
                "fii_pct": fund.fii_holding_pct,
                "dii_pct": fund.dii_holding_pct,
                "retail_pct": fund.retail_holding_pct,
            },
            "red_flag_notes": fund.red_flag_notes,
            "provenance": fund.provenance.model_dump(mode="json"),
            "warnings": res.warnings,
        }
    )


@router.get("/stocks/{symbol}/technical")
def stock_technical(symbol: str, timeframe: str = "1d"):
    _require_symbol(symbol)
    res = get_registry().history(symbol.upper(), timeframe=timeframe, lookback=500)
    frame = ind.enrich(res.value.frame)
    clean = frame.dropna(subset=["rsi14"])
    if clean.empty:
        raise ValidationError("insufficient history for technical analysis")
    row = clean.iloc[-1]
    close = float(row["close"])
    macd_frame = ind.macd(frame["close"])
    return ok(
        {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "price": round(close, 2),
            "indicators": {
                k: (None if pd.isna(row[k]) else round(float(row[k]), 4))
                for k in (
                    "ema20", "ema50", "ema200", "sma50", "rsi14", "macd", "macd_signal",
                    "macd_hist", "atr14", "adx14", "plus_di", "minus_di", "bb_upper",
                    "bb_lower", "bb_width", "stoch_k", "stoch_d", "vol_ratio", "vol20", "vwap",
                )
                if k in row
            },
            "levels": ind.support_resistance(frame, close),
            "fibonacci": ind.fibonacci_levels(
                float(frame["low"].tail(60).min()), float(frame["high"].tail(60).max())
            ),
            "divergence": ind.detect_divergence(clean["close"], clean["rsi14"]),
            "trend": {
                "primary": "up" if close > float(row["ema200"]) else "down",
                "intermediate": "up" if close > float(row["ema50"]) else "down",
                "short_term": "up" if close > float(row["ema20"]) else "down",
            },
            "macd_series": [
                {"date": d.isoformat(), "macd": None if pd.isna(v) else round(float(v), 3)}
                for d, v in macd_frame["macd"].tail(120).items()
            ],
            "rsi_series": [
                {"date": d.isoformat(), "rsi": None if pd.isna(v) else round(float(v), 2)}
                for d, v in frame["rsi14"].tail(120).items()
            ],
            "provenance": res.value.meta.model_dump(mode="json"),
        }
    )


@router.get("/stocks/{symbol}/valuation")
def stock_valuation(symbol: str):
    _require_symbol(symbol)
    from backend.services.orchestrator import run_single_agent

    finding = run_single_agent("valuation", symbol.upper())
    return ok(finding.model_dump(mode="json"))


@router.get("/stocks/{symbol}/news")
def stock_news(symbol: str, limit: int = Query(default=12, le=30)):
    _require_symbol(symbol)
    from backend.services.orchestrator import run_single_agent

    finding = run_single_agent("news_sentiment", symbol.upper())
    return ok(finding.model_dump(mode="json"))


@router.get("/stocks/{symbol}/options")
def stock_options(symbol: str, expiry: date | None = None):
    _require_symbol(symbol)
    from backend.services.orchestrator import run_single_agent

    finding = run_single_agent("options", symbol.upper())
    return ok(finding.model_dump(mode="json"))


@router.post("/options/payoff")
def options_payoff(payload: PayoffRequest):
    from backend.agents.options_intelligence import Leg, structure_summary

    legs = [
        Leg(l.action, l.kind, l.strike, l.premium, l.quantity) for l in payload.legs
    ]
    summary = structure_summary(legs, payload.spot, payload.lot_size)
    return ok(
        {
            **summary,
            "note": (
                "Payoff is a mathematical construction at expiry. It ignores IV "
                "changes, assignment and liquidity. margin_estimate is a conservative "
                "research stress estimate, not broker SPAN/Exposure margin. "
                "F&O execution is disabled."
            ),
        }
    )


# ----------------------------------------------------------------- research
@router.post("/research/{symbol}")
def research(symbol: str, payload: ResearchRequest | None = None):
    _require_symbol(symbol)
    lookback = payload.lookback if payload else 750
    report = run_research(symbol.upper(), lookback=lookback)
    return ok(report.to_dict())


@router.get("/research/{symbol}")
def research_get(symbol: str, lookback: int = Query(default=750, ge=260, le=2000)):
    _require_symbol(symbol)
    report = run_research(symbol.upper(), lookback=lookback)
    return ok(report.to_dict())


@router.get("/research/{symbol}/report")
def research_report(symbol: str, format: str = Query(default="markdown")):
    _require_symbol(symbol)
    report = run_research(symbol.upper())
    try:
        path = export_report(report, format)
    except ValidationError as exc:
        raise exc
    media = {
        "markdown": "text/markdown",
        "html": "text/html",
        "pdf": "application/pdf",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
    }
    return FileResponse(
        path,
        media_type=media.get(format, "application/octet-stream"),
        filename=path.name,
    )


@router.get("/agents")
def agents():
    return ok(
        {
            "agents": describe_agents(),
            "count": len(AGENT_REGISTRY),
            "note": (
                "Agents produce structured findings. The risk agent's rejection is "
                "final; no agent can place an order."
            ),
        }
    )


@router.post("/agents/{agent_name}/run")
def run_agent(agent_name: str, symbol: str = Query(...)):
    _require_symbol(symbol)
    if agent_name not in AGENT_REGISTRY:
        raise NotFoundError(f"unknown agent {agent_name}")
    from backend.services.orchestrator import run_single_agent

    finding = run_single_agent(agent_name, symbol.upper())
    return ok(finding.model_dump(mode="json"))


# --------------------------------------------------------------------- risk
@router.get("/risk/limits")
def risk_limits():
    s = get_settings()
    return ok(
        {
            "limits": {
                "max_position_risk_pct": s.max_position_risk_pct,
                "max_portfolio_heat_pct": s.max_portfolio_heat_pct,
                "max_single_stock_pct": s.max_single_stock_pct,
                "max_sector_pct": s.max_sector_pct,
                "daily_loss_limit_pct": s.daily_loss_limit_pct,
                "min_reward_risk": s.min_reward_risk,
            },
            "note": (
                "These are platform defaults, not Brij's personal limits. They are "
                "configurable via environment variables (BTI_MAX_*)."
            ),
        }
    )


@router.post("/risk/position-size")
def position_size(payload: PositionSizeRequest):
    from backend.analytics.risk import risk_based_sizing

    qty, detail = risk_based_sizing(
        capital=payload.capital,
        entry=payload.entry,
        stop_loss=payload.stop_loss,
        risk_pct=payload.risk_pct,
        max_position_pct=payload.max_position_pct,
        lot_size=payload.lot_size,
    )
    reward = None
    return ok(
        {
            "quantity": qty,
            "detail": detail,
            "position_value": round(qty * payload.entry, 2),
            "risk_amount": round(qty * (payload.entry - payload.stop_loss), 2),
            "risk_pct_of_capital": round(
                qty * (payload.entry - payload.stop_loss) / payload.capital * 100, 3
            ),
            "stop_distance_pct": round(
                (payload.entry - payload.stop_loss) / payload.entry * 100, 2
            ),
            "formula": (
                "quantity = floor((capital x risk_pct / 100) / (entry - stop_loss) / lot) x lot"
            ),
            "disclaimer": DISCLAIMER,
        }
    )


@router.post("/risk/validate")
def risk_validate(payload: TradeValidationRequest):
    settings = get_settings()
    limits = RiskLimits(
        capital=payload.capital or settings.capital,
        max_position_risk_pct=settings.max_position_risk_pct,
        max_portfolio_heat_pct=settings.max_portfolio_heat_pct,
        max_single_stock_pct=settings.max_single_stock_pct,
        max_sector_pct=settings.max_sector_pct,
        min_reward_risk=settings.min_reward_risk,
    )
    decision = validate_proposal(
        TradeProposal(
            symbol=payload.symbol.upper(),
            side=payload.side,
            entry=payload.entry,
            stop_loss=payload.stop_loss,
            target=payload.target,
            sector=payload.sector,
            atr=payload.atr,
            strategy=payload.strategy,
            is_fno=payload.is_fno,
        ),
        limits,
        open_risk_pct=payload.open_risk_pct,
    )
    return ok(decision.to_dict())


# ----------------------------------------------------------------- backtest
@router.get("/backtest/strategies")
def backtest_strategies():
    return ok(
        {
            "strategies": list_strategies(),
            "costs_note": (
                "Delivery: brokerage 0.03%/side, STT 0.10%/side, exchange 0.00297%, "
                "SEBI 0.0001%, stamp duty 0.015% buy, GST 18% on brokerage+charges, "
                "plus explicit slippage."
            ),
        }
    )


@router.post("/backtest/run")
def backtest_run(payload: BacktestRequest):
    symbol = payload.symbol.upper()
    _require_symbol(symbol)
    try:
        spec = get_strategy(payload.strategy)
    except KeyError as exc:
        raise ValidationError(str(exc)) from exc
    if spec.family == "intraday" and payload.timeframe == "1d":
        raise ValidationError(
            "this strategy needs an intraday frame; set timeframe to 15m or 60m"
        )
    res = get_registry().history(symbol, timeframe=payload.timeframe, lookback=payload.lookback)
    config = BacktestConfig(
        initial_capital=payload.initial_capital,
        risk_per_trade_pct=payload.risk_per_trade_pct,
        max_position_pct=payload.max_position_pct,
        costs=CostConfig(segment=payload.segment, slippage_bps=payload.slippage_bps),
    )
    result = run_backtest(res.value, spec.signal_fn, config, spec.name)
    payload_out: dict[str, Any] = result.to_dict()
    payload_out["strategy_detail"] = spec.summary()
    if payload.lookback >= 600:
        payload_out["walk_forward"] = walk_forward(
            res.value, spec.signal_fn, config, folds=payload.walk_forward_folds or 4,
            strategy_name=spec.name,
        )
        payload_out["out_of_sample"] = train_test_split_backtest(
            res.value, spec.signal_fn, config, payload.out_of_sample_split, spec.name
        )
    payload_out["disclaimer"] = (
        "Backtest results are historical simulations with modelled costs. They are "
        "not evidence of future returns, and synthetic data will produce synthetic "
        "results."
    )
    return ok(payload_out)


@router.post("/backtest/compare")
def backtest_compare(payload: StrategyCompareRequest):
    symbol = payload.symbol.upper()
    _require_symbol(symbol)
    res = get_registry().history(symbol, lookback=payload.lookback)
    config = BacktestConfig()
    results = []
    skipped: list[dict[str, str]] = []
    for key in payload.strategies:
        try:
            spec = get_strategy(key)
        except KeyError as exc:
            raise ValidationError(str(exc)) from exc
        if spec.family == "intraday":
            # Comparing an intraday rule on daily bars produces zero trades and
            # a meaningless row, so it is reported as skipped rather than shown.
            skipped.append(
                {
                    "strategy": spec.name,
                    "reason": "intraday strategy — needs a 15m/60m frame; use /backtest/run",
                }
            )
            continue
        results.append(run_backtest(res.value, spec.signal_fn, config, spec.name))
    return ok(
        {
            "symbol": symbol,
            "comparison": compare(results),
            "skipped": skipped,
            "note": (
                "Sorted by Sharpe. Check trade counts before drawing conclusions; "
                "fewer than 20 trades is not evidence."
            ),
        }
    )


# ----------------------------------------------------------------- screener
@router.get("/screener")
def screener(
    scans: str = Query(default="quality", description="comma separated scan keys"),
    sector: str | None = None,
    limit: int = Query(default=30, le=100),
):
    keys = [s.strip() for s in scans.split(",") if s.strip()]
    payload = run_screener(get_registry(), scans=keys, sector=sector, limit=limit)
    return ok(payload)


@router.get("/screener/definitions")
def screener_definitions():
    return ok({"definitions": SCANNER_CATALOGUE})


# ------------------------------------------------------------------ journal
@router.get("/journal/trades")
def journal_trades(status: str | None = None, symbol: str | None = None, limit: int = 200):
    trades = journal().list_trades(status=status, symbol=symbol, limit=limit)
    return ok({"trades": [t.to_dict() for t in trades], "count": len(trades)})


@router.post("/journal/trades")
def journal_add_trade(payload: TradeCreate):
    record = journal().add_trade(payload.model_dump())
    return ok({"trade": record.to_dict()})


@router.post("/journal/trades/{trade_id}/close")
def journal_close_trade(trade_id: int, payload: TradeClose):
    record = journal().close_trade(trade_id, payload.model_dump())
    return ok({"trade": record.to_dict()})


@router.post("/journal/trades/{trade_id}/cancel")
def journal_cancel_trade(trade_id: int, reason: str | None = None):
    record = journal().cancel_trade(trade_id, reason)
    return ok({"trade": record.to_dict()})


@router.get("/journal/performance")
def journal_performance():
    trades = journal().list_trades(limit=1000)
    return ok(
        {
            "summary": performance_summary(trades),
            "by_strategy": strategy_breakdown(trades),
        }
    )


@router.get("/journal/review")
def journal_review(period: str = "weekly"):
    trades = journal().list_trades(limit=1000)
    return ok(build_review(trades, period))


@router.get("/journal/notes")
def journal_notes(kind: str | None = None):
    return ok({"notes": journal().list_notes(kind)})


@router.post("/journal/notes")
def journal_add_note(payload: NoteCreate):
    note_id = journal().add_note(payload.model_dump())
    return ok({"id": note_id})


# ---------------------------------------------------------------- portfolio
@router.get("/portfolio/holdings")
def portfolio_holdings():
    return ok({"holdings": journal().list_holdings()})


@router.post("/portfolio/import")
def portfolio_import(payload: PortfolioImport):
    rows = [
        {
            "symbol": h.symbol.upper().strip(),
            "quantity": h.quantity,
            "avg_price": h.avg_price,
            "name": h.name,
            "sector": h.sector or (get_instrument(h.symbol.upper()).sector
                                   if get_instrument(h.symbol.upper()) else "Unknown"),
        }
        for h in payload.holdings
    ]
    count = journal().upsert_holdings(rows)
    return ok({"imported": count, "holdings": journal().list_holdings()})


@router.delete("/portfolio/holdings/{symbol}")
def portfolio_delete(symbol: str):
    removed = journal().delete_holding(symbol)
    if not removed:
        raise NotFoundError(f"{symbol.upper()} is not in the portfolio")
    return ok({"removed": symbol.upper()})


@router.get("/portfolio/analysis")
def portfolio_analysis(include_agents: bool = False):
    from backend.agents.base import AgentContext
    from backend.agents.portfolio_manager import PortfolioManagerAgent
    from backend.core.config import get_settings as gs

    ctx = AgentContext(registry=get_registry(), settings=gs())
    ctx.cache["journal_store"] = journal()
    finding = PortfolioManagerAgent().safe_run(ctx)
    return ok(finding.model_dump(mode="json"))


@router.get("/portfolio/snapshots")
def portfolio_snapshots():
    return ok({"snapshots": journal().list_snapshots()})


@router.post("/portfolio/snapshot")
def portfolio_snapshot():
    from backend.agents.base import AgentContext
    from backend.agents.portfolio_manager import PortfolioManagerAgent

    ctx = AgentContext(registry=get_registry(), settings=get_settings())
    ctx.cache["journal_store"] = journal()
    finding = PortfolioManagerAgent().safe_run(ctx)
    total = finding.metrics.get("exposure", {}).get("total_value", 0.0)
    invested = finding.metrics.get("exposure", {}).get("invested", 0.0)
    snapshot_id = journal().add_snapshot(
        float(total or 0), float(invested or 0), json.dumps(finding.metrics)
    )
    return ok({"snapshot_id": snapshot_id, "total_value": total, "invested": invested})
