"""Event-driven backtester with explicit, auditable execution assumptions.

Anti-bias design
----------------
* **No look-ahead.** A signal computed on bar *t* is executed at the open of
  bar *t+1*. Intrabar stop/target fills use the bar's high/low, and when a bar
  could hit both, the **stop is assumed to fill first** (conservative).
* **Costs and slippage** are applied on every fill, both sides.
* **Position sizing** is risk-based (fixed fractional) so results cannot be
  inflated by compounding fixed share counts.
* **No shorting** in long-only strategies; one position at a time.
* **Survivorship**: the universe is an explicit list of live symbols. This
  engine cannot fix that by itself — see the documented limitation.

Reported metrics include the ones that expose poor strategies: expectancy,
profit factor, max drawdown, exposure and cost drag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from backend.backtesting.costs import CostConfig, LiquidityConfig
from backend.data.providers.base import Series

TRADING_DAYS = 252


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None
    exit_price: float | None
    quantity: int
    stop_loss: float
    target: float
    costs: float = 0.0
    slippage: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    r_multiple: float = 0.0
    bars_held: int = 0
    exit_reason: str = "open"

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date.date().isoformat(),
            "exit_date": self.exit_date.date().isoformat() if self.exit_date is not None else None,
            "entry_price": round(self.entry_price, 2),
            "exit_price": None if self.exit_price is None else round(self.exit_price, 2),
            "quantity": self.quantity,
            "stop_loss": round(self.stop_loss, 2),
            "target": round(self.target, 2),
            "costs": round(self.costs, 2),
            "slippage": round(self.slippage, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 2),
            "r_multiple": round(self.r_multiple, 2),
            "bars_held": self.bars_held,
            "exit_reason": self.exit_reason,
        }


@dataclass
class BacktestConfig:
    initial_capital: float = 20_000.0
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    costs: CostConfig = field(default_factory=CostConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    #: Optional hard stop in ATR units, applied in addition to the strategy stop.
    max_bars_in_trade: int = 0
    warmup_bars: int = 220


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    trades: list[Trade]
    equity_curve: pd.Series
    daily_returns: pd.Series
    metrics: dict[str, float]
    config: BacktestConfig
    warnings: list[str] = field(default_factory=list)
    assumptions: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "metrics": self.metrics,
            "trades": [t.as_dict() for t in self.trades],
            "equity_curve": [
                {"date": d.date().isoformat(), "equity": round(float(v), 2)}
                for d, v in self.equity_curve.items()
            ],
            "warnings": self.warnings,
            "assumptions": self.assumptions,
        }


#: A signal function receives the indicator frame and returns a DataFrame with
#: columns ``entry_signal`` (bool), ``stop``, ``target`` (prices) computed using
#: only data available at that bar.
SignalFn = Callable[[pd.DataFrame], pd.DataFrame]


def _metrics(
    equity: pd.Series, trades: list[Trade], initial: float, exposure: float
) -> dict[str, float]:
    if equity.empty:
        return {}
    daily = equity.pct_change().dropna()
    years = max(len(equity) / TRADING_DAYS, 1e-9)
    total_return = float(equity.iloc[-1] / initial - 1)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0
    downside = daily[daily < 0]
    peak = equity.cummax()
    dd = equity / peak - 1
    closed = [t for t in trades if t.exit_date is not None]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
    win_rate = len(wins) / len(closed) if closed else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss if closed else 0.0
    sharpe = (
        float(daily.mean() / daily.std(ddof=0) * np.sqrt(TRADING_DAYS))
        if len(daily) > 1 and daily.std(ddof=0) > 0
        else 0.0
    )
    sortino = (
        float(daily.mean() / downside.std(ddof=0) * np.sqrt(TRADING_DAYS))
        if len(downside) > 1 and downside.std(ddof=0) > 0
        else 0.0
    )
    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(float(dd.min()) * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "trades": float(len(closed)),
        "win_rate_pct": round(win_rate * 100, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")
        if gross_win > 0
        else 0.0,
        "expectancy_per_trade": round(expectancy, 2),
        "avg_r_multiple": round(float(np.mean([t.r_multiple for t in closed])), 2)
        if closed
        else 0.0,
        "exposure_pct": round(exposure * 100, 2),
        "total_costs": round(sum(t.costs for t in trades), 2),
        "cost_drag_pct_of_capital": round(sum(t.costs for t in trades) / initial * 100, 2),
        "final_equity": round(float(equity.iloc[-1]), 2),
    }


def run_backtest(
    series: Series,
    signal_fn: SignalFn,
    config: BacktestConfig | None = None,
    strategy_name: str = "unnamed",
) -> BacktestResult:
    config = config or BacktestConfig()
    frame = series.frame
    warnings: list[str] = []
    if len(frame) < config.warmup_bars + 30:
        warnings.append(
            f"Only {len(frame)} bars available; results before "
            f"{config.warmup_bars} warmup bars are discarded and the sample is short."
        )
    signals = signal_fn(frame)
    required = {"entry_signal", "stop", "target"}
    if not required.issubset(signals.columns):
        raise ValueError(f"signal_fn must return columns {sorted(required)}")
    signals = signals.reindex(frame.index)

    cash = config.initial_capital
    position: Trade | None = None
    trades: list[Trade] = []
    equity_points: list[float] = []
    equity_index: list[pd.Timestamp] = []
    bars_in_market = 0
    pending: dict | None = None

    opens = frame["open"].to_numpy()
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    volumes = frame["volume"].to_numpy()
    entry_flags = signals["entry_signal"].fillna(False).to_numpy(dtype=bool)
    stops = signals["stop"].to_numpy(dtype=float)
    targets = signals["target"].to_numpy(dtype=float)
    index = frame.index

    for i in range(len(frame)):
        # 1. Execute a signal generated on the previous bar at today's open.
        if pending is not None and position is None and not np.isnan(pending["stop"]):
            fill = config.costs.slippage(opens[i], "BUY")
            risk_per_share = fill - pending["stop"]
            if risk_per_share > 0:
                risk_amount = cash * config.risk_per_trade_pct / 100.0
                qty = int(risk_amount / risk_per_share)
                max_value = cash * config.max_position_pct / 100.0
                qty = min(qty, int(max_value / fill))
                liq = config.liquidity.check(qty, fill, int(volumes[i])) if qty else {}
                if qty > 0 and liq.get("within_liquidity", True):
                    buy_charges = config.costs.charges(qty * fill, "BUY")["total"]
                    position = Trade(
                        symbol=series.symbol,
                        entry_date=index[i],
                        entry_price=fill,
                        exit_date=None,
                        exit_price=None,
                        quantity=qty,
                        stop_loss=float(pending["stop"]),
                        target=float(pending["target"]),
                        costs=buy_charges,
                        slippage=abs(fill - opens[i]) * qty,
                    )
                    # Cash actually leaves the account on the fill; without this
                    # the equity curve double-counts the open position.
                    cash -= qty * fill + buy_charges
                    pending = None
                elif qty > 0:
                    warnings.append(
                        f"{index[i].date()}: order skipped — {qty} shares exceeded "
                        f"{config.liquidity.max_pct_of_bar_volume}% of bar volume."
                    )
                    pending = None
            else:
                pending = None

        # 2. Manage an open position intrabar. Stop is assumed to fill first
        #    when a bar spans both stop and target (conservative).
        if position is not None:
            bars_in_market += 1
            exit_price: float | None = None
            reason = ""
            if lows[i] <= position.stop_loss:
                exit_price, reason = position.stop_loss, "stop"
            elif highs[i] >= position.target:
                exit_price, reason = position.target, "target"
            elif (
                config.max_bars_in_trade
                and (i - index.get_loc(position.entry_date)) >= config.max_bars_in_trade
            ):
                exit_price, reason = closes[i], "time"
            if exit_price is not None:
                fill = config.costs.slippage(exit_price, "SELL")
                sell_charges = config.costs.charges(position.quantity * fill, "SELL")["total"]
                position.exit_date = index[i]
                position.exit_price = fill
                position.costs += sell_charges
                position.slippage += abs(fill - exit_price) * position.quantity
                gross = (fill - position.entry_price) * position.quantity
                position.pnl = gross - position.costs
                position.pnl_pct = (
                    (fill / position.entry_price - 1) * 100 if position.entry_price else 0.0
                )
                per_share_risk = position.entry_price - position.stop_loss
                position.r_multiple = (
                    (fill - position.entry_price - position.costs / position.quantity)
                    / per_share_risk
                    if per_share_risk > 0 and position.quantity
                    else 0.0
                )
                position.bars_held = int(np.busday_count(
                    position.entry_date.date(), index[i].date()
                ))
                position.exit_reason = reason
                cash += position.quantity * fill - sell_charges
                trades.append(position)
                position = None

        # 3. Record equity and queue tomorrow's signal.
        mark = position.quantity * closes[i] if position is not None else 0.0
        equity_points.append(cash + mark)
        equity_index.append(index[i])
        if position is None and entry_flags[i] and not np.isnan(stops[i]) and not np.isnan(targets[i]):
            pending = {"stop": float(stops[i]), "target": float(targets[i]),
                       "signal_date": index[i]}

    equity = pd.Series(equity_points, index=pd.DatetimeIndex(equity_index), name="equity")
    # Force-close at the end so trade statistics are complete and honest.
    if position is not None:
        last_fill = closes[-1]
        sell_charges = config.costs.charges(position.quantity * last_fill, "SELL")["total"]
        position.exit_date = index[-1]
        position.exit_price = last_fill
        position.costs += sell_charges
        gross = (last_fill - position.entry_price) * position.quantity
        position.pnl = gross - position.costs
        position.pnl_pct = (last_fill / position.entry_price - 1) * 100
        per_share_risk = position.entry_price - position.stop_loss
        position.r_multiple = (
            (last_fill - position.entry_price - position.costs / position.quantity)
            / per_share_risk
            if per_share_risk > 0 and position.quantity
            else 0.0
        )
        position.exit_reason = "end_of_data"
        trades.append(position)
        equity.iloc[-1] = cash + position.quantity * last_fill - sell_charges
        warnings.append("Open position closed at the last bar (end_of_data).")

    exposure = bars_in_market / max(len(frame), 1)
    metrics = _metrics(equity, trades, config.initial_capital, exposure)
    return BacktestResult(
        symbol=series.symbol,
        strategy=strategy_name,
        trades=trades,
        equity_curve=equity,
        daily_returns=equity.pct_change().dropna(),
        metrics=metrics,
        config=config,
        warnings=warnings,
        assumptions={
            "execution": "signal on bar t, filled at open of bar t+1",
            "intrabar_priority": "stop before target when both are touched",
            "costs": {
                "segment": config.costs.segment,
                "slippage_bps_per_side": config.costs.slippage_bps,
                "stt_delivery_pct": 0.10,
                "brokerage_delivery_pct": 0.03,
            },
            "sizing": f"risk {config.risk_per_trade_pct}% of current equity per trade",
            "data_source": series.meta.source,
            "data_freshness": series.meta.freshness.value,
            "is_synthetic_data": series.meta.is_synthetic,
            "shorting_allowed": False,
        },
    )


def compare(results: list[BacktestResult]) -> list[dict[str, object]]:
    """Side-by-side comparison table, sorted by risk-adjusted return."""
    rows = []
    for r in results:
        rows.append(
            {
                "strategy": r.strategy,
                "symbol": r.symbol,
                "cagr_pct": r.metrics.get("cagr_pct"),
                "max_drawdown_pct": r.metrics.get("max_drawdown_pct"),
                "sharpe": r.metrics.get("sharpe"),
                "profit_factor": r.metrics.get("profit_factor"),
                "win_rate_pct": r.metrics.get("win_rate_pct"),
                "trades": r.metrics.get("trades"),
                "expectancy": r.metrics.get("expectancy_per_trade"),
                "cost_drag_pct": r.metrics.get("cost_drag_pct_of_capital"),
            }
        )
    return sorted(rows, key=lambda r: (r["sharpe"] or -99), reverse=True)


@dataclass
class WalkForwardFold:
    label: str
    start: str
    end: str
    metrics: dict[str, float]


def walk_forward(
    series: Series,
    signal_fn: SignalFn,
    config: BacktestConfig | None = None,
    folds: int = 4,
    strategy_name: str = "unnamed",
) -> dict[str, object]:
    """Split the sample into sequential folds and report each separately.

    This is *stability* evidence, not optimisation: a strategy whose edge only
    appears in one fold should not be trusted. Parameters are not re-tuned
    inside the folds, which avoids the usual overfitting trap at the cost of
    not being a true walk-forward optimisation.
    """
    config = config or BacktestConfig()
    frame = series.frame
    n = len(frame)
    if folds < 2 or n < folds * (config.warmup_bars + 20):
        return {
            "available": False,
            "reason": (
                f"Need at least {folds * (config.warmup_bars + 20)} bars for "
                f"{folds} folds; have {n}."
            ),
            "folds": [],
        }
    size = n // folds
    out: list[WalkForwardFold] = []
    for k in range(folds):
        start = max(0, k * size - config.warmup_bars)
        end = (k + 1) * size if k < folds - 1 else n
        window = frame.iloc[start:end]
        sub = Series(
            symbol=series.symbol,
            frame=window,
            meta=series.meta,
            timeframe=series.timeframe,
        )
        result = run_backtest(sub, signal_fn, config, strategy_name)
        out.append(
            WalkForwardFold(
                label=f"fold_{k + 1}",
                start=window.index[0].date().isoformat(),
                end=window.index[-1].date().isoformat(),
                metrics=result.metrics,
            )
        )
    sharpes = [f.metrics.get("sharpe", 0.0) for f in out]
    positive = sum(1 for s in sharpes if s > 0)
    return {
        "available": True,
        "folds": [
            {"label": f.label, "start": f.start, "end": f.end, "metrics": f.metrics} for f in out
        ],
        "stability": {
            "positive_folds": positive,
            "total_folds": len(out),
            "sharpe_range": [round(min(sharpes), 2), round(max(sharpes), 2)],
            "verdict": (
                "consistent"
                if positive == len(out)
                else "mixed"
                if positive * 2 >= len(out)
                else "fragile"
            ),
            "note": (
                "Sequential folds with fixed parameters (no re-optimisation). "
                "Fewer than two positive folds is not evidence of an edge."
            ),
        },
    }


def train_test_split_backtest(
    series: Series,
    signal_fn: SignalFn,
    config: BacktestConfig | None = None,
    train_pct: float = 0.7,
    strategy_name: str = "unnamed",
) -> dict[str, object]:
    """In-sample vs out-of-sample comparison with a single fixed split."""
    config = config or BacktestConfig()
    n = len(series.frame)
    split = int(n * train_pct)
    train = Series(series.symbol, series.frame.iloc[:split], series.meta, series.timeframe)
    test = Series(series.symbol, series.frame.iloc[split:], series.meta, series.timeframe)
    r_train = run_backtest(train, signal_fn, config, strategy_name)
    r_test = run_backtest(test, signal_fn, config, strategy_name)
    degradation = (r_train.metrics.get("sharpe", 0) or 0) - (r_test.metrics.get("sharpe", 0) or 0)
    return {
        "train": {"period": [train.frame.index[0].date().isoformat(),
                             train.frame.index[-1].date().isoformat()],
                  "metrics": r_train.metrics},
        "test": {"period": [test.frame.index[0].date().isoformat(),
                            test.frame.index[-1].date().isoformat()],
                 "metrics": r_test.metrics},
        "sharpe_degradation": round(degradation, 2),
        "note": (
            "Out-of-sample Sharpe far below in-sample Sharpe is the normal "
            "signature of an overfitted strategy."
        ),
    }
