"""AGENT 13 — Portfolio Manager.

Analyses imported holdings: allocation, sector concentration, overlap,
unrealised P&L, portfolio volatility/beta against the index, and risk
concentration. Reports; never rebalances. Rebalancing is a simulation the user
can inspect, never an automatic action.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import risk_limits_from
from backend.analytics import indicators as ind
from backend.analytics.risk import (
    Holding,
    beta_to_benchmark,
    check_exposure,
    portfolio_volatility,
    sector_exposure,
    value_at_risk,
)
from backend.core.provenance import Freshness, Verification


class PortfolioManagerAgent(BaseAgent):
    name = "portfolio_manager"
    responsibility = "Holdings analysis, concentration and portfolio risk"
    requires = ("portfolio", "prices")

    def run(self, ctx: AgentContext) -> AgentFinding:
        limits = risk_limits_from(ctx)
        store = ctx.cache.get("journal_store")
        rows = store.list_holdings() if store is not None else []
        if not rows:
            return AgentFinding(
                agent=self.name,
                symbol=None,
                headline="No portfolio imported",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=[
                    "Import holdings as CSV/XLSX via POST /api/portfolio/import to enable "
                    "portfolio-level analysis. Nothing is inferred without data."
                ],
                data_quality={"score": 0, "band": "VERY_LOW"},
                metrics={"holdings": [], "total_value": 0.0},
            )

        holdings: list[Holding] = []
        returns_map: dict[str, pd.Series] = {}
        warnings: list[str] = []
        synthetic_any = False
        for row in rows:
            symbol = str(row["symbol"]).upper()
            try:
                res = ctx.registry.quote(symbol)
                price = float(res.value.last_price)
                hist = ctx.registry.history(symbol, lookback=260).value
                returns_map[symbol] = hist.frame["close"].pct_change()
                synthetic_any = synthetic_any or hist.meta.is_synthetic
            except Exception as exc:  # noqa: BLE001
                price = float(row["avg_price"])
                warnings.append(f"{symbol}: price unavailable ({exc}); valued at cost.")
            holdings.append(
                Holding(
                    symbol=symbol,
                    quantity=float(row["quantity"]),
                    avg_price=float(row["avg_price"]),
                    last_price=price,
                    sector=row.get("sector") or "Unknown",
                    name=row.get("name"),
                )
            )

        exposure = check_exposure(holdings, limits)
        total = float(exposure["total_value"])
        weights = [h.value / total for h in holdings] if total else []

        # ---------------------------------------------------------- risk maths
        vol = 0.0
        beta = None
        var = {"var_pct": 0.0, "cvar_pct": 0.0}
        if len(returns_map) >= 2:
            frame = pd.DataFrame(returns_map).dropna(how="all").fillna(0.0)
            vol = portfolio_volatility(frame, weights)
            port_ret = (frame * pd.Series(weights, index=frame.columns)).sum(axis=1)
            var = value_at_risk(port_ret)
            try:
                bench = ctx.registry.index_history("NIFTY 50", lookback=300).value.frame["close"]
                beta = beta_to_benchmark(port_ret, bench.pct_change())
            except Exception:  # noqa: BLE001
                beta = None
        elif holdings:
            # Single-stock portfolio: use its own volatility.
            only = next(iter(returns_map.values()), None)
            if only is not None:
                vol = float(only.std(ddof=0) * np.sqrt(252))
                var = value_at_risk(only)
        if vol == 0.0:
            warnings.append(
                "Portfolio volatility could not be estimated (insufficient overlapping history)."
            )

        score = 0.0
        if exposure["breaches"]:
            score -= 12 * len(exposure["breaches"])
        conc = exposure.get("concentration", {})
        effective = conc.get("effective_holdings", 0.0)
        if effective and effective < 5:
            score -= 12
            warnings.append(
                f"Only {effective} effective holdings: the portfolio behaves like a "
                "concentrated bet, not a diversified basket."
            )
        sectors = exposure.get("sector_exposure", [])
        if sectors and sectors[0]["weight_pct"] > 35:
            score -= 10
            warnings.append(
                f"Largest sector {sectors[0]['sector']} at {sectors[0]['weight_pct']}%."
            )
        if vol > 0.30:
            score -= 8
            warnings.append(f"Annualised volatility {vol * 100:.0f}% is high.")

        unrealised = float(exposure.get("unrealised_pnl", 0.0))
        invested = float(exposure.get("invested", 0.0))
        evidence = [
            Evidence(
                claim=(
                    f"Portfolio value INR {total:,.0f}; invested INR {invested:,.0f}; "
                    f"unrealised P&L INR {unrealised:,.0f}"
                ),
                value=total,
                source="holdings import",
                freshness=Freshness.SYNTHETIC if synthetic_any else Freshness.DELAYED,
                verification=Verification.UNVERIFIED_SYNTHETIC
                if synthetic_any
                else Verification.CROSS_CHECKED,
                is_synthetic=synthetic_any,
            ),
            Evidence(
                claim=(
                    f"Estimated annualised volatility {vol * 100:.1f}%, beta "
                    f"{'n/a' if beta is None else f'{beta:.2f}'}, 1-day 95% VaR "
                    f"{var['var_pct']:.2f}%"
                ),
                value=vol,
                source="computed from price history",
                freshness=Freshness.SYNTHETIC if synthetic_any else Freshness.EOD,
                verification=Verification.UNVERIFIED_SYNTHETIC
                if synthetic_any
                else Verification.CROSS_CHECKED,
                is_synthetic=synthetic_any,
            ),
        ]

        rebalance = self._rebalance_simulation(holdings, limits)

        return AgentFinding(
            agent=self.name,
            symbol=None,
            headline=(
                f"{len(holdings)} holdings, INR {total:,.0f} value, "
                f"{conc.get('effective_holdings', 0)} effective holdings, "
                f"vol {vol * 100:.0f}%"
            ),
            stance="BEARISH" if score <= -20 else "NEUTRAL",
            score=float(np.clip(score, -100, 0)),
            confidence=0.6 if not synthetic_any else 0.4,
            evidence=evidence,
            risks=exposure["breaches"] + warnings,
            limitations=[
                "Sector labels come from the platform universe; unlisted or unsupported "
                "symbols are grouped as Unknown.",
                "Overlap with mutual funds is not assessed: fund holdings are not ingested.",
                "Realised P&L requires transaction history, not just current holdings.",
            ]
            + (["Prices are synthetic demonstration data."] if synthetic_any else []),
            data_quality={"score": 55 if synthetic_any else 80,
                          "band": "LOW" if synthetic_any else "HIGH"},
            metrics={
                "holdings": [
                    {
                        "symbol": h.symbol,
                        "quantity": h.quantity,
                        "avg_price": round(h.avg_price, 2),
                        "last_price": round(h.last_price, 2),
                        "value": round(h.value, 2),
                        "weight_pct": round(h.value / total * 100, 2) if total else 0.0,
                        "pnl": round(h.pnl, 2),
                        "pnl_pct": round(h.pnl_pct, 2),
                        "sector": h.sector,
                    }
                    for h in holdings
                ],
                "exposure": exposure,
                "sector_exposure": sector_exposure(holdings),
                "volatility_pct": round(vol * 100, 2),
                "beta": beta,
                "value_at_risk": var,
                "rebalance_simulation": rebalance,
                "limits": {
                    "max_single_stock_pct": limits.max_single_stock_pct,
                    "max_sector_pct": limits.max_sector_pct,
                },
            },
            warnings=warnings + [
                "No rebalancing action is taken by this platform. The simulation above is "
                "for review only."
            ],
        )

    def _rebalance_simulation(self, holdings: list[Holding], limits) -> dict[str, Any]:
        """Equal-weight simulation, shown only as a comparison."""
        total = sum(h.value for h in holdings)
        if total <= 0 or len(holdings) < 2:
            return {"available": False, "reason": "need at least two valued holdings"}
        target = total / len(holdings)
        moves = []
        for h in holdings:
            delta_value = target - h.value
            delta_qty = delta_value / h.last_price if h.last_price else 0
            moves.append(
                {
                    "symbol": h.symbol,
                    "current_pct": round(h.value / total * 100, 2),
                    "target_pct": round(100 / len(holdings), 2),
                    "delta_value": round(delta_value, 2),
                    "delta_quantity": round(delta_qty, 2),
                }
            )
        return {
            "available": True,
            "method": "equal weight",
            "moves": sorted(moves, key=lambda m: -abs(m["delta_value"])),
            "note": (
                "Simulation only. The platform never executes rebalancing trades. "
                "Equal weighting ignores valuation, conviction and tax consequences."
            ),
        }
