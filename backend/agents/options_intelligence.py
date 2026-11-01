"""AGENT 07 — Options Intelligence (research only).

Analyses the option chain: OI structure, change in OI, PCR, IV skew, max pain,
expected move, greeks and strategy payoffs. F&O ordering is disabled in this
build (``FNO_ENABLED = FALSE``) and the risk agent rejects any F&O proposal.

Payoff construction is exact (piecewise-linear accounting for premiums and lot
size), and breakevens are solved rather than eyeballed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.analytics import indicators as ind
from backend.core.provenance import Freshness, Verification
from backend.data.universe import get_instrument


@dataclass
class Leg:
    action: str  # BUY | SELL
    kind: str  # CE | PE
    strike: float
    premium: float
    quantity: int = 1


def payoff_at(legs: list[Leg], spot: float, lot_size: int = 1) -> float:
    """Net P&L of the structure at expiry for a given spot."""
    total = 0.0
    for leg in legs:
        intrinsic = max(spot - leg.strike, 0.0) if leg.kind == "CE" else max(leg.strike - spot, 0.0)
        value = intrinsic - leg.premium
        sign = 1 if leg.action == "BUY" else -1
        total += sign * value * leg.quantity * lot_size
    return round(total, 2)


def research_margin_estimate(legs: list[Leg], spot: float, lot_size: int = 1) -> dict[str, Any]:
    """Return a conservative, explicitly non-broker margin estimate.

    This is deliberately not called SPAN.  It stress-tests expiry P&L at a wide
    set of underlying prices and adds a 20% spot notional buffer for short
    options.  Long-only structures are funded by their premium at risk.  The
    result is useful for research sizing while remaining honest that an exchange
    or broker may require a different amount.
    """
    contracts = sum(leg.quantity for leg in legs)
    short_notional = sum(
        leg.quantity * lot_size * spot for leg in legs if leg.action == "SELL"
    )
    stress_spots = [spot * x for x in (0.50, 0.70, 0.85, 1.00, 1.15, 1.30, 1.50)]
    worst_loss = min(payoff_at(legs, s, lot_size) for s in stress_spots)
    premium_at_risk = sum(
        leg.premium * leg.quantity * lot_size for leg in legs if leg.action == "BUY"
    )
    # A long option's premium is the cash at risk; short options receive a
    # premium but need a stress buffer for adverse moves.
    estimate = max(premium_at_risk, max(0.0, -worst_loss) + short_notional * 0.20)
    # Only net short call exposure is mathematically unbounded on the upside.
    # A short call paired with a long call is a defined-risk spread. Put losses
    # are finite at expiry because the underlying cannot fall below zero.
    net_call_contracts = sum(
        (1 if leg.action == "BUY" else -1) * leg.quantity
        for leg in legs if leg.kind == "CE"
    )
    unbounded_short_call = net_call_contracts < 0
    return {
        "estimated_margin": round(estimate, 2),
        "method": "expiry stress grid + 20% short-option spot-notional buffer",
        "stress_spots": [round(s, 2) for s in stress_spots],
        "worst_stress_pnl": round(worst_loss, 2),
        "premium_at_risk": round(premium_at_risk, 2),
        "short_option_notional": round(short_notional, 2),
        "unbounded_risk": unbounded_short_call,
        "warning": (
            "Research estimate only; not exchange SPAN/Exposure margin. "
            "Broker requirements, volatility scans, liquidity add-ons, "
            "calendar spreads and intraday revisions are not modelled."
        ),
        "contracts": contracts,
    }


def structure_summary(legs: list[Leg], spot: float, lot_size: int = 1, points: int = 81) -> dict[str, Any]:
    grid = np.linspace(spot * 0.75, spot * 1.25, points)
    pnls = [payoff_at(legs, float(s), lot_size) for s in grid]
    net_premium = sum(
        (1 if leg.action == "BUY" else -1) * leg.premium * leg.quantity * lot_size for leg in legs
    )
    # Breakevens: sign changes in the payoff curve.
    breakevens: list[float] = []
    for i in range(len(grid) - 1):
        if pnls[i] == 0:
            breakevens.append(round(float(grid[i]), 2))
        elif pnls[i] * pnls[i + 1] < 0:
            x0, x1 = grid[i], grid[i + 1]
            y0, y1 = pnls[i], pnls[i + 1]
            breakevens.append(round(float(x0 - y0 * (x1 - x0) / (y1 - y0)), 2))
    max_profit = max(pnls)
    max_loss = min(pnls)
    unbounded_profit = any(leg.action == "BUY" and leg.kind == "CE" for leg in legs)
    unbounded_loss = any(leg.action == "SELL" and leg.kind == "CE" for leg in legs)
    return {
        "net_premium": round(net_premium, 2),
        "max_profit": "unlimited" if unbounded_profit and max_profit == pnls[-1] else round(max_profit, 2),
        "max_loss": "unlimited" if unbounded_loss and max_loss == pnls[-1] else round(max_loss, 2),
        "breakevens": sorted(set(breakevens)),
        "payoff_curve": [
            {"spot": round(float(s), 2), "pnl": p} for s, p in zip(grid, pnls)
        ][:: max(1, points // 25)],
        "lot_size": lot_size,
        "margin_estimate": research_margin_estimate(legs, spot, lot_size),
        "legs": [
            {
                "action": leg.action,
                "kind": leg.kind,
                "strike": leg.strike,
                "premium": leg.premium,
                "quantity": leg.quantity,
            }
            for leg in legs
        ],
    }


class OptionsIntelligenceAgent(BaseAgent):
    name = "options"
    responsibility = "Option chain, greeks, OI, PCR, max pain and payoff research"
    requires = ("option_chain",)

    def run(self, ctx: AgentContext) -> AgentFinding:
        symbol = (ctx.symbol or "").upper()
        instrument = get_instrument(symbol)
        limitations = [
            "Research only. F&O ordering is disabled in this build (FNO_ENABLED = FALSE); "
            "the risk agent rejects any F&O proposal.",
            "Margin is a conservative stress-based research estimate, not broker SPAN/Exposure.",
            "Greeks come from the provider; for demo data they are Black-Scholes values "
            "on a synthetic surface.",
        ]
        if instrument is None or not instrument.fno:
            return AgentFinding(
                agent=self.name,
                symbol=symbol or None,
                headline=f"{symbol or 'Symbol'} has no listed F&O contract in this universe",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=limitations,
                data_quality={"score": 0, "band": "VERY_LOW"},
                metrics={},
            )

        try:
            res = ctx.registry.option_chain(symbol)
        except Exception as exc:  # noqa: BLE001
            return AgentFinding(
                agent=self.name,
                symbol=symbol,
                headline="Option chain unavailable",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=limitations + [f"Provider error: {exc}"],
                data_quality={"score": 0, "band": "VERY_LOW"},
                metrics={},
            )

        chain = res.value
        spot = chain.spot
        rows = chain.rows
        meta = chain.meta
        is_syn = meta.is_synthetic
        total_call_oi = sum(r.call_oi for r in rows)
        total_put_oi = sum(r.put_oi for r in rows)
        pcr = total_put_oi / total_call_oi if total_call_oi else None
        chg_call = sum(r.call_change_oi for r in rows)
        chg_put = sum(r.put_change_oi for r in rows)
        max_pain = self._max_pain(rows, chain.lot_size or 1)
        atm = min(rows, key=lambda r: abs(r.strike - spot))
        atm_iv = (atm.call_iv + atm.put_iv) / 2 / 100
        days = max((chain.expiry - date.today()).days, 1)
        expected_move = spot * atm_iv * math.sqrt(days / 365)
        iv_skew = (rows[0].put_iv - rows[-1].call_iv) if rows else 0.0
        support_strike = max(rows, key=lambda r: r.put_oi).strike
        resistance_strike = max(rows, key=lambda r: r.call_oi).strike

        strategies = self._strategy_comparison(rows, spot, chain.lot_size or 1, atm_iv, days)

        score = 0.0
        notes: list[str] = []
        if pcr is not None:
            if pcr > 1.2:
                score += 18
                notes.append(f"PCR {pcr:.2f} is put-heavy (defensive positioning / support build-up).")
            elif pcr < 0.7:
                score -= 18
                notes.append(f"PCR {pcr:.2f} is call-heavy (complacency or aggressive upside bets).")
            else:
                notes.append(f"PCR {pcr:.2f} is balanced.")
        if max_pain and spot:
            gap = (max_pain / spot - 1) * 100
            score += float(np.clip(gap * 1.5, -12, 12))
            notes.append(
                f"Max-pain strike {max_pain:,.0f} is {gap:+.2f}% from spot; pinning "
                "pressure tends to grow into expiry (a tendency, not a rule)."
            )
        if iv_skew > 3:
            score -= 8
            notes.append(f"Put IV exceeds call IV by {iv_skew:.1f} points — downside protection is bid.")

        stance = "BULLISH" if score >= 12 else "BEARISH" if score <= -12 else "NEUTRAL"
        quality = 45 if is_syn else 80
        confidence = self._quality_cap(quality) * 0.7

        evidence = [
            Evidence(
                claim=f"Put-call ratio {pcr:.2f} on total OI (puts {total_put_oi:,} / calls {total_call_oi:,})"
                if pcr
                else "PCR not computable",
                value=pcr,
                source=meta.source,
                as_of=str(chain.expiry),
                freshness=meta.freshness,
                verification=meta.verification,
                is_synthetic=is_syn,
            ),
            Evidence(
                claim=f"ATM IV {atm_iv * 100:.1f}% implies a {days}-day expected move of +/-{expected_move:,.0f} points",
                value=round(expected_move, 2),
                source=meta.source,
                as_of=str(chain.expiry),
                freshness=meta.freshness,
                verification=meta.verification,
                is_synthetic=is_syn,
            ),
            Evidence(
                claim=f"Highest call OI at {resistance_strike:,.0f}, highest put OI at {support_strike:,.0f}",
                value=resistance_strike,
                source=meta.source,
                as_of=str(chain.expiry),
                freshness=meta.freshness,
                verification=meta.verification,
                is_synthetic=is_syn,
            ),
        ]

        return AgentFinding(
            agent=self.name,
            symbol=symbol,
            headline=(
                f"{symbol} options: PCR {pcr:.2f}, max pain {max_pain:,.0f}, "
                f"ATM IV {atm_iv * 100:.1f}%, expected move +/-{expected_move:,.0f}"
                if pcr and max_pain
                else f"{symbol} option chain analysed with limited data"
            ),
            stance=stance,
            score=score,
            confidence=round(confidence, 3),
            evidence=evidence,
            risks=[
                "OI data is end-of-day; intraday positioning can reverse quickly.",
                "Selling options carries unlimited or very large tail risk; the "
                "structures below are research illustrations, not recommendations.",
                "Expiry-day pinning is a tendency, not a dependable rule.",
            ],
            limitations=limitations
            + (["Option chain is entirely synthetic demonstration data."] if is_syn else []),
            data_quality={"score": quality, "band": "LOW" if quality < 60 else "MODERATE"},
            metrics={
                "spot": spot,
                "expiry": chain.expiry.isoformat(),
                "lot_size": chain.lot_size,
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
                "pcr": None if pcr is None else round(pcr, 3),
                "change_in_call_oi": chg_call,
                "change_in_put_oi": chg_put,
                "max_pain": max_pain,
                "atm_iv_pct": round(atm_iv * 100, 2),
                "iv_skew_points": round(iv_skew, 2),
                "expected_move_points": round(expected_move, 2),
                "expected_move_pct": round(expected_move / spot * 100, 2),
                "support_strike": support_strike,
                "resistance_strike": resistance_strike,
                "notes": notes,
                "chain": [
                    {
                        "strike": r.strike,
                        "call_oi": r.call_oi,
                        "call_change_oi": r.call_change_oi,
                        "call_iv": r.call_iv,
                        "call_ltp": r.call_ltp,
                        "call_delta": r.call_delta,
                        "call_gamma": r.call_gamma,
                        "call_theta": r.call_theta,
                        "call_vega": r.call_vega,
                        "put_oi": r.put_oi,
                        "put_change_oi": r.put_change_oi,
                        "put_iv": r.put_iv,
                        "put_ltp": r.put_ltp,
                        "put_delta": r.put_delta,
                        "put_gamma": r.put_gamma,
                        "put_theta": r.put_theta,
                        "put_vega": r.put_vega,
                    }
                    for r in rows
                ],
                "strategies": strategies,
                "fno_enabled": False,
            },
            warnings=[
                "F&O trading is disabled in this build. These structures cannot be "
                "executed through this platform."
            ],
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _max_pain(rows, lot_size: int) -> float:
        """Strike at which total option-writer loss is minimised."""
        strikes = [r.strike for r in rows]
        best_strike, best_loss = strikes[0], float("inf")
        for k in strikes:
            loss = 0.0
            for r in rows:
                loss += max(k - r.strike, 0.0) * r.call_oi  # ITM calls payout
                loss += max(r.strike - k, 0.0) * r.put_oi
            if loss < best_loss:
                best_strike, best_loss = k, loss
        return round(best_strike, 2)

    @staticmethod
    def _strategy_comparison(rows, spot: float, lot_size: int, atm_iv: float, days: int) -> list[dict[str, Any]]:
        by_strike = {r.strike: r for r in rows}
        strikes = sorted(by_strike)
        atm = min(strikes, key=lambda k: abs(k - spot))
        idx = strikes.index(atm)
        up1 = strikes[min(idx + 2, len(strikes) - 1)]
        down1 = strikes[max(idx - 2, 0)]

        def leg(action: str, kind: str, strike: float, premium: float) -> Leg:
            return Leg(action, kind, strike, premium, 1)

        defs: list[tuple[str, str, list[Leg]]] = [
            (
                "Long call",
                "Bullish; defined risk, needs a move above breakeven.",
                [leg("BUY", "CE", atm, by_strike[atm].call_ltp)],
            ),
            (
                "Bull call spread",
                "Moderately bullish; cheaper than a naked call, profit capped at the upper strike.",
                [
                    leg("BUY", "CE", atm, by_strike[atm].call_ltp),
                    leg("SELL", "CE", up1, by_strike[up1].call_ltp),
                ],
            ),
            (
                "Long put",
                "Bearish hedge; defined risk.",
                [leg("BUY", "PE", atm, by_strike[atm].put_ltp)],
            ),
            (
                "Bear put spread",
                "Moderately bearish; lower cost, capped payoff.",
                [
                    leg("BUY", "PE", atm, by_strike[atm].put_ltp),
                    leg("SELL", "PE", down1, by_strike[down1].put_ltp),
                ],
            ),
            (
                "Short straddle (illustration)",
                "Neutral, range-bound view. Unlimited tail risk on both sides — "
                "shown only so the asymmetry is visible.",
                [
                    leg("SELL", "CE", atm, by_strike[atm].call_ltp),
                    leg("SELL", "PE", atm, by_strike[atm].put_ltp),
                ],
            ),
            (
                "Iron condor (illustration)",
                "Range-bound with defined risk.",
                [
                    leg("SELL", "CE", up1, by_strike[up1].call_ltp),
                    leg("BUY", "CE", strikes[min(idx + 4, len(strikes) - 1)],
                        by_strike[strikes[min(idx + 4, len(strikes) - 1)]].call_ltp),
                    leg("SELL", "PE", down1, by_strike[down1].put_ltp),
                    leg("BUY", "PE", strikes[max(idx - 4, 0)],
                        by_strike[strikes[max(idx - 4, 0)]].put_ltp),
                ],
            ),
        ]
        out = []
        for name, note, legs in defs:
            summary = structure_summary(legs, spot, lot_size)
            out.append({"name": name, "note": note, **summary})
        return out
