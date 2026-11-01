"""Fundamental analysis: ratios, quality scoring and growth diagnostics.

Every ratio is computed from the reported statements only. Nothing is
estimated. When an input is missing or mathematically impossible (negative
equity, zero revenue) the ratio is *omitted* rather than coerced — the output
carries an ``insufficient`` list so downstream agents can lower confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from backend.data.providers.base import AnnualFinancials, Fundamentals

CRORE = 1e7  # 1 crore = 10 million


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    value = numerator / denominator
    return None if value != value else value  # drop NaN


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def cagr(first: float, last: float, years: int) -> float | None:
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


@dataclass
class RatioSet:
    fiscal_year: str
    revenue: float
    revenue_growth: float | None
    ebitda_margin: float | None
    ebit_margin: float | None
    net_margin: float | None
    roe: float | None
    roce: float | None
    roa: float | None
    debt_to_equity: float | None
    interest_coverage: float | None
    net_debt_to_ebitda: float | None
    cfo_to_pat: float | None
    fcf: float
    fcf_margin: float | None
    receivable_days: float | None
    inventory_days: float | None
    payable_days: float | None
    cash_conversion_cycle: float | None
    working_capital_to_revenue: float | None
    eps: float
    asset_turnover: float | None
    dividend_payout: float | None

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "fiscal_year": self.fiscal_year,
            "revenue_cr": round(self.revenue, 1),
            "revenue_growth_pct": _pct(self.revenue_growth),
            "ebitda_margin_pct": _pct(self.ebitda_margin),
            "ebit_margin_pct": _pct(self.ebit_margin),
            "net_margin_pct": _pct(self.net_margin),
            "roe_pct": _pct(self.roe),
            "roce_pct": _pct(self.roce),
            "roa_pct": _pct(self.roa),
            "debt_to_equity": None if self.debt_to_equity is None else round(self.debt_to_equity, 2),
            "interest_coverage": None
            if self.interest_coverage is None
            else round(self.interest_coverage, 2),
            "net_debt_to_ebitda": None
            if self.net_debt_to_ebitda is None
            else round(self.net_debt_to_ebitda, 2),
            "cfo_to_pat": None if self.cfo_to_pat is None else round(self.cfo_to_pat, 2),
            "fcf_cr": round(self.fcf, 1),
            "fcf_margin_pct": _pct(self.fcf_margin),
            "receivable_days": None
            if self.receivable_days is None
            else round(self.receivable_days, 1),
            "inventory_days": None
            if self.inventory_days is None
            else round(self.inventory_days, 1),
            "payable_days": None if self.payable_days is None else round(self.payable_days, 1),
            "cash_conversion_cycle_days": None
            if self.cash_conversion_cycle is None
            else round(self.cash_conversion_cycle, 1),
            "eps": round(self.eps, 2),
            "asset_turnover": None
            if self.asset_turnover is None
            else round(self.asset_turnover, 2),
        }


@dataclass
class FundamentalAnalysis:
    symbol: str
    company_name: str
    sector: str
    industry: str
    is_financial: bool
    ratios: list[RatioSet]
    latest: RatioSet
    revenue_cagr_3y: float | None
    revenue_cagr_5y: float | None
    pat_cagr_3y: float | None
    eps_cagr_3y: float | None
    eps_consistency: float | None
    margin_trend: str
    leverage_trend: str
    cash_quality: str
    promoter_holding_pct: float
    promoter_pledge_pct: float
    institutional_pct: float
    quality_score: int
    quality_band: str
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    insufficient: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "industry": self.industry,
            "is_financial": self.is_financial,
            "peer_group": "banks/NBFC" if self.is_financial else self.sector,
            "quality_score": self.quality_score,
            "quality_band": self.quality_band,
            "revenue_cagr_3y_pct": _pct(self.revenue_cagr_3y),
            "revenue_cagr_5y_pct": _pct(self.revenue_cagr_5y),
            "pat_cagr_3y_pct": _pct(self.pat_cagr_3y),
            "eps_cagr_3y_pct": _pct(self.eps_cagr_3y),
            "eps_consistency_pct": _pct(self.eps_consistency),
            "margin_trend": self.margin_trend,
            "leverage_trend": self.leverage_trend,
            "cash_quality": self.cash_quality,
            "promoter_holding_pct": self.promoter_holding_pct,
            "promoter_pledge_pct": self.promoter_pledge_pct,
            "institutional_pct": self.institutional_pct,
            "strengths": self.strengths,
            "concerns": self.concerns,
            "insufficient_data": self.insufficient,
            "latest_ratios": self.latest.as_dict(),
            "history": [r.as_dict() for r in self.ratios],
        }


def _ratios_for(
    prev: AnnualFinancials | None, cur: AnnualFinancials, is_financial: bool
) -> RatioSet:
    rev = cur.revenue
    ebitda_margin = _safe_div(cur.ebitda, rev)
    ebit_margin = _safe_div(cur.ebit, rev)
    net_margin = _safe_div(cur.pat, rev)
    roe = _safe_div(cur.pat, cur.equity)
    roa = _safe_div(cur.pat, cur.total_assets)
    # ROCE = EBIT / (equity + debt - cash). For lenders, capital employed is
    # dominated by borrowings, so ROCE is not a meaningful quality metric and is
    # reported as None (bank/NBFC analysis uses ROA and NIM instead).
    capital_employed = cur.equity + cur.total_debt - cur.cash
    roce = None if is_financial else _safe_div(cur.ebit, capital_employed)
    de = _safe_div(cur.total_debt, cur.equity)
    ic = _safe_div(cur.ebit, cur.interest_expense)
    nd_ebitda = _safe_div(cur.net_debt, cur.ebitda)
    cfo_pat = _safe_div(cur.cfo, cur.pat)
    fcf = cur.cfo - cur.capex
    fcf_margin = _safe_div(fcf, rev)
    rec_days = None
    inv_days = pay_days = None
    if rev:
        rec_days = _safe_div(cur.receivables, rev) * 365 if cur.receivables else None
        inv_days = _safe_div(cur.inventory, rev) * 365 if cur.inventory else None
        pay_days = _safe_div(cur.payables, rev) * 365 if cur.payables else None
    ccc = None
    if rec_days is not None and pay_days is not None:
        ccc = rec_days + (inv_days or 0.0) - pay_days
    wc_rev = _safe_div(cur.receivables + cur.inventory - cur.payables, rev)
    growth = _safe_div(rev - prev.revenue, prev.revenue) if prev else None
    payout = _safe_div(cur.dividend_per_share, cur.eps)
    return RatioSet(
        fiscal_year=cur.fiscal_year,
        revenue=rev,
        revenue_growth=growth,
        ebitda_margin=ebitda_margin,
        ebit_margin=ebit_margin,
        net_margin=net_margin,
        roe=roe,
        roce=roce,
        roa=roa,
        debt_to_equity=de,
        interest_coverage=ic,
        net_debt_to_ebitda=nd_ebitda,
        cfo_to_pat=cfo_pat,
        fcf=fcf,
        fcf_margin=fcf_margin,
        receivable_days=rec_days,
        inventory_days=inv_days,
        payable_days=pay_days,
        cash_conversion_cycle=ccc,
        working_capital_to_revenue=wc_rev,
        eps=cur.eps,
        asset_turnover=_safe_div(rev, cur.total_assets),
        dividend_payout=payout,
    )


def _trend(values: list[float | None]) -> str:
    clean = [v for v in values if v is not None]
    if len(clean) < 3:
        return "insufficient"
    first, last = clean[0], clean[-1]
    delta = last - first
    scale = max(abs(first), 1e-9)
    if delta / scale > 0.06:
        return "improving"
    if delta / scale < -0.06:
        return "deteriorating"
    return "stable"


def analyse_fundamentals(fund: Fundamentals) -> FundamentalAnalysis:
    is_financial = fund.sector == "Financial Services"
    annual = fund.annual
    ratios: list[RatioSet] = []
    for i, cur in enumerate(annual):
        ratios.append(_ratios_for(annual[i - 1] if i > 0 else None, cur, is_financial))
    latest = ratios[-1]
    insufficient: list[str] = []

    def yrs(n: int) -> int:
        return min(n, len(annual) - 1)

    rev_cagr_3 = cagr(annual[-1 - yrs(3)].revenue, annual[-1].revenue, yrs(3)) if yrs(3) else None
    rev_cagr_5 = cagr(annual[0].revenue, annual[-1].revenue, len(annual) - 1)
    pat_series = [a.pat for a in annual]
    eps_series = [a.eps for a in annual]
    pat_cagr_3 = (
        cagr(annual[-1 - yrs(3)].pat, annual[-1].pat, yrs(3)) if yrs(3) else None
    )
    eps_cagr_3 = (
        cagr(annual[-1 - yrs(3)].eps, annual[-1].eps, yrs(3)) if yrs(3) else None
    )
    growth_years = [
        g for g in (r.revenue_growth for r in ratios) if g is not None
    ]
    eps_consistency = (
        sum(1 for g in growth_years if g > 0) / len(growth_years) if growth_years else None
    )

    # ------------------------------------------------------------- scoring
    score = 50
    strengths: list[str] = []
    concerns: list[str] = []

    def bump(points: int, why: str, positive: bool) -> None:
        nonlocal score
        score += points
        (strengths if positive else concerns).append(why)

    if latest.roe is not None:
        if latest.roe >= 0.20:
            bump(10, f"ROE of {latest.roe * 100:.1f}% indicates high return on equity.", True)
        elif latest.roe >= 0.14:
            bump(5, f"ROE of {latest.roe * 100:.1f}% is respectable.", True)
        elif latest.roe < 0.08:
            bump(-10, f"ROE of {latest.roe * 100:.1f}% is low for an Indian listed company.", False)
    else:
        insufficient.append("ROE not computable (equity unavailable or negative).")

    if not is_financial and latest.roce is not None:
        if latest.roce >= 0.18:
            bump(8, f"ROCE of {latest.roce * 100:.1f}% suggests a durable moat.", True)
        elif latest.roce < 0.10:
            bump(-8, f"ROCE of {latest.roce * 100:.1f}% is below the cost of capital proxy.", False)

    if latest.debt_to_equity is not None and not is_financial:
        if latest.debt_to_equity <= 0.3:
            bump(6, f"Low leverage at D/E {latest.debt_to_equity:.2f}.", True)
        elif latest.debt_to_equity > 1.5:
            bump(-8, f"High leverage at D/E {latest.debt_to_equity:.2f}.", False)

    if is_financial:
        # For lenders, interest expense is cost of funds, and CFO/FCF are not
        # comparable quality signals. Use ROA instead and say so.
        if latest.roa is not None:
            if latest.roa >= 0.018:
                bump(6, f"ROA of {latest.roa * 100:.2f}% is healthy for a lender.", True)
            elif latest.roa < 0.008:
                bump(-8, f"ROA of {latest.roa * 100:.2f}% is weak for a lender.", False)
        concerns.append(
            "Lender: asset quality (GNPA/NNPA), NIM and provision coverage are not "
            "in this dataset; conventional CFO/FCF and interest-coverage checks "
            "are not meaningful here."
        )
    if not is_financial and latest.interest_coverage is not None and latest.interest_coverage < 2.0:
        bump(-6, f"Interest coverage of {latest.interest_coverage:.1f}x is thin.", False)

    if not is_financial and latest.cfo_to_pat is not None:
        if latest.cfo_to_pat >= 1.0:
            bump(8, f"Operating cash flow exceeds profit (CFO/PAT {latest.cfo_to_pat:.2f}).", True)
        elif latest.cfo_to_pat < 0.6:
            bump(-10, f"Weak cash conversion (CFO/PAT {latest.cfo_to_pat:.2f}).", False)
    else:
        insufficient.append("CFO/PAT not computable.")

    if not is_financial:
        if latest.fcf > 0:
            bump(5, f"Free cash flow positive at INR {latest.fcf:,.0f} crore.", True)
        else:
            bump(-6, f"Free cash flow negative at INR {latest.fcf:,.0f} crore.", False)

    if rev_cagr_3 is not None:
        if rev_cagr_3 >= 0.15:
            bump(7, f"Revenue CAGR of {rev_cagr_3 * 100:.1f}% over three years.", True)
        elif rev_cagr_3 < 0.05:
            bump(-6, f"Revenue CAGR of only {rev_cagr_3 * 100:.1f}% over three years.", False)
    else:
        insufficient.append("Three-year revenue CAGR not computable.")

    if eps_consistency is not None and eps_consistency < 0.6:
        bump(-8, f"Earnings grew in only {eps_consistency * 100:.0f}% of years — inconsistent.", False)

    if fund.promoter_pledge_pct > 10:
        bump(-10, f"Promoter pledge of {fund.promoter_pledge_pct:.1f}% of holding is a red flag.", False)
    if fund.auditor_qualification:
        bump(-12, "Auditor issued a qualification.", False)
    if fund.auditor_changes_5y >= 2:
        bump(-8, f"{fund.auditor_changes_5y} auditor changes in five years.", False)
    if fund.equity_dilution_pct_3y > 8:
        bump(-6, f"Equity diluted {fund.equity_dilution_pct_3y:.1f}% in three years.", False)
    if fund.related_party_txn_pct_revenue > 10:
        bump(-5, f"Related-party transactions at {fund.related_party_txn_pct_revenue:.1f}% of revenue.", False)

    score = int(max(0, min(100, score)))
    band = "STRONG" if score >= 72 else "GOOD" if score >= 58 else "AVERAGE" if score >= 42 else "WEAK"

    return FundamentalAnalysis(
        symbol=fund.symbol,
        company_name=fund.company_name,
        sector=fund.sector,
        industry=fund.industry,
        is_financial=is_financial,
        ratios=ratios,
        latest=latest,
        revenue_cagr_3y=rev_cagr_3,
        revenue_cagr_5y=rev_cagr_5,
        pat_cagr_3y=pat_cagr_3,
        eps_cagr_3y=eps_cagr_3,
        eps_consistency=eps_consistency,
        margin_trend=_trend([r.ebitda_margin for r in ratios]),
        leverage_trend=_trend([r.debt_to_equity for r in ratios]),
        cash_quality="strong"
        if (latest.cfo_to_pat or 0) >= 1.0
        else "adequate"
        if (latest.cfo_to_pat or 0) >= 0.75
        else "weak",
        promoter_holding_pct=fund.promoter_holding_pct,
        promoter_pledge_pct=fund.promoter_pledge_pct,
        institutional_pct=round(fund.fii_holding_pct + fund.dii_holding_pct, 2),
        quality_score=score,
        quality_band=band,
        strengths=strengths,
        concerns=concerns,
        insufficient=insufficient,
    )


def percentile_rank(values: list[float], value: float) -> float:
    """Percentile of ``value`` inside a peer ``values`` list (0-100)."""
    clean = [v for v in values if v is not None]
    if not clean:
        return 50.0
    below = sum(1 for v in clean if v < value)
    equal = sum(1 for v in clean if v == value)
    return round((below + 0.5 * equal) / len(clean) * 100, 1)


def average(values) -> float | None:
    clean = [v for v in values if v is not None]
    return mean(clean) if clean else None
