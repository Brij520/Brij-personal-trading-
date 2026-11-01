"""Journal analytics: performance, mistakes and periodic reviews.

The AI **describes** patterns; it never changes a strategy by itself. Any
suggested improvement is returned as a proposal for human review, with the
sample size stated. With fewer than ``MIN_SAMPLE`` closed trades the review says
so and refuses to draw conclusions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

import numpy as np

from backend.journal.store import TradeRecord

MIN_SAMPLE = 20


def performance_summary(trades: list[TradeRecord]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "CLOSED" and t.pnl is not None]
    open_trades = [t for t in trades if t.status == "OPEN"]
    if not closed:
        return {
            "closed_trades": 0,
            "open_trades": len(open_trades),
            "note": "No closed paper trades yet; performance statistics are not computable.",
        }
    pnls = [float(t.pnl) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    rs = [float(t.r_multiple) for t in closed if t.r_multiple is not None]
    win_rate = len(wins) / len(closed)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "closed_trades": len(closed),
        "open_trades": len(open_trades),
        "total_pnl": round(sum(pnls), 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "avg_win": round(mean(wins), 2) if wins else 0.0,
        "avg_loss": round(mean(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "expectancy": round(win_rate * (mean(wins) if wins else 0)
                            + (1 - win_rate) * (mean(losses) if losses else 0), 2),
        "avg_r_multiple": round(mean(rs), 2) if rs else None,
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "total_costs": round(sum(float(t.costs or 0) for t in closed), 2),
        "sample_warning": (
            f"Only {len(closed)} closed trades. Fewer than {MIN_SAMPLE} is not "
            "statistically meaningful — treat every statistic as provisional."
            if len(closed) < MIN_SAMPLE
            else None
        ),
    }


def strategy_breakdown(trades: list[TradeRecord]) -> list[dict[str, Any]]:
    buckets: dict[str, list[TradeRecord]] = defaultdict(list)
    for t in trades:
        if t.status == "CLOSED" and t.pnl is not None:
            buckets[t.strategy or "unspecified"].append(t)
    rows = []
    for strategy, group in buckets.items():
        pnls = [float(t.pnl) for t in group]
        wins = [p for p in pnls if p > 0]
        rows.append(
            {
                "strategy": strategy,
                "trades": len(group),
                "pnl": round(sum(pnls), 2),
                "win_rate_pct": round(len(wins) / len(group) * 100, 2),
                "avg_pnl": round(mean(pnls), 2),
                "note": "provisional" if len(group) < MIN_SAMPLE else "usable sample",
            }
        )
    return sorted(rows, key=lambda r: r["pnl"], reverse=True)


def mistake_analysis(trades: list[TradeRecord]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "CLOSED"]
    counter: Counter[str] = Counter()
    for t in closed + [t for t in trades if t.status == "OPEN"]:
        if not t.mistakes:
            continue
        for tag in str(t.mistakes).replace(";", ",").split(","):
            tag = tag.strip().lower()
            if tag:
                counter[tag] += 1
    loss_by_mistake: dict[str, float] = defaultdict(float)
    for t in closed:
        if not t.mistakes or t.pnl is None:
            continue
        for tag in str(t.mistakes).replace(";", ",").split(","):
            tag = tag.strip().lower()
            if tag and t.pnl < 0:
                loss_by_mistake[tag] += float(t.pnl)
    top = [
        {
            "mistake": tag,
            "occurrences": n,
            "loss_attributed": round(loss_by_mistake.get(tag, 0.0), 2),
        }
        for tag, n in counter.most_common(10)
    ]
    discipline = discipline_checks(trades)
    return {
        "tagged_mistakes": top,
        "untagged_closed_trades": sum(1 for t in closed if not t.mistakes),
        "discipline_findings": discipline,
        "note": (
            "Patterns are descriptive. The AI does not modify strategies from these "
            "observations, and any change needs a documented test."
        ),
    }


def discipline_checks(trades: list[TradeRecord]) -> list[dict[str, Any]]:
    """Objective process violations, independent of P&L."""
    findings: list[dict[str, Any]] = []
    no_stop = [t for t in trades if t.stop_loss is None and t.status != "CANCELLED"]
    if no_stop:
        findings.append(
            {
                "check": "stop-loss defined on every trade",
                "violations": len(no_stop),
                "symbols": [t.symbol for t in no_stop][:10],
                "severity": "HIGH",
            }
        )
    no_thesis = [t for t in trades if not t.thesis and t.status != "CANCELLED"]
    if no_thesis:
        findings.append(
            {
                "check": "written thesis before entry",
                "violations": len(no_thesis),
                "severity": "MEDIUM",
            }
        )
    # Revenge trading: a new entry on the same day a trade closed at a loss.
    losses_by_date: dict[str, int] = Counter(
        str(t.exit_date) for t in trades if t.status == "CLOSED" and (t.pnl or 0) < 0
    )
    entries: dict[str, list[str]] = defaultdict(list)
    for t in trades:
        entries[str(t.entry_date)].append(t.symbol)
    revenge = [
        {"date": d, "new_entries": entries[d]}
        for d, n in losses_by_date.items()
        if n >= 1 and d in entries
    ]
    if revenge:
        findings.append(
            {
                "check": "no new position on the same day as a realised loss",
                "violations": len(revenge),
                "examples": revenge[:5],
                "severity": "MEDIUM",
            }
        )
    # Overtrading: more than 5 entries in one day.
    heavy = {d: v for d, v in entries.items() if len(v) > 5}
    if heavy:
        findings.append(
            {
                "check": "at most 5 new positions per day",
                "violations": len(heavy),
                "days": list(heavy)[:5],
                "severity": "MEDIUM",
            }
        )
    return findings


def open_position_risk(trades: list[TradeRecord]) -> list[dict[str, Any]]:
    rows = []
    for t in trades:
        if t.status != "OPEN" or t.stop_loss is None:
            continue
        risk = abs(t.entry_price - t.stop_loss) * t.quantity
        rows.append(
            {
                "id": t.id,
                "symbol": t.symbol,
                "risk_amount": round(risk, 2),
                "stop_distance_pct": round(abs(t.entry_price - t.stop_loss) / t.entry_price * 100, 2),
            }
        )
    return rows


def build_review(
    trades: list[TradeRecord], period: str, *, today: date | None = None
) -> dict[str, Any]:
    """Daily / weekly / monthly review with an explicit sample-size caveat."""
    today = today or date.today()
    if period == "daily":
        start = today
    elif period == "weekly":
        start = today - timedelta(days=7)
    elif period == "monthly":
        start = today - timedelta(days=30)
    else:
        raise ValueError("period must be daily, weekly or monthly")

    def in_window(t: TradeRecord) -> bool:
        for stamp in (t.entry_date, t.exit_date):
            if not stamp:
                continue
            try:
                d = datetime.fromisoformat(str(stamp)[:10]).date()
            except ValueError:
                continue
            if start <= d <= today:
                return True
        return False

    window = [t for t in trades if in_window(t)]
    summary = performance_summary(window)
    breakdown = strategy_breakdown(window)
    mistakes = mistake_analysis(window)

    observations: list[str] = []
    if summary.get("closed_trades", 0) == 0:
        observations.append("No trades were closed in this window; there is nothing to evaluate.")
    else:
        observations.append(
            f"{summary['closed_trades']} closed trade(s) with total P&L "
            f"{summary['total_pnl']:,.0f} and a {summary['win_rate_pct']:.0f}% win rate."
        )
        if summary.get("avg_r_multiple") is not None:
            observations.append(
                f"Average R-multiple {summary['avg_r_multiple']:.2f}: "
                + ("the process is producing positive expectancy."
                   if summary["avg_r_multiple"] > 0
                   else "the process is currently negative — review entries, not just exits.")
            )
    for finding in mistakes["discipline_findings"]:
        observations.append(
            f"Discipline: {finding['violations']} violation(s) of '{finding['check']}'."
        )

    proposals: list[dict[str, Any]] = []
    if summary.get("closed_trades", 0) >= MIN_SAMPLE:
        worst = breakdown[-1] if breakdown else None
        if worst and worst["pnl"] < 0:
            proposals.append(
                {
                    "proposal": (
                        f"Review or pause the '{worst['strategy']}' strategy: "
                        f"{worst['trades']} trades, P&L {worst['pnl']:,.0f}."
                    ),
                    "requires": "out-of-sample backtest before any parameter change",
                    "approved_automatically": False,
                }
            )
    else:
        proposals.append(
            {
                "proposal": "Not enough closed trades to propose a strategy change.",
                "requires": f"at least {MIN_SAMPLE} closed trades",
                "approved_automatically": False,
            }
        )

    return {
        "period": period,
        "window_start": start.isoformat(),
        "window_end": today.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "trades_in_window": len(window),
        "summary": summary,
        "strategy_breakdown": breakdown,
        "mistakes": mistakes,
        "open_risk": open_position_risk([t for t in trades if t.status == "OPEN"]),
        "observations": observations,
        "proposals": proposals,
        "guardrails": [
            "The AI never modifies a strategy automatically.",
            "Any change requires a documented hypothesis, a backtest and out-of-sample validation.",
            "Reviews under 20 closed trades are descriptive only.",
        ],
    }


def equity_curve_from_trades(trades: list[TradeRecord], initial: float = 0.0) -> list[dict[str, Any]]:
    closed = sorted(
        [t for t in trades if t.status == "CLOSED" and t.pnl is not None and t.exit_date],
        key=lambda t: str(t.exit_date),
    )
    equity = initial
    out = []
    for t in closed:
        equity += float(t.pnl)
        out.append({"date": str(t.exit_date), "equity": round(equity, 2), "symbol": t.symbol})
    return out
