"""AGENT 03 — Valuation.

Produces bear/base/bull valuation for non-financials via FCFF DCF, and a
justified-P/B framework for banks/NBFCs. Relative multiples are shown alongside
so the user can see whether the DCF and the market tell the same story.

The agent never emits a "target price". It emits a modelled value range plus
the assumptions that generated it, and it explicitly states when the model is
not applicable.
"""

from __future__ import annotations

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.analytics import valuation as val
from backend.core.provenance import Freshness, Verification
from backend.data.universe import INSTRUMENTS

LABELS = {"dcf": "FCFF DCF", "justified_pb": "justified P/B", "relative": "relative multiples"}


class ValuationAgent(BaseAgent):
    name = "valuation"
    responsibility = "Intrinsic and relative valuation with transparent assumptions"
    requires = ("fundamentals", "price")

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        f = bundle.fundamentals
        a = bundle.analysis
        price = bundle.price
        is_syn = bundle.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else Freshness.EOD
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED
        )

        def ev(claim: str, value: float | None = None, unit: str | None = None) -> Evidence:
            return Evidence(
                claim=claim,
                value=None if value is None else round(float(value), 2),
                unit=unit,
                source="model output",
                as_of=str(bundle.series.meta.period_end),
                freshness=freshness,
                verification=verification,
                is_synthetic=is_syn,
            )

        latest = f.latest
        bvps = latest.equity / f.shares_outstanding if f.shares_outstanding else None
        eps = latest.eps
        ebitda_ps = latest.ebitda / f.shares_outstanding if f.shares_outstanding else None
        net_debt_ps = latest.net_debt / f.shares_outstanding if f.shares_outstanding else 0.0

        peers = self._peers(bundle.symbol, bundle.instrument.sector)
        multiple_rows = val.multiple_valuation(
            price=price,
            eps=eps,
            book_value_per_share=bvps or 0.0,
            ebitda_per_share=ebitda_ps or 0.0,
            net_debt_per_share=net_debt_ps or 0.0,
            peers=peers,
            history=[],
        )
        evidence: list[Evidence] = []
        metrics: dict[str, object] = {
            "price": round(price, 2),
            "eps": round(eps, 2),
            "book_value_per_share": None if bvps is None else round(bvps, 2),
            "peers": peers,
            "multiples": [
                {
                    "metric": r.metric,
                    "company": r.company_value,
                    "peer_median": r.peer_median,
                    "verdict": r.verdict,
                    "note": r.note,
                }
                for r in multiple_rows
            ],
        }
        warnings: list[str] = []
        limitations: list[str] = []
        scenarios: list[val.Scenario] = []
        value_anchor: float | None = None

        if a.is_financial:
            # ------------------------------------------------------- lender
            roe = a.latest.roe or 0.13
            bank = val.bank_valuation(
                price=price,
                book_value_per_share=bvps or 0.0,
                roe=roe,
                cost_of_equity=0.135,
                sustainable_growth=None,
                dividend_per_share=latest.dividend_per_share,
                payout_ratio=float(np.clip(f.dividend_payout_pct or 0.15, 0.0, 0.8)),
            )
            value_anchor = bank.fair_value_per_share
            metrics["bank_valuation"] = {
                "justified_pb": bank.justified_pb,
                "price_to_book": bank.price_to_book,
                "fair_value_per_share": bank.fair_value_per_share,
                "upside_pct": bank.upside_pct,
                "ddm_value": bank.ddm_value,
                "assumptions": {
                    "roe": round(roe, 4),
                    "cost_of_equity": 0.135,
                    "sustainable_growth": round(max(0.03, min(0.12, roe * (1 - (f.dividend_payout_pct or 0.15)))), 4),
                    "payout_ratio": round(float(f.dividend_payout_pct or 0.15), 3),
                },
                "notes": bank.notes,
            }
            evidence.append(
                ev(f"Justified P/B {bank.justified_pb} vs traded P/B {bank.price_to_book}")
            )
            limitations += bank.notes
            methods = ["justified_pb"]
            dcf_applicable = False
        else:
            # ---------------------------------------------------------- DCF
            dcf_applicable = True
            assumptions = val.default_dcf_assumptions(f, a, price)
            base = val.run_dcf(assumptions, latest.revenue, price)
            scenarios = val.run_scenarios(assumptions, latest.revenue, price)
            value_anchor = base.value_per_share
            metrics["dcf"] = {
                "assumptions": assumptions.__dict__,
                "value_per_share": base.value_per_share,
                "enterprise_value": base.enterprise_value,
                "equity_value": base.equity_value,
                "upside_pct": base.upside_pct,
                "terminal_share_of_value": base.terminal_share_of_value,
                "forecast": base.forecast,
                "sensitivity": base.sensitivity,
                "warnings": base.warnings,
                "disclaimer": base.disclaimer,
            }
            metrics["scenarios"] = [
                {
                    "name": s.name,
                    "growth": round(s.growth, 4),
                    "margin": round(s.margin, 4),
                    "wacc": s.wacc,
                    "terminal_growth": s.terminal_growth,
                    "value_per_share": s.value_per_share,
                    "note": s.note,
                }
                for s in scenarios
            ]
            warnings.extend(base.warnings)
            if base.value_per_share:
                evidence.append(ev(f"DCF base value per share INR {base.value_per_share:,.2f}",
                                   base.value_per_share, "INR"))
            methods = ["dcf", "relative"]

            # ------------------------------------------------------ DDM / RI
            ddm = val.dividend_discount(latest.dividend_per_share)
            ri = val.residual_income(bvps or 0.0, a.latest.roe or 0.12)
            metrics["cross_checks"] = {"ddm": ddm, "residual_income": ri}
            limitations.append(ddm["note"])
            limitations.append(ri["note"])
            evidence.append(ev(f"Residual income cross-check INR {ri['value']:,.2f}",
                               float(ri["value"]) if ri["value"] else None, "INR"))

        evidence.extend(
            [
                ev(f"{row.metric} {row.company_value} vs peers {row.peer_median} ({row.verdict})",
                   row.company_value)
                for row in multiple_rows
                if row.company_value is not None
            ]
        )

        upside = (
            (value_anchor / price - 1) * 100 if value_anchor and price else None
        )
        metrics["upside_pct"] = None if upside is None else round(upside, 2)
        metrics["methods_used"] = methods

        if upside is None:
            stance, score = "INSUFFICIENT_DATA", 0.0
        elif upside > 20:
            stance, score = "BULLISH", min(60.0, upside * 0.8)
        elif upside < -20:
            stance, score = "BEARISH", max(-70.0, upside * 0.6)
        else:
            stance, score = "NEUTRAL", float(np.clip(upside * 0.5, -20, 20))

        # A wide bear/bull spread means the answer is assumption-driven.
        if scenarios:
            values = [s.value_per_share for s in scenarios if s.value_per_share]
            if len(values) >= 2 and price:
                spread = (max(values) - min(values)) / price
                if spread > 0.8:
                    warnings.append(
                        f"Bear-to-bull spread is {spread:.0%} of the share price: the "
                        "valuation is dominated by assumptions, not by evidence."
                    )
                    score *= 0.7

        limitations.extend(
            [
                "The DCF uses a single consolidated revenue line; segment-level "
                "capital allocation is not modelled.",
                "Working-capital and capex ratios are inferred from history, not from "
                "management guidance.",
                "Relative valuation peers are drawn from the platform universe by "
                "sector, which is a coarse peer definition.",
            ]
        )
        limitations.append(val.DISCLAIMER)
        if is_syn:
            limitations.append("All valuation inputs are synthetic demonstration data.")

        headline = (
            f"Valuation {'not comparable' if upside is None else f'{upside:+.1f}% vs base-case value'} "
            f"(fair-value anchor INR {value_anchor:,.2f} via {LABELS.get(methods[0], methods[0])})" if value_anchor
            else "Valuation not computable from available data"
        )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=headline,
            stance=stance,
            score=float(score),
            confidence=self._quality_cap(bundle.data_quality["score"]) * (0.8 if value_anchor else 0.2),
            evidence=evidence,
            risks=warnings + [
                "Valuation is assumption-driven; a 1% change in WACC can move the "
                "DCF value by 10-15%.",
            ],
            limitations=limitations,
            data_quality=bundle.data_quality,
            metrics=metrics,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ peers
    def _peers(self, symbol: str, sector: str) -> list[dict[str, float]]:
        """Peer multiples built from the same analytics path (cheap and consistent)."""
        from backend.data.providers.synthetic import build_fundamentals, daily_bars
        from backend.analytics.fundamental import analyse_fundamentals

        out: list[dict[str, float]] = []
        for inst in INSTRUMENTS:
            if inst.sector != sector or inst.symbol == symbol:
                continue
            try:
                fund = build_fundamentals(inst.symbol)
                price = float(daily_bars(inst.symbol)["close"].iloc[-1])
            except Exception:  # noqa: BLE001
                continue
            latest = fund.latest
            pe = fund.market_cap / latest.pat if latest.pat > 0 else None
            bv = latest.equity / fund.shares_outstanding if fund.shares_outstanding else None
            pb = price / bv if bv and bv > 0 else None
            ev_ebitda = (
                (fund.market_cap + latest.net_debt) / latest.ebitda
                if latest.ebitda > 0
                else None
            )
            out.append(
                {
                    "symbol": inst.symbol,  # type: ignore[dict-item]
                    "pe": pe,
                    "pb": pb,
                    "ev_ebitda": ev_ebitda,
                }
            )
        return out
