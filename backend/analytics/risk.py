"""Risk management: sizing, validation, portfolio exposure and statistics.

This module has no dependency on any other agent and no ability to place an
order. It answers one question: *given a stated hypothesis, how much capital may
be put at risk, and is this proposal internally consistent?*

Hard rules (configurable in settings, but never silently overridden):

* Risk per trade must not exceed ``max_position_risk_pct`` of capital.
* Reward-to-risk must be at least ``min_reward_risk``.
* Portfolio "heat" (sum of open risk) must not exceed
  ``max_portfolio_heat_pct``.
* A single stock must not exceed ``max_single_stock_pct`` of portfolio value.
* A single sector must not exceed ``max_sector_pct``.
* A stop-loss must be on the correct side of entry.
* Position size must be affordable given available capital.

Rejections are final. :class:`RiskDecision.overridable` is always False.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Literal

import numpy as np
import pandas as pd

Side = Literal["LONG", "SHORT"]


# --------------------------------------------------------------- primitives

@dataclass
class RiskLimits:
    capital: float = 20_000.0
    max_position_risk_pct: float = 2.0
    max_portfolio_heat_pct: float = 6.0
    max_single_stock_pct: float = 15.0
    max_sector_pct: float = 35.0
    daily_loss_limit_pct: float = 3.0
    min_reward_risk: float = 1.5
    max_leverage: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return self.__dict__.copy()


@dataclass
class TradeProposal:
    symbol: str
    side: Side
    entry: float
    stop_loss: float
    target: float
    sector: str = "Unknown"
    atr: float | None = None
    strategy: str = "unspecified"
    rationale: str = ""
    is_fno: bool = False


@dataclass
class RiskDecision:
    approved: bool
    symbol: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk_per_share: float = 0.0
    reward_per_share: float = 0.0
    reward_risk: float | None = None
    quantity: int = 0
    position_value: float = 0.0
    risk_amount: float = 0.0
    risk_pct_capital: float = 0.0
    portfolio_heat_pct: float = 0.0
    stop_distance_pct: float = 0.0
    suggested_stop: float | None = None
    sizing_method: str = "risk-based"
    overridable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "approved": self.approved,
            "symbol": self.symbol,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "reward_risk": self.reward_risk,
            "quantity": self.quantity,
            "position_value": round(self.position_value, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct_capital": round(self.risk_pct_capital, 3),
            "portfolio_heat_pct": round(self.portfolio_heat_pct, 3),
            "stop_distance_pct": round(self.stop_distance_pct, 3),
            "suggested_stop": self.suggested_stop,
            "sizing_method": self.sizing_method,
            "overridable": self.overridable,
            "disclaimer": (
                "Risk approval is a controls check, not a recommendation and not "
                "authorisation to trade. No order is placed by this platform."
            ),
        }


# ------------------------------------------------------------------ sizing

def risk_based_sizing(
    capital: float,
    entry: float,
    stop_loss: float,
    risk_pct: float,
    *,
    max_position_pct: float | None = None,
    lot_size: int = 1,
) -> tuple[int, dict[str, float]]:
    """Fixed-fractional sizing: the number of shares that loses exactly
    ``risk_pct`` of capital if the stop is hit.

    Returns ``(quantity, detail)``. Quantity is a lot multiple, floor-rounded, so
    it is always tradeable.
    """
    risk_per_share = abs(entry - stop_loss)
    risk_amount = capital * risk_pct / 100.0
    if risk_per_share <= 0 or entry <= 0:
        return 0, {"risk_per_share": 0.0, "risk_amount": risk_amount, "note": "invalid stop"}
    raw_qty = risk_amount / risk_per_share
    if max_position_pct:
        cap = capital * max_position_pct / 100.0 / entry
        raw_qty = min(raw_qty, cap)
    lots = int(raw_qty // lot_size)
    qty = lots * lot_size
    return qty, {
        "risk_per_share": round(risk_per_share, 2),
        "risk_amount": round(risk_amount, 2),
        "raw_quantity": round(raw_qty, 2),
        "position_value": round(qty * entry, 2),
        "capped_by": "position value limit" if max_position_pct else "none",
    }


def atr_based_sizing(
    capital: float, entry: float, atr: float, risk_pct: float, atr_multiple: float = 2.0
) -> tuple[float, int]:
    """ATR stop distance -> quantity. Returns ``(stop_price, quantity)``."""
    stop_distance = max(atr * atr_multiple, entry * 0.005)
    stop = entry - stop_distance
    qty, _ = risk_based_sizing(capital, entry, stop, risk_pct)
    return round(stop, 2), qty


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly fraction, capped at 25% (half-Kelly discipline for real use).

    Returns 0 when the edge is negative or the inputs are unusable.
    """
    if avg_loss <= 0 or not 0 < win_rate < 1:
        return 0.0
    payoff = avg_win / avg_loss
    if payoff <= 0:
        return 0.0
    kelly = win_rate - (1 - win_rate) / payoff
    return float(max(0.0, min(kelly, 0.25)))


def volatility_targeted_size(
    capital: float, entry: float, annual_vol: float, target_portfolio_vol: float = 0.15
) -> int:
    """Scale exposure so the position contributes at most the target volatility."""
    if entry <= 0 or annual_vol <= 0:
        return 0
    weight = min(1.0, target_portfolio_vol / annual_vol)
    return int((capital * weight) // entry)


# ------------------------------------------------------------- validation

def validate_proposal(
    proposal: TradeProposal, limits: RiskLimits, *, open_risk_pct: float = 0.0
) -> RiskDecision:
    """The single place where a trade proposal is accepted or rejected."""
    reasons: list[str] = []
    warnings: list[str] = []

    if proposal.is_fno:
        return RiskDecision(
            approved=False,
            symbol=proposal.symbol,
            reasons=[
                "F&O trading is disabled in this build (FNO_ENABLED = FALSE). "
                "Options research is available; ordering is not."
            ],
        )
    if proposal.entry <= 0 or proposal.stop_loss <= 0 or proposal.target <= 0:
        return RiskDecision(
            approved=False,
            symbol=proposal.symbol,
            reasons=["Entry, stop-loss and target must all be positive prices."],
        )
    if proposal.side == "LONG":
        if proposal.stop_loss >= proposal.entry:
            reasons.append(
                f"Long stop ({proposal.stop_loss:.2f}) must be below entry "
                f"({proposal.entry:.2f})."
            )
        if proposal.target <= proposal.entry:
            reasons.append(
                f"Long target ({proposal.target:.2f}) must be above entry "
                f"({proposal.entry:.2f})."
            )
    else:
        if proposal.stop_loss <= proposal.entry:
            reasons.append(
                f"Short stop ({proposal.stop_loss:.2f}) must be above entry "
                f"({proposal.entry:.2f})."
            )
        if proposal.target >= proposal.entry:
            reasons.append(
                f"Short target ({proposal.target:.2f}) must be below entry "
                f"({proposal.entry:.2f})."
            )
    if reasons:
        return RiskDecision(False, proposal.symbol, reasons=reasons)

    risk_per_share = abs(proposal.entry - proposal.stop_loss)
    reward_per_share = abs(proposal.target - proposal.entry)
    rr = reward_per_share / risk_per_share if risk_per_share else None
    # Compare on the rounded value so a 1.4999996 ratio does not read as "1.50
    # is below 1.50" in the rejection message.
    rr = None if rr is None else round(rr, 2)
    stop_distance_pct = risk_per_share / proposal.entry * 100

    if rr is None or rr < limits.min_reward_risk - 1e-9:
        reasons.append(
            f"Reward-to-risk of {0.0 if rr is None else rr:.2f} is below the "
            f"{limits.min_reward_risk:.2f} minimum."
        )
    if rr is not None and rr > 20:
        warnings.append(
            f"Reward-to-risk of {rr:.1f} implies a target far outside the setup's "
            "range. Check that the target is a realistic structure level, not a "
            "round number chosen to satisfy the ratio."
        )
    if stop_distance_pct > 12:
        warnings.append(
            f"Stop is {stop_distance_pct:.1f}% away from entry, which is wide for a "
            "single trade; consider a tighter, structure-based invalidation."
        )
    if stop_distance_pct < 0.4:
        warnings.append(
            f"Stop is only {stop_distance_pct:.2f}% away — inside typical noise and "
            "likely to be hit by spread or slippage."
        )
    if proposal.atr and risk_per_share < 0.8 * proposal.atr:
        warnings.append(
            f"Stop distance ({risk_per_share:.2f}) is less than 0.8x ATR "
            f"({proposal.atr:.2f}); random noise can stop this trade out."
        )

    qty, detail = risk_based_sizing(
        limits.capital,
        proposal.entry,
        proposal.stop_loss,
        limits.max_position_risk_pct,
        max_position_pct=limits.max_single_stock_pct,
    )
    position_value = qty * proposal.entry
    risk_amount = qty * risk_per_share
    risk_pct = risk_amount / limits.capital * 100
    heat = open_risk_pct + risk_pct

    if qty <= 0:
        reasons.append(
            "Position size rounds to zero at the permitted risk; the stop distance "
            "is too large relative to capital for a tradeable size."
        )
    if position_value > limits.capital * limits.max_leverage:
        reasons.append("Position value exceeds available capital (leverage not allowed).")
    if heat > limits.max_portfolio_heat_pct:
        reasons.append(
            f"Adding this trade takes portfolio heat to {heat:.2f}%, above the "
            f"{limits.max_portfolio_heat_pct:.2f}% limit."
        )
    if limits.capital <= 0:
        reasons.append("Capital must be positive.")

    return RiskDecision(
        approved=not reasons,
        symbol=proposal.symbol,
        reasons=reasons,
        warnings=warnings,
        risk_per_share=round(risk_per_share, 2),
        reward_per_share=round(reward_per_share, 2),
        reward_risk=None if rr is None else round(rr, 2),
        quantity=qty,
        position_value=round(position_value, 2),
        risk_amount=round(risk_amount, 2),
        risk_pct_capital=round(risk_pct, 3),
        portfolio_heat_pct=round(heat, 3),
        stop_distance_pct=round(stop_distance_pct, 2),
        suggested_stop=round(proposal.stop_loss, 2),
    )


# ------------------------------------------------------- portfolio exposure

@dataclass
class Holding:
    symbol: str
    quantity: float
    avg_price: float
    last_price: float
    sector: str = "Unknown"
    name: str | None = None

    @property
    def value(self) -> float:
        return self.quantity * self.last_price

    @property
    def invested(self) -> float:
        return self.quantity * self.avg_price

    @property
    def pnl(self) -> float:
        return self.value - self.invested

    @property
    def pnl_pct(self) -> float:
        return (self.last_price / self.avg_price - 1) * 100 if self.avg_price else 0.0


def concentration(weights: Iterable[float]) -> dict[str, float]:
    """HHI and effective number of holdings from a weight vector."""
    w = np.array([x for x in weights if x > 0], dtype=float)
    if w.size == 0:
        return {"hhi": 0.0, "effective_holdings": 0.0, "top_weight_pct": 0.0}
    w = w / w.sum()
    hhi = float(np.sum(w**2))
    return {
        "hhi": round(hhi, 4),
        "effective_holdings": round(1 / hhi, 1) if hhi else 0.0,
        "top_weight_pct": round(float(w.max()) * 100, 2),
    }


def sector_exposure(holdings: list[Holding]) -> list[dict[str, float | str]]:
    total = sum(h.value for h in holdings)
    buckets: dict[str, float] = {}
    for h in holdings:
        buckets[h.sector] = buckets.get(h.sector, 0.0) + h.value
    rows = [
        {
            "sector": sector,
            "value": round(value, 2),
            "weight_pct": round(value / total * 100, 2) if total else 0.0,
        }
        for sector, value in buckets.items()
    ]
    return sorted(rows, key=lambda r: r["weight_pct"], reverse=True)  # type: ignore[arg-type]


def check_exposure(
    holdings: list[Holding], limits: RiskLimits
) -> dict[str, object]:
    """Flag concentration and sector-limit breaches. Reports, never auto-trades."""
    total = sum(h.value for h in holdings)
    breaches: list[str] = []
    if total <= 0:
        return {"total_value": 0.0, "breaches": ["Portfolio has no market value."],
                "sector_exposure": [], "single_stock": [], "concentration": {}}
    single = [
        {
            "symbol": h.symbol,
            "weight_pct": round(h.value / total * 100, 2),
            "value": round(h.value, 2),
        }
        for h in holdings
    ]
    single.sort(key=lambda r: r["weight_pct"], reverse=True)
    for row in single:
        if row["weight_pct"] > limits.max_single_stock_pct:
            breaches.append(
                f"{row['symbol']} is {row['weight_pct']:.1f}% of the portfolio "
                f"(limit {limits.max_single_stock_pct:.0f}%)."
            )
    sectors = sector_exposure(holdings)
    for row in sectors:
        if row["weight_pct"] > limits.max_sector_pct:  # type: ignore[operator]
            breaches.append(
                f"{row['sector']} is {row['weight_pct']:.1f}% of the portfolio "
                f"(limit {limits.max_sector_pct:.0f}%)."
            )
    return {
        "total_value": round(total, 2),
        "invested": round(sum(h.invested for h in holdings), 2),
        "unrealised_pnl": round(sum(h.pnl for h in holdings), 2),
        "breaches": breaches,
        "sector_exposure": sectors,
        "single_stock": single,
        "concentration": concentration([h.value for h in holdings]),
    }


# ---------------------------------------------------------------- statistics

def value_at_risk(returns: pd.Series, confidence: float = 0.95, horizon_days: int = 1) -> dict[str, float]:
    """Historical-simulation VaR and Expected Shortfall (CVaR), as positive loss %."""
    clean = returns.dropna()
    if len(clean) < 60:
        return {"var_pct": 0.0, "cvar_pct": 0.0, "confidence": confidence,
                "note": "insufficient observations (need 60+)"}
    scaled = clean * math.sqrt(horizon_days)
    var = float(np.percentile(scaled, (1 - confidence) * 100))
    tail = scaled[scaled <= var]
    cvar = float(tail.mean()) if len(tail) else var
    return {
        "var_pct": round(-var * 100, 2),
        "cvar_pct": round(-cvar * 100, 2),
        "confidence": confidence,
        "horizon_days": horizon_days,
        "observations": int(len(clean)),
        "note": "Historical simulation on the available sample; not a guarantee.",
    }


def portfolio_volatility(returns: pd.DataFrame, weights: list[float]) -> float:
    """Annualised portfolio volatility from a returns matrix and weights."""
    if returns.empty:
        return 0.0
    w = np.array(weights, dtype=float)
    if len(w) != returns.shape[1] or w.sum() == 0:
        return 0.0
    w = w / w.sum()
    cov = returns.cov().to_numpy() * 252
    return float(math.sqrt(max(0.0, float(w @ cov @ w))))


def beta_to_benchmark(asset: pd.Series, benchmark: pd.Series) -> float | None:
    aligned = pd.concat([asset, benchmark], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return None
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    if cov[1, 1] == 0:
        return None
    return round(float(cov[0, 1] / cov[1, 1]), 3)


def daily_loss_check(day_pnl: float, capital: float, limits: RiskLimits) -> dict[str, object]:
    limit_amount = capital * limits.daily_loss_limit_pct / 100
    breached = day_pnl < -limit_amount
    return {
        "day_pnl": round(day_pnl, 2),
        "limit_amount": round(limit_amount, 2),
        "breached": breached,
        "message": (
            f"Daily loss limit breached ({day_pnl:,.0f} vs limit -{limit_amount:,.0f}). "
            "Stop trading and review. This platform will not place or cancel orders."
            if breached
            else "Daily loss within limit."
        ),
    }
