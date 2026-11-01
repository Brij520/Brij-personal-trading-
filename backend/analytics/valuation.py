"""Valuation models with fully exposed assumptions.

Philosophy: a valuation is a set of *stated assumptions*, not a price target.
Every model returns its inputs, its output and a sensitivity grid, so the user
can see how much the answer depends on what they believe.

Models
------
* Two-stage FCFF DCF (explicit forecast + fade to terminal growth).
* Relative valuation (P/E, EV/EBITDA, P/B) vs an explicit peer set and vs the
  stock's own history.
* Dividend discount model (Gordon growth) when a dividend exists.
* Residual income model (clean-surplus).
* Banks/NBFC: justified P/B from ROE and cost of equity, plus a DDM variant,
  because FCFF DCF is not valid for a lender.

All monetary values are INR crore unless labelled per-share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from backend.data.providers.base import Fundamentals
from backend.analytics.fundamental import FundamentalAnalysis

DISCLAIMER = (
    "Valuation is a model output, not a forecast. It is highly sensitive to the "
    "assumptions shown. Do not treat any single number here as a target price."
)


@dataclass
class DCFAssumptions:
    horizon_years: int = 5
    revenue_growth_first_year: float = 0.12
    growth_fade_to: float = 0.05
    ebit_margin: float = 0.14
    tax_rate: float = 0.252
    capex_pct_revenue: float = 0.05
    nwc_pct_revenue_increment: float = 0.12
    wacc: float = 0.12
    terminal_growth: float = 0.045
    net_debt: float = 0.0
    shares_outstanding: float = 1.0

    def validate(self) -> list[str]:
        problems = []
        if self.wacc <= self.terminal_growth:
            problems.append(
                f"WACC ({self.wacc:.1%}) must exceed terminal growth "
                f"({self.terminal_growth:.1%}); the terminal value is undefined."
            )
        if self.horizon_years < 3:
            problems.append("Forecast horizon below 3 years is not credible.")
        if not 0 <= self.tax_rate <= 0.5:
            problems.append("Tax rate outside a plausible 0-50% band.")
        if self.shares_outstanding <= 0:
            problems.append("Share count must be positive.")
        return problems


@dataclass
class Scenario:
    name: str
    growth: float
    margin: float
    wacc: float
    terminal_growth: float
    value_per_share: float | None
    equity_value: float | None
    note: str = ""


@dataclass
class DCFResult:
    assumptions: DCFAssumptions
    forecast: list[dict[str, float]]
    pv_explicit: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    value_per_share: float | None
    current_price: float | None
    upside_pct: float | None
    terminal_share_of_value: float
    sensitivity: dict[str, dict[str, float]]
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def _dcf_core(a: DCFAssumptions, start_revenue: float) -> tuple[list[dict], float, float, float]:
    forecast: list[dict] = []
    revenue = start_revenue
    pv_explicit = 0.0
    prev_nwc = a.nwc_pct_revenue_increment * revenue
    for year in range(1, a.horizon_years + 1):
        # Linear fade from the first-year growth to the terminal growth.
        if a.horizon_years > 1:
            g = a.revenue_growth_first_year + (
                a.growth_fade_to - a.revenue_growth_first_year
            ) * (year - 1) / (a.horizon_years - 1)
        else:
            g = a.revenue_growth_first_year
        revenue = revenue * (1 + g)
        ebit = revenue * a.ebit_margin
        nopat = ebit * (1 - a.tax_rate)
        capex = revenue * a.capex_pct_revenue
        nwc = a.nwc_pct_revenue_increment * revenue
        d_nwc = nwc - prev_nwc
        prev_nwc = nwc
        # FCFF = NOPAT + D&A - capex - increase in NWC. Depreciation is proxied at
        # 1.0x capex in steady state (maintenance capex), so FCFF = NOPAT - dNWC.
        # This is deliberately conservative: growth capex is not credited back.
        fcff = nopat - d_nwc
        discount = (1 + a.wacc) ** year
        pv = fcff / discount
        pv_explicit += pv
        forecast.append(
            {
                "year": year,
                "revenue": round(revenue, 1),
                "growth_pct": round(g * 100, 2),
                "ebit": round(ebit, 1),
                "nopat": round(nopat, 1),
                "fcff": round(fcff, 1),
                "discount_factor": round(1 / discount, 4),
                "pv_fcff": round(pv, 1),
            }
        )
    terminal_fcff = forecast[-1]["fcff"] * (1 + a.terminal_growth)
    tv = terminal_fcff / (a.wacc - a.terminal_growth)
    pv_terminal = tv / (1 + a.wacc) ** a.horizon_years
    return forecast, pv_explicit, pv_terminal, revenue


def run_dcf(
    assumptions: DCFAssumptions, start_revenue: float, current_price: float | None = None
) -> DCFResult:
    warnings = assumptions.validate()
    if warnings:
        return DCFResult(
            assumptions=assumptions,
            forecast=[],
            pv_explicit=0.0,
            pv_terminal=0.0,
            enterprise_value=0.0,
            equity_value=0.0,
            value_per_share=None,
            current_price=current_price,
            upside_pct=None,
            terminal_share_of_value=0.0,
            sensitivity={},
            warnings=warnings,
        )
    forecast, pv_explicit, pv_terminal, _ = _dcf_core(assumptions, start_revenue)
    ev = pv_explicit + pv_terminal
    equity = ev - assumptions.net_debt
    per_share = equity / assumptions.shares_outstanding if assumptions.shares_outstanding else None
    upside = (
        (per_share / current_price - 1) * 100
        if per_share is not None and current_price
        else None
    )
    # Sensitivity grid: WACC x terminal growth.
    grid: dict[str, dict[str, float]] = {}
    for dw in (-0.02, -0.01, 0.0, 0.01, 0.02):
        wacc = assumptions.wacc + dw
        row: dict[str, float] = {}
        for dg in (-0.01, -0.005, 0.0, 0.005, 0.01):
            g = assumptions.terminal_growth + dg
            if wacc - g <= 0.005:
                row[f"{g * 100:.1f}%"] = float("nan")
                continue
            alt = DCFAssumptions(**{**assumptions.__dict__, "wacc": wacc, "terminal_growth": g})
            _, pe, pt, _ = _dcf_core(alt, start_revenue)
            eq = pe + pt - alt.net_debt
            row[f"{g * 100:.1f}%"] = round(eq / alt.shares_outstanding, 2)
        grid[f"{wacc * 100:.1f}%"] = row
    terminal_share = pv_terminal / ev if ev > 0 else 0.0
    if terminal_share > 0.75:
        warnings.append(
            f"Terminal value is {terminal_share:.0%} of the total — the conclusion "
            "depends mostly on the terminal assumption, not the forecast."
        )
    return DCFResult(
        assumptions=assumptions,
        forecast=forecast,
        pv_explicit=round(pv_explicit, 1),
        pv_terminal=round(pv_terminal, 1),
        enterprise_value=round(ev, 1),
        equity_value=round(equity, 1),
        value_per_share=None if per_share is None else round(per_share, 2),
        current_price=current_price,
        upside_pct=None if upside is None else round(upside, 2),
        terminal_share_of_value=round(terminal_share, 3),
        sensitivity=grid,
        warnings=warnings,
    )


def default_dcf_assumptions(
    fund: Fundamentals, analysis: FundamentalAnalysis, price: float | None
) -> DCFAssumptions:
    """Derive starting assumptions from the company's own history.

    Growth is anchored to the realised three-year revenue CAGR (capped), the
    margin to the realised EBIT margin, and the WACC from a leverage-aware
    build-up. These are *starting points the user can and should change.*
    """
    latest = analysis.latest
    growth = analysis.revenue_cagr_3y if analysis.revenue_cagr_3y is not None else 0.10
    growth = max(-0.05, min(0.28, growth))
    ebit_margin = latest.ebit_margin if latest.ebit_margin is not None else 0.14
    ebit_margin = max(0.02, min(0.45, ebit_margin))
    de = latest.debt_to_equity or 0.0
    beta_proxy = 0.85 + 0.25 * min(de, 2.0)
    wacc = 0.068 + beta_proxy * 0.050  # risk-free 6.8% + beta * equity risk premium 5.0%
    wacc = max(0.095, min(0.17, wacc))
    return DCFAssumptions(
        revenue_growth_first_year=growth,
        growth_fade_to=max(0.045, min(0.09, growth * 0.55)),
        ebit_margin=ebit_margin,
        capex_pct_revenue=max(0.01, min(0.12, (fund.latest.capex / fund.latest.revenue)
                                       if fund.latest.revenue else 0.04)),
        wacc=round(wacc, 3),
        terminal_growth=0.045,
        net_debt=fund.latest.net_debt,
        shares_outstanding=fund.shares_outstanding,
    )


def run_scenarios(
    base: DCFAssumptions, start_revenue: float, price: float | None
) -> list[Scenario]:
    bear = DCFAssumptions(
        **{**base.__dict__,
           "revenue_growth_first_year": base.revenue_growth_first_year * 0.45,
           "growth_fade_to": 0.025,
           "ebit_margin": base.ebit_margin * 0.80,
           "wacc": min(0.20, base.wacc + 0.02),
           "terminal_growth": 0.030}
    )
    bull = DCFAssumptions(
        **{**base.__dict__,
           "revenue_growth_first_year": min(0.35, base.revenue_growth_first_year * 1.45 + 0.02),
           "growth_fade_to": min(0.09, base.growth_fade_to * 1.5),
           "ebit_margin": min(0.50, base.ebit_margin * 1.15),
           "wacc": max(0.08, base.wacc - 0.015),
           "terminal_growth": min(0.055, base.terminal_growth + 0.005)}
    )
    out: list[Scenario] = []
    for name, assumptions, note in (
        ("BEAR", bear, "Demand disappoints; margins compress; discount rate rises."),
        ("BASE", base, "Realised growth and margin fade toward a mature state."),
        ("BULL", bull, "Growth persists longer with margin expansion and a lower risk premium."),
    ):
        res = run_dcf(assumptions, start_revenue, price)
        out.append(
            Scenario(
                name=name,
                growth=assumptions.revenue_growth_first_year,
                margin=assumptions.ebit_margin,
                wacc=assumptions.wacc,
                terminal_growth=assumptions.terminal_growth,
                value_per_share=res.value_per_share,
                equity_value=res.equity_value,
                note=note,
            )
        )
    return out


# --------------------------------------------------------------- relative

@dataclass
class RelativeValuation:
    metric: str
    company_value: float | None
    peer_median: float | None
    sector_median: float | None
    historical_median: float | None
    verdict: str
    note: str


def multiple_valuation(
    price: float,
    eps: float,
    book_value_per_share: float,
    ebitda_per_share: float,
    net_debt_per_share: float,
    peers: list[dict[str, float]],
    history: list[float],
) -> list[RelativeValuation]:
    """Compare P/E, P/B and EV/EBITDA with peers and with its own history."""
    out: list[RelativeValuation] = []

    def summarise(
        metric: str,
        company: float | None,
        peer_values: list[float],
        hist: list[float],
        lower_is_cheaper: bool = True,
    ) -> RelativeValuation:
        peer_med = round(median(peer_values), 2) if peer_values else None
        hist_med = round(median(hist), 2) if hist else None
        if company is None or peer_med is None:
            return RelativeValuation(
                metric, company, peer_med, peer_med, hist_med, "INSUFFICIENT",
                "Not enough peer or company data for a comparison.",
            )
        ratio = company / peer_med if peer_med else None
        if ratio is None:
            verdict = "INSUFFICIENT"
        elif lower_is_cheaper:
            verdict = "CHEAP" if ratio < 0.8 else "EXPENSIVE" if ratio > 1.25 else "IN_LINE"
        else:
            verdict = "CHEAP" if ratio > 1.25 else "EXPENSIVE" if ratio < 0.8 else "IN_LINE"
        note = (
            f"{metric} at {company:.2f} vs peer median {peer_med:.2f} "
            f"({(ratio or 0) * 100:.0f}% of peers)."
        )
        if hist_med:
            note += f" Own five-year median {hist_med:.2f}."
        return RelativeValuation(metric, company, peer_med, peer_med, hist_med, verdict, note)

    pe_peers = [p["pe"] for p in peers if p.get("pe")]
    pb_peers = [p["pb"] for p in peers if p.get("pb")]
    evebitda_peers = [p["ev_ebitda"] for p in peers if p.get("ev_ebitda")]
    pe = price / eps if eps and eps > 0 else None
    pb = price / book_value_per_share if book_value_per_share and book_value_per_share > 0 else None
    ev = price + net_debt_per_share
    ev_ebitda = ev / ebitda_per_share if ebitda_per_share and ebitda_per_share > 0 else None
    out.append(summarise("P/E", None if pe is None else round(pe, 2), pe_peers, history))
    out.append(summarise("P/B", None if pb is None else round(pb, 2), pb_peers, []))
    out.append(summarise("EV/EBITDA", None if ev_ebitda is None else round(ev_ebitda, 2),
                         evebitda_peers, []))
    return out


# ------------------------------------------------------------------ banks

@dataclass
class BankValuation:
    justified_pb: float | None
    justified_pb_note: str
    price_to_book: float | None
    fair_value_per_share: float | None
    upside_pct: float | None
    ddm_value: float | None
    notes: list[str] = field(default_factory=list)


def bank_valuation(
    price: float,
    book_value_per_share: float,
    roe: float,
    cost_of_equity: float = 0.135,
    sustainable_growth: float | None = None,
    dividend_per_share: float = 0.0,
    payout_ratio: float = 0.15,
) -> BankValuation:
    """Justified P/B = (ROE - g) / (CoE - g), the standard lender framework.

    This is more defensible for a bank than an FCFF DCF. It still depends on
    a long-run ROE and cost-of-equity assumption, which are stated explicitly.
    """
    # Sustainable growth follows the retention identity g = ROE x retention, but
    # is capped at (cost of equity - 2.5%) because no bank compounds book value
    # above its cost of capital in perpetuity. Without this cap the Gordon-style
    # formula produces absurd multiple swings.
    if sustainable_growth is None:
        retention_growth = roe * (1 - payout_ratio)
        sustainable_growth = max(0.03, min(retention_growth, cost_of_equity - 0.025))
    notes = [
        "The justified P/B denominator (cost of equity minus sustainable growth) is "
        "narrow, so the output is highly sensitive to both assumptions. Treat it as "
        "a sensitivity range, not a price target.",
        "Banks and NBFCs are valued on book value, not on free cash flow. "
        "An FCFF DCF would be structurally misleading for a lender.",
        f"Assumes long-run ROE of {roe:.1%}, cost of equity {cost_of_equity:.1%} "
        f"and sustainable growth {sustainable_growth:.1%}.",
    ]
    pb: float | None = None
    if cost_of_equity > sustainable_growth and book_value_per_share > 0:
        pb = (roe - sustainable_growth) / (cost_of_equity - sustainable_growth)
        pb = max(0.0, round(pb, 2))
    price_to_book = price / book_value_per_share if book_value_per_share > 0 else None
    fair = None if pb is None else round(pb * book_value_per_share, 2)
    upside = round((fair / price - 1) * 100, 2) if fair and price else None
    ddm = None
    if dividend_per_share > 0 and cost_of_equity > sustainable_growth:
        ddm = round(dividend_per_share * (1 + sustainable_growth) / (cost_of_equity - sustainable_growth), 2)
    else:
        notes.append("Dividend discount model skipped: no dividend or growth >= cost of equity.")
    if pb is not None and pb < 0.75:
        notes.append(
            "Justified P/B below 0.75 implies the model expects returns below the "
            "cost of equity indefinitely — check whether that is a fair judgement."
        )
    if price_to_book is not None and price_to_book > 4:
        notes.append(
            f"Trading at {price_to_book:.1f}x book requires a durable franchise; "
            "growth assumptions dominate the outcome."
        )
    return BankValuation(pb, "Justified P/B from ROE, growth and cost of equity.",
                         None if price_to_book is None else round(price_to_book, 2),
                         fair, upside, ddm, notes)


# ------------------------------------------------------------------ DDM / RI

def dividend_discount(
    dividend_per_share: float, cost_of_equity: float = 0.12, growth: float = 0.06
) -> dict[str, float | str]:
    if dividend_per_share <= 0:
        return {"value": 0.0, "note": "No dividend paid; DDM not applicable."}
    if cost_of_equity <= growth:
        return {"value": 0.0, "note": "Gordon growth undefined: g >= cost of equity."}
    value = dividend_per_share * (1 + growth) / (cost_of_equity - growth)
    return {
        "value": round(value, 2),
        "note": (
            f"Gordon growth with DPS {dividend_per_share:.2f}, g {growth:.1%}, "
            f"CoE {cost_of_equity:.1%}. Sensitive to g."
        ),
    }


def residual_income(
    book_value_per_share: float,
    roe: float,
    cost_of_equity: float = 0.12,
    growth: float = 0.05,
    years: int = 5,
) -> dict[str, float | str]:
    """Residual income with a fading ROE to the cost of equity."""
    if book_value_per_share <= 0:
        return {"value": 0.0, "note": "Book value unavailable; residual income model skipped."}
    bv = book_value_per_share
    pv_ri = 0.0
    for year in range(1, years + 1):
        roe_t = roe + (cost_of_equity - roe) * (year / years)
        earnings = bv * roe_t
        ri = earnings - cost_of_equity * bv
        pv_ri += ri / (1 + cost_of_equity) ** year
        bv += earnings * (1 - 0.3)
    terminal = pv_ri * 0.0  # no terminal value: conservative, stated below
    value = book_value_per_share + pv_ri + terminal
    return {
        "value": round(value, 2),
        "note": (
            "Residual income with ROE fading to cost of equity over "
            f"{years} years and no terminal value (deliberately conservative)."
        ),
    }
