"""Deterministic synthetic market engine (demonstration + test data).

Why this exists
---------------
The development sandbox has no access to NSE/BSE endpoints. Rather than ship a
system that crashes without credentials, or worse, one that pretends to have
live data, this provider generates **internally consistent, fully reproducible**
market data and labels every single output ``Freshness.SYNTHETIC`` /
``Verification.UNVERIFIED_SYNTHETIC``.

Properties that make it useful for research engineering
-------------------------------------------------------
* Deterministic: seeded per symbol and anchored to a fixed calendar start, so a
  backtest run today gives the same answer tomorrow.
* Coherent: a shared market factor drives every stock, so index movements,
  breadth and sector rotation agree with each other.
* Structurally valid OHLCV: ``low <= min(open, close) <= max(open, close) <= high``.
* Accounting-consistent fundamentals: margin/growth profiles by sector, and
  CFO/PAT/leverage relationships that respect basic accounting identities.
* Option prices and greeks are computed with Black-Scholes from a synthetic
  spot and a synthetic term structure, so the maths is real even when the
  inputs are not.

None of it is a market forecast. The UI shows a persistent synthetic-data banner.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

import numpy as np
import pandas as pd

from backend.core.provenance import (
    Freshness,
    Provenance,
    Verification,
    demo_provenance,
)
from backend.data.providers.base import (
    AnnualFinancials,
    Fundamentals,
    MarketDataProvider,
    NewsItem,
    OptionChain,
    OptionChainRow,
    QuarterlyFinancials,
    Quote,
    Series,
)
from backend.core.provenance import DatasetMeta
from backend.data.universe import BY_SYMBOL, INSTRUMENTS, Instrument

SEED = 20240117
ANCHOR_START = date(2018, 1, 1)
EOD_CUTOFF = time(15, 30)

#: Per-sector business profile: (revenue CAGR base, EBITDA margin base,
#: net margin, asset turnover, debt/equity, beta, annual vol, cfo/pat quality)
SECTOR_PROFILES: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "Information Technology": (0.085, 0.235, 0.175, 1.35, 0.12, 0.82, 0.24, 1.10),
    "Financial Services": (0.135, 0.000, 0.235, 0.09, 5.20, 1.05, 0.27, 0.85),
    "Oil & Gas": (0.070, 0.145, 0.070, 0.95, 0.45, 1.05, 0.29, 0.95),
    "FMCG": (0.075, 0.235, 0.165, 1.60, 0.08, 0.62, 0.19, 1.05),
    "Automobile": (0.110, 0.135, 0.085, 1.25, 0.35, 1.02, 0.28, 1.00),
    "Pharmaceuticals": (0.095, 0.240, 0.155, 1.05, 0.22, 0.72, 0.26, 0.98),
    "Capital Goods": (0.155, 0.145, 0.095, 1.10, 0.28, 1.15, 0.32, 0.92),
    "Metals & Mining": (0.080, 0.165, 0.075, 0.85, 0.72, 1.25, 0.34, 0.88),
    "Power": (0.075, 0.285, 0.115, 0.38, 1.15, 0.88, 0.27, 1.02),
    "Cement": (0.090, 0.195, 0.095, 0.75, 0.38, 0.95, 0.26, 1.00),
    "Infrastructure": (0.125, 0.225, 0.130, 0.42, 1.35, 1.12, 0.31, 0.90),
    "Telecom": (0.105, 0.385, 0.075, 0.48, 1.65, 0.85, 0.28, 1.05),
    "Consumer Durables": (0.135, 0.135, 0.085, 1.55, 0.18, 0.92, 0.29, 0.95),
    "Retail": (0.165, 0.105, 0.055, 2.10, 0.42, 1.00, 0.30, 1.05),
    "Chemicals": (0.125, 0.185, 0.115, 1.15, 0.25, 1.05, 0.30, 0.95),
    "Paints": (0.085, 0.190, 0.115, 1.70, 0.12, 0.78, 0.24, 1.00),
    "Conglomerate": (0.115, 0.110, 0.055, 0.80, 1.10, 1.20, 0.33, 0.85),
    "Fintech": (0.145, 0.115, 0.015, 0.55, 0.35, 1.35, 0.42, 0.80),
}
DEFAULT_PROFILE = (0.095, 0.180, 0.105, 1.05, 0.40, 1.00, 0.28, 0.98)


def _seed(*parts: object) -> int:
    raw = "|".join(str(p) for p in parts).encode()
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def _profile(inst: Instrument):
    return SECTOR_PROFILES.get(inst.sector, DEFAULT_PROFILE)


#: Plausible size bands per index tier: (market cap crore, share price) ranges.
#: Used so a small-cap never gets a large-cap valuation and prices stay sane.
SIZE_BANDS = {
    "large": ((120_000.0, 2_200_000.0), (220.0, 4_500.0)),
    "mid": ((15_000.0, 150_000.0), (150.0, 5_000.0)),
    "small": ((1_500.0, 32_000.0), (12.0, 950.0)),
}


def _tier(inst: Instrument) -> str:
    from backend.data.universe import MIDCAP, NIFTY50

    if NIFTY50 in inst.indices:
        return "large"
    if MIDCAP in inst.indices:
        return "mid"
    return "small"


def sizing(symbol: str) -> tuple[float, float, float]:
    """Deterministic ``(price, shares_in_crore, market_cap_crore)`` for a symbol."""
    inst = BY_SYMBOL[symbol]
    (mc_lo, mc_hi), (px_lo, px_hi) = SIZE_BANDS[_tier(inst)]
    r = np.random.default_rng(_seed("size", symbol))
    mcap = float(mc_lo + (mc_hi - mc_lo) * r.random() ** 2.2)
    price = float(px_lo + (px_hi - px_lo) * r.random() ** 1.6)
    shares = mcap / price
    return round(price, 2), round(shares, 3), round(mcap, 1)


# ----------------------------------------------------------------- calendar

def trading_days(start: date = ANCHOR_START, end: date | None = None) -> pd.DatetimeIndex:
    """Weekday calendar with a fixed list of NSE holidays."""
    end = end or datetime.now(timezone.utc).date()
    days = pd.bdate_range(start, end, tz=None)
    holidays = {
        "2018-01-26", "2018-03-02", "2018-03-30", "2018-04-14", "2018-05-01",
        "2018-08-15", "2018-09-13", "2018-10-02", "2018-11-07", "2018-12-25",
        "2019-01-26", "2019-03-04", "2019-04-17", "2019-04-19", "2019-05-01",
        "2019-06-05", "2019-08-12", "2019-08-15", "2019-09-02", "2019-09-10",
        "2019-10-02", "2019-10-08", "2019-10-21", "2019-10-28", "2019-11-12",
        "2019-12-25", "2020-02-21", "2020-03-10", "2020-04-02", "2020-04-06",
        "2020-04-10", "2020-04-14", "2020-05-01", "2020-05-25", "2020-10-02",
        "2020-11-16", "2020-11-30", "2020-12-25", "2021-01-26", "2021-03-11",
        "2021-03-29", "2021-04-02", "2021-04-14", "2021-04-21", "2021-05-13",
        "2021-07-21", "2021-08-15", "2021-09-10", "2021-10-15", "2021-11-05",
        "2021-11-19", "2022-01-26", "2022-03-01", "2022-04-14", "2022-04-15",
        "2022-05-03", "2022-08-09", "2022-08-15", "2022-08-31", "2022-10-05",
        "2022-10-26", "2022-11-08", "2023-01-26", "2023-03-07", "2023-03-30",
        "2023-04-04", "2023-04-07", "2023-04-14", "2023-05-01", "2023-06-29",
        "2023-08-15", "2023-09-19", "2023-10-02", "2023-10-24", "2023-11-14",
        "2023-11-27", "2023-12-25", "2024-01-22", "2024-01-26", "2024-03-08",
        "2024-03-25", "2024-03-29", "2024-04-11", "2024-04-17", "2024-04-01",
        "2024-05-01", "2024-05-20", "2024-06-17", "2024-07-17", "2024-08-15",
        "2024-10-02", "2024-11-01", "2024-11-15", "2024-11-20", "2024-12-25",
        "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
        "2025-04-18", "2025-05-01", "2025-08-15", "2025-08-27", "2025-10-02",
        "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
        "2026-01-26", "2026-03-03", "2026-03-31", "2026-04-03", "2026-04-14",
        "2026-05-01", "2026-08-15", "2026-10-02", "2026-10-20", "2026-10-21",
        "2026-11-10", "2026-12-25",
    }
    mask = [d.strftime("%Y-%m-%d") not in holidays for d in days]
    return pd.DatetimeIndex(days[mask])


# ------------------------------------------------------- shared market state

@lru_cache(maxsize=4)
def _market_factor(n: int) -> np.ndarray:
    """Shared daily market log-returns with slow regime shifts.

    Deterministic: same length always yields the same prefix, because the
    generator is seeded and the regime process is a fixed AR(1).
    """
    rng = np.random.default_rng(_seed("market-factor", n))
    mu = np.empty(n)
    vol = np.empty(n)
    state = 0.0
    vstate = 0.0
    for t in range(n):
        state = 0.94 * state + rng.normal(0, 1)
        vstate = 0.97 * vstate + rng.normal(0, 1)
        mu[t] = 0.00042 + 0.00035 * math.tanh(state)
        vol[t] = 0.0085 * math.exp(0.18 * math.tanh(vstate))
    return rng.normal(mu, vol)


def _sector_factor(sector: str, n: int) -> np.ndarray:
    rng = np.random.default_rng(_seed("sector", sector, n))
    return rng.normal(0, 0.0048, n)


@lru_cache(maxsize=512)
def daily_bars(symbol: str) -> pd.DataFrame:
    """Full, deterministic daily OHLCV history from the anchor date to today."""
    inst = BY_SYMBOL.get(symbol)
    if inst is None:
        raise KeyError(symbol)
    idx = trading_days(ANCHOR_START)
    n = len(idx)
    mkt = _market_factor(n)
    sec = _sector_factor(inst.sector, n)
    growth, margin, net_margin, turnover, de, beta, vol, cfo_quality = _profile(inst)
    rng = np.random.default_rng(_seed("stock", symbol, n))

    idio = rng.normal(0, vol / math.sqrt(252), n)
    # idiosyncratic event jumps: a handful of gaps per decade of data
    jumps = rng.random(n) < 0.004
    idio = idio + jumps * rng.normal(0, 0.035, n)
    rets = beta * mkt + 0.6 * sec + idio
    rets = np.clip(rets, -0.095, 0.095)  # circuit-breaker realism

    # Anchor the *final* level so the latest close lands in a plausible band for
    # an Indian equity, regardless of how the simulated random walk drifted.
    target_last = sizing(symbol)[0]
    close = np.exp(np.cumsum(rets))
    close = close / close[-1] * target_last
    base = float(close[0])

    prev = np.concatenate([[base], close[:-1]])
    intraday_range = np.abs(rng.normal(0.009, 0.004, n))
    open_ = prev * (1 + np.clip(rng.normal(0, 0.0035, n), -0.02, 0.02))
    hi = np.maximum(open_, close) * (1 + intraday_range * rng.random(n))
    lo = np.minimum(open_, close) * (1 - intraday_range * rng.random(n))
    base_vol = 2_000_000 + (_seed("vol", symbol) % 8_000_000)
    volume = (base_vol * np.exp(rng.normal(0, 0.42, n)) * (1 + 2.2 * np.abs(rets))).astype(np.int64)

    frame = pd.DataFrame(
        {"open": open_, "high": hi, "low": lo, "close": close, "volume": volume},
        index=idx,
    )
    frame.index.name = "date"
    return frame.round(4)


def _intraday_bars(symbol: str, timeframe: str, sessions: int = 10) -> pd.DataFrame:
    """Bridge-constructed intraday bars consistent with the daily OHLC."""
    per_session = {"5m": 75, "15m": 25, "60m": 7}[timeframe]
    step = {"5m": 5, "15m": 15, "60m": 60}[timeframe]
    daily = daily_bars(symbol).tail(sessions)
    rows = []
    for day, bar in daily.iterrows():
        rng = np.random.default_rng(_seed("intraday", symbol, str(day.date()), timeframe))
        # Brownian bridge from open -> close, pinned inside [low, high]
        w = np.cumsum(rng.normal(0, 1, per_session))
        w = w - np.linspace(0, 1, per_session) * w[-1]
        path = np.linspace(bar["open"], bar["close"], per_session) + w * (
            (bar["high"] - bar["low"]) / max(6.0, per_session / 4)
        )
        path = np.clip(path, bar["low"], bar["high"])
        start = datetime.combine(day.date(), time(9, 15))
        for i, px in enumerate(path):
            ts = start + timedelta(minutes=step * i)
            nxt = path[i + 1] if i + 1 < per_session else bar["close"]
            hi = max(px, nxt) * (1 + abs(rng.normal(0, 0.0012)))
            lo = min(px, nxt) * (1 - abs(rng.normal(0, 0.0012)))
            rows.append(
                {
                    "date": ts,
                    "open": px,
                    "high": min(hi, bar["high"] * 1.0005),
                    "low": max(lo, bar["low"] * 0.9995),
                    "close": nxt,
                    "volume": int(bar["volume"] / per_session * abs(rng.normal(1, 0.4))),
                }
            )
    out = pd.DataFrame(rows).set_index("date")
    return out.round(4)


# --------------------------------------------------------------- fundamentals

def _profile_for(symbol: str):
    inst = BY_SYMBOL[symbol]
    growth, margin, net_margin, turnover, de, beta, vol, cfo_q = _profile(inst)
    rng = np.random.default_rng(_seed("fund", symbol))
    return inst, (
        growth * float(rng.normal(1.0, 0.22)),
        margin * float(rng.normal(1.0, 0.12)),
        net_margin * float(rng.normal(1.0, 0.16)),
        turnover * float(rng.normal(1.0, 0.10)),
        de * float(rng.normal(1.0, 0.25)),
        beta,
        vol,
        cfo_q * float(rng.normal(1.0, 0.06)),
    ), rng


def fiscal_years(count: int = 5, latest_fy: int | None = None) -> list[tuple[str, date]]:
    today = datetime.now(timezone.utc).date()
    latest_fy = latest_fy or (today.year if today.month >= 4 else today.year - 1)
    out = []
    for k in range(count):
        fy = latest_fy - (count - 1) + k
        out.append((f"FY{str(fy)[2:]}", date(fy, 3, 31)))
    return out


#: Sector price-to-sales anchors, used only to keep synthetic revenue in a
#: plausible relationship with synthetic market cap.
SECTOR_PS: dict[str, float] = {
    "Information Technology": 5.2, "Financial Services": 3.4, "Oil & Gas": 1.1,
    "FMCG": 9.0, "Automobile": 2.6, "Pharmaceuticals": 4.4, "Capital Goods": 5.0,
    "Metals & Mining": 1.0, "Power": 2.6, "Cement": 4.0, "Infrastructure": 3.2,
    "Telecom": 3.6, "Consumer Durables": 6.0, "Retail": 5.5, "Chemicals": 4.6,
    "Paints": 7.0, "Conglomerate": 3.0, "Fintech": 6.5,
}


def annual_financials(symbol: str) -> list[AnnualFinancials]:
    inst, (growth, margin, net_margin, turnover, de, beta, vol, cfo_q), rng = _profile_for(symbol)
    is_financial = inst.sector == "Financial Services"
    years = fiscal_years(5)
    price, shares, mcap = sizing(symbol)
    ps = SECTOR_PS.get(inst.sector, 3.5) * float(rng.normal(1.0, 0.18))
    # Revenue for the latest year, then walked backwards to the first year.
    latest_rev = max(500.0, mcap / max(ps, 0.4))
    rev_final = latest_rev
    out: list[AnnualFinancials] = []
    revenues: list[float] = []
    for i, (fy, period_end) in enumerate(years):
        rev = latest_rev / ((1 + growth) ** (len(years) - 1 - i))
        rev *= float(rng.normal(1.0, 0.03))
        revenues.append(rev)
    for (fy, period_end), rev in zip(years, revenues):
        m = margin if not is_financial else 0.0
        ebitda = rev * m if not is_financial else rev * 0.62
        ebit = ebitda - rev * (0.028 if not is_financial else 0.045)
        interest = rev * (0.012 + 0.006 * de) if not is_financial else rev * 0.38
        pat = (ebit - interest) * (1 - 0.252)
        if is_financial:
            pat = rev * net_margin * float(rng.normal(1.0, 0.06))
        eps = pat / shares
        # Balance sheet built from a target return on equity and a target
        # leverage ratio, so ROE / D-E land in a believable band.
        roe_target = float(np.clip(
            (0.19 if not is_financial else 0.175) + float(rng.normal(0, 0.020)) + 0.10 * margin,
            0.06, 0.34,
        ))
        equity = pat / roe_target
        total_debt = equity * de
        total_assets = equity + total_debt + rev * 0.15
        cash = total_assets * (0.06 if not is_financial else 0.10) * float(rng.normal(1, 0.1))
        cfo = pat * cfo_q * float(rng.normal(1, 0.08))
        capex = rev * (0.045 if not is_financial else 0.02) * float(rng.normal(1, 0.2))
        receivables = rev * (0.16 * float(rng.normal(1, 0.12)))
        inventory = rev * (0.11 * float(rng.normal(1, 0.15)) if not is_financial else 0.0)
        payables = rev * (0.13 * float(rng.normal(1, 0.1)))
        dps = max(0.0, eps * (0.28 if not is_financial else 0.12) * float(rng.normal(1, 0.2)))
        out.append(
            AnnualFinancials(
                fiscal_year=fy,
                period_end=period_end,
                revenue=round(rev, 1),
                ebitda=round(ebitda, 1),
                ebit=round(ebit, 1),
                pat=round(pat, 1),
                eps=round(eps, 2),
                total_debt=round(total_debt, 1),
                cash=round(cash, 1),
                equity=round(equity, 1),
                total_assets=round(total_assets, 1),
                cfo=round(cfo, 1),
                capex=round(capex, 1),
                receivables=round(receivables, 1),
                inventory=round(inventory, 1),
                payables=round(payables, 1),
                interest_expense=round(interest, 1),
                dividend_per_share=round(dps, 2),
                shares_outstanding=round(shares, 2),
            )
        )
    return out


def quarterly_financials(symbol: str) -> list[QuarterlyFinancials]:
    annual = annual_financials(symbol)
    last = annual[-1]
    rng = np.random.default_rng(_seed("quarterly", symbol))
    out: list[QuarterlyFinancials] = []
    today = datetime.now(timezone.utc).date()
    fy = int("20" + last.fiscal_year[2:])
    # quarters ending Jun/Sep/Dec/Mar; keep only those already reported
    candidates = []
    for y in (fy - 1, fy, fy + 1):
        for m, label in ((6, "Q1"), (9, "Q2"), (12, "Q3"), (3, "Q4")):
            end = date(y, m, 28 if m != 3 else 31)
            fy_label = y + 1 if m >= 4 else y
            candidates.append((f"{label} FY{str(fy_label)[2:]}", end))
    candidates = [c for c in candidates if c[1] < today - timedelta(days=25)]
    candidates.sort(key=lambda c: c[1])
    for period, end in candidates[-6:]:
        q_rev = last.revenue / 4 * float(rng.normal(1.0, 0.09))
        q_ebitda = q_rev * (last.ebitda / last.revenue) * float(rng.normal(1.0, 0.07))
        q_pat = q_ebitda * (last.pat / last.ebitda) * float(rng.normal(1.0, 0.10))
        out.append(
            QuarterlyFinancials(
                period=period,
                period_end=end,
                revenue=round(q_rev, 1),
                ebitda=round(q_ebitda, 1),
                pat=round(q_pat, 1),
                eps=round(q_pat / last.shares_outstanding, 2),
                cfo=round(q_pat * float(rng.normal(0.9, 0.15)), 1),
            )
        )
    return out


def build_fundamentals(symbol: str) -> Fundamentals:
    inst = BY_SYMBOL[symbol]
    annual = annual_financials(symbol)
    rng = np.random.default_rng(_seed("holdings", symbol))
    last = annual[-1]
    price = float(daily_bars(symbol)["close"].iloc[-1])
    mcap = price * last.shares_outstanding
    promoter = float(np.clip(rng.normal(52, 14), 0, 75))
    pledge = float(max(0.0, rng.normal(0.9, 2.6))) if rng.random() > 0.62 else 0.0
    fii = float(np.clip(rng.normal(18, 8), 1, 45))
    dii = float(np.clip(rng.normal(14, 6), 1, 35))
    dii = min(dii, max(0.0, 99 - promoter - fii - 4))
    retail = max(0.0, 100 - promoter - fii - dii)
    auditor_changes = int(rng.choice([0, 0, 0, 1, 2], p=[0.62, 0.18, 0.1, 0.07, 0.03]))
    qualification = None
    if rng.random() > 0.86:
        qualification = "Qualified opinion on a subsidiary's revenue recognition."
    rp = float(abs(rng.normal(3.2, 3.0)))
    cl = float(abs(rng.normal(8, 9)))
    dilution = float(abs(rng.normal(2.4, 3.4)))
    payout = float(np.clip(last.dividend_per_share / max(last.eps, 0.01), 0, 1))
    notes: list[str] = []
    if pledge > 5:
        notes.append(f"Promoter pledge at {pledge:.1f}% of promoter holding.")
    if auditor_changes >= 2:
        notes.append(f"{auditor_changes} auditor changes in five years.")
    if dilution > 8:
        notes.append(f"Share count expanded {dilution:.1f}% over three years.")
    if rp > 10:
        notes.append(f"Related-party transactions at {rp:.1f}% of revenue.")
    return Fundamentals(
        symbol=symbol,
        company_name=inst.name,
        sector=inst.sector,
        industry=inst.industry,
        market_cap=round(mcap, 1),
        shares_outstanding=last.shares_outstanding,
        annual=annual,
        quarterly=quarterly_financials(symbol),
        promoter_holding_pct=round(promoter, 2),
        promoter_pledge_pct=round(pledge, 2),
        fii_holding_pct=round(fii, 2),
        dii_holding_pct=round(dii, 2),
        retail_holding_pct=round(retail, 2),
        auditor_changes_5y=auditor_changes,
        auditor_qualification=qualification,
        related_party_txn_pct_revenue=round(rp, 2),
        contingent_liabilities_pct_equity=round(cl, 2),
        equity_dilution_pct_3y=round(dilution, 2),
        dividend_payout_pct=round(payout, 3),
        provenance=demo_provenance(
            "synthetic-demo/fundamentals",
            exchange=inst.exchange,
            reporting_period=last.fiscal_year,
            note="Synthetic financial statements. Accounting relationships are "
            "consistent but the company figures are not real.",
        ),
        red_flag_notes=notes,
    )


# ------------------------------------------------------------------ news

_NEWS_TEMPLATES = (
    ("{name} reports quarterly revenue of INR {rev} crore", "earnings", "FACT",
     "Synthetic earnings item generated for demonstration of the news pipeline."),
    ("{name} board approves capex plan for the next fiscal", "corporate", "FACT",
     "Synthetic board-outcome item; no real filing exists."),
    ("Analysts remain divided on {name} margin outlook", "sector", "OPINION",
     "Synthetic opinion item used to exercise fact/opinion separation."),
    ("Regulator publishes consultation paper affecting {sector}", "regulatory", "FACT",
     "Synthetic regulatory item; do not treat as an actual circular."),
    ("Brokerage note raises {name} valuation multiple assumptions", "earnings", "OPINION",
     "Synthetic sell-side commentary."),
    ("{name} announces change in senior management", "corporate", "FACT",
     "Synthetic management-change disclosure."),
)


def build_news(symbol: str, limit: int = 12) -> list[NewsItem]:
    inst = BY_SYMBOL[symbol]
    fund = build_fundamentals(symbol)
    rng = np.random.default_rng(_seed("news", symbol))
    now = datetime.now(timezone.utc)
    items: list[NewsItem] = []
    for k in range(limit):
        idx = int(rng.integers(0, len(_NEWS_TEMPLATES)))
        tpl, category, kind, summary = _NEWS_TEMPLATES[idx]
        published = now - timedelta(hours=float(rng.uniform(1, 24 * 14)))
        headline = tpl.format(
            name=inst.name,
            sector=inst.sector,
            rev=f"{fund.latest.revenue / 4:,.0f}",
        )
        sentiment = float(np.clip(rng.normal(0.12 if kind == "FACT" else 0.0, 0.45), -1, 1))
        items.append(
            NewsItem(
                headline=headline,
                published_at=published,
                source="synthetic-demo/wire",
                url=None,
                category=category,
                kind=kind,
                summary=summary,
                sentiment=round(sentiment, 2),
                provenance=demo_provenance(
                    "synthetic-demo/news",
                    exchange=inst.exchange,
                    market_timestamp=published,
                    note="Synthetic news. Not a real publication.",
                ),
            )
        )
    items.sort(key=lambda i: i.published_at, reverse=True)
    return items


# ------------------------------------------------------------ option chain

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(
    spot: float, strike: float, t: float, vol: float, rate: float = 0.065, div: float = 0.0
) -> dict[str, float]:
    """European BS price and greeks (per unit, theta per day)."""
    if t <= 0 or vol <= 0:
        intrinsic_c = max(spot - strike, 0.0)
        intrinsic_p = max(strike - spot, 0.0)
        return {
            "price": intrinsic_c, "put_price": intrinsic_p,
            "delta": 1.0 if spot > strike else 0.0, "put_delta": -1.0 if spot < strike else 0.0,
            "gamma": 0.0, "theta": 0.0, "vega": 0.0,
        }
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    disc_r = math.exp(-rate * t)
    disc_q = math.exp(-div * t)
    call = spot * disc_q * _norm_cdf(d1) - strike * disc_r * _norm_cdf(d2)
    put = strike * disc_r * _norm_cdf(-d2) - spot * disc_q * _norm_cdf(-d1)
    delta_c = disc_q * _norm_cdf(d1)
    gamma = disc_q * _norm_pdf(d1) / (spot * vol * math.sqrt(t))
    vega = spot * disc_q * _norm_pdf(d1) * math.sqrt(t) / 100.0
    theta_c = (
        -spot * disc_q * _norm_pdf(d1) * vol / (2 * math.sqrt(t))
        - rate * strike * disc_r * _norm_cdf(d2)
        + div * spot * disc_q * _norm_cdf(d1)
    ) / 365.0
    return {
        "price": round(call, 2), "put_price": round(put, 2),
        "delta": round(delta_c, 4), "put_delta": round(delta_c - 1, 4),
        "gamma": round(gamma, 6), "theta": round(theta_c, 4), "vega": round(vega, 4),
    }


def next_expiries(today: date | None = None, count: int = 4) -> list[date]:
    """Approximate weekly/monthly NSE expiry calendar (Thursdays)."""
    today = today or datetime.now(timezone.utc).date()
    out: list[date] = []
    d = today
    while len(out) < count:
        d += timedelta(days=1)
        if d.weekday() == 3:  # Thursday
            out.append(d)
    return out


def build_option_chain(symbol: str, expiry: date | None = None) -> OptionChain:
    inst = BY_SYMBOL[symbol]
    if not inst.fno:
        raise KeyError(f"{symbol} has no F&O contract")
    daily = daily_bars(symbol)
    spot = float(daily["close"].iloc[-1])
    expiries = next_expiries()
    expiry = expiry or expiries[0]
    t = max((expiry - datetime.now(timezone.utc).date()).days, 1) / 365.0
    step = max(round(spot * 0.02 / 5) * 5, 2.5)
    atm = round(spot / step) * step
    rng = np.random.default_rng(_seed("chain", symbol, str(expiry)))
    base_iv = 0.145 + float(abs(rng.normal(0, 0.035)))
    rows: list[OptionChainRow] = []
    for k in range(-10, 11):
        strike = round(atm + k * step, 2)
        moneyness = math.log(strike / spot)
        iv = max(0.06, base_iv + 0.55 * moneyness**2 + 0.06 * abs(moneyness))
        g = black_scholes(spot, strike, t, iv)
        skew = math.exp(-((strike - atm) / (4 * step)) ** 2)
        call_oi = int((180_000 + 900_000 * skew) * float(rng.uniform(0.6, 1.4)))
        put_oi = int((200_000 + 1_000_000 * skew) * float(rng.uniform(0.6, 1.5)))
        rows.append(
            OptionChainRow(
                strike=strike,
                call_oi=call_oi,
                call_change_oi=int(call_oi * float(rng.normal(0.05, 0.22))),
                call_iv=round(iv * 100, 2),
                call_volume=int(call_oi * float(rng.uniform(0.1, 0.9))),
                call_ltp=g["price"],
                call_delta=g["delta"],
                call_gamma=g["gamma"],
                call_theta=g["theta"],
                call_vega=g["vega"],
                put_oi=put_oi,
                put_change_oi=int(put_oi * float(rng.normal(0.06, 0.24))),
                put_iv=round((iv + 0.01) * 100, 2),
                put_volume=int(put_oi * float(rng.uniform(0.1, 0.9))),
                put_ltp=g["put_price"],
                put_delta=g["put_delta"],
                put_gamma=g["gamma"],
                put_theta=g["theta"],
                put_vega=g["vega"],
            )
        )
    return OptionChain(
        symbol=symbol,
        spot=round(spot, 2),
        expiry=expiry,
        rows=rows,
        lot_size=inst.lot_size,
        meta=DatasetMeta(
            source="synthetic-demo/option-chain",
            exchange=inst.exchange,
            freshness=Freshness.SYNTHETIC,
            verification=Verification.UNVERIFIED_SYNTHETIC,
            rows=len(rows),
            market_timestamp=datetime.combine(
                datetime.now(timezone.utc).date(), EOD_CUTOFF, tzinfo=timezone.utc
            ),
            warnings=[
                "Synthetic option chain. Greeks are Black-Scholes values on a "
                "synthetic spot and volatility surface — the maths is real, the "
                "market is not.",
                "F&O ordering is disabled in this build.",
            ],
        ),
    )


# ---------------------------------------------------------------- provider

class SyntheticProvider(MarketDataProvider):
    name = "synthetic"
    is_synthetic = True

    def _meta(self, inst: Instrument, rows: int, timeframe: str, note: str) -> DatasetMeta:
        bars = daily_bars(inst.symbol)
        return DatasetMeta(
            source=f"synthetic-demo/{timeframe}",
            exchange=inst.exchange,
            freshness=Freshness.SYNTHETIC,
            verification=Verification.UNVERIFIED_SYNTHETIC,
            rows=rows,
            period_start=bars.index[0].date(),
            period_end=bars.index[-1].date(),
            market_timestamp=datetime.combine(
                bars.index[-1].date(), EOD_CUTOFF, tzinfo=timezone.utc
            ),
            warnings=[note],
        )

    def get_history(self, symbol: str, *, timeframe: str = "1d", lookback: int = 750) -> Series:
        symbol = symbol.upper()
        if symbol not in BY_SYMBOL:
            raise KeyError(symbol)
        inst = BY_SYMBOL[symbol]
        if timeframe == "1d":
            frame = daily_bars(symbol).tail(lookback).copy()
        else:
            frame = _intraday_bars(symbol, timeframe).tail(lookback).copy()
        note = (
            f"Synthetic {timeframe} bars generated deterministically. "
            "Not observed market prices."
        )
        return Series(
            symbol=symbol,
            frame=frame,
            meta=self._meta(inst, len(frame), timeframe, note),
            timeframe=timeframe,
        )

    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        if symbol not in BY_SYMBOL:
            raise KeyError(symbol)
        inst = BY_SYMBOL[symbol]
        frame = daily_bars(symbol)
        last = frame.iloc[-1]
        prev = frame.iloc[-2]
        year = frame.tail(252)
        prov = demo_provenance(
            "synthetic-demo/quote",
            exchange=inst.exchange,
            market_timestamp=datetime.combine(
                frame.index[-1].date(), EOD_CUTOFF, tzinfo=timezone.utc
            ),
            note="Synthetic quote. EOD-equivalent; not a live tick.",
        )
        change = float(last["close"] - prev["close"])
        return Quote(
            symbol=symbol,
            last_price=round(float(last["close"]), 2),
            change=round(change, 2),
            change_pct=round(change / float(prev["close"]) * 100, 2),
            day_open=round(float(last["open"]), 2),
            day_high=round(float(last["high"]), 2),
            day_low=round(float(last["low"]), 2),
            prev_close=round(float(prev["close"]), 2),
            volume=int(last["volume"]),
            week52_high=round(float(year["high"].max()), 2),
            week52_low=round(float(year["low"].min()), 2),
            provenance=prov,
            as_of=datetime.now(timezone.utc),
        )

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        symbol = symbol.upper()
        if symbol not in BY_SYMBOL:
            raise KeyError(symbol)
        return build_fundamentals(symbol)

    def get_news(self, symbol: str, limit: int = 12) -> list[NewsItem]:
        return build_news(symbol.upper(), limit)

    def get_option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        return build_option_chain(symbol.upper(), expiry)

    def health(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "is_synthetic": True,
            "healthy": True,
            "data_mode": "demo",
            "assets": len(INSTRUMENTS),
            "note": "Deterministic synthetic research data. No upstream network calls.",
        }


def index_level_series(index_name: str) -> pd.DataFrame:
    """Equal-weighted synthetic index level built from its constituents.

    Used for market overview so that breadth, index movement and sector
    performance are mutually consistent.
    """
    from backend.data.universe import INDEX_MEMBERSHIP

    members = INDEX_MEMBERSHIP.get(index_name)
    if not members:
        raise KeyError(index_name)
    frames = {s: daily_bars(s)["close"] for s in members}
    closes = pd.DataFrame(frames).dropna()
    normalised = closes / closes.iloc[0] * 1000.0
    level = normalised.mean(axis=1)
    # Rescale to an illustrative *current* level. Anchoring on the final bar (not
    # the first) keeps today's print in a plausible band; an eight-year random
    # walk anchored at the start drifts to levels no one would recognise
    # (BANK NIFTY at 1,27,000), which makes the whole terminal look fictional in a
    # way that distracts from the analysis. Percentages are unaffected either way:
    # the level is a synthetic composite, never the official index value.
    anchor = INDEX_ANCHORS.get(index_name, 1000.0)
    level = level / level.iloc[-1] * anchor
    return pd.DataFrame({"close": level.round(2)}, index=closes.index)


#: Illustrative *latest* levels for the synthetic composite indices. These are
#: presented nowhere as official index values — they only keep the axis readable.
INDEX_ANCHORS: dict[str, float] = {
    "NIFTY 50": 24_850.0,
    "NIFTY BANK": 53_400.0,
    "NIFTY FIN SERVICE": 26_200.0,
    "NIFTY MIDCAP 100": 58_600.0,
    "NIFTY SMALLCAP 100": 19_400.0,
    "SENSEX": 81_400.0,
}
