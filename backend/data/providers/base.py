"""Provider contract for all upstream data.

A provider never returns a value without provenance. If a provider cannot get
real data it must raise :class:`ProviderUnavailable` — it must **not** return
zeros, nulls dressed as numbers, or invented values. The registry then decides
whether to fail the request or fall back to another configured provider, and the
fallback is always labelled in the response.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from backend.core.provenance import DatasetMeta, Provenance

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class Series:
    """A price/fundamental series plus its provenance."""

    symbol: str
    frame: pd.DataFrame
    meta: DatasetMeta
    timeframe: str = "1d"

    def __post_init__(self) -> None:
        missing = [c for c in OHLCV_COLUMNS if c not in self.frame.columns]
        if missing:
            raise ValueError(f"{self.symbol}: OHLCV frame missing {missing}")
        if not isinstance(self.frame.index, pd.DatetimeIndex):
            raise ValueError(f"{self.symbol}: frame index must be a DatetimeIndex")
        self.frame = self.frame.sort_index()

    def __len__(self) -> int:
        return len(self.frame)


@dataclass
class Quote:
    symbol: str
    last_price: float
    change: float
    change_pct: float
    day_open: float
    day_high: float
    day_low: float
    prev_close: float
    volume: int
    week52_high: float
    week52_low: float
    provenance: Provenance
    as_of: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AnnualFinancials:
    fiscal_year: str  # e.g. "FY24"
    period_end: date
    revenue: float
    ebitda: float
    ebit: float
    pat: float
    eps: float
    total_debt: float
    cash: float
    equity: float
    total_assets: float
    cfo: float
    capex: float
    receivables: float
    inventory: float
    payables: float
    interest_expense: float
    dividend_per_share: float
    shares_outstanding: float

    @property
    def fcf(self) -> float:
        return self.cfo - self.capex

    @property
    def net_debt(self) -> float:
        return self.total_debt - self.cash


@dataclass
class QuarterlyFinancials:
    period: str  # e.g. "Q2 FY25"
    period_end: date
    revenue: float
    ebitda: float
    pat: float
    eps: float
    cfo: float = 0.0


@dataclass
class Fundamentals:
    """Raw fundamentals bundle. All monetary values in INR crore."""

    symbol: str
    company_name: str
    sector: str
    industry: str
    market_cap: float
    shares_outstanding: float
    annual: list[AnnualFinancials]
    quarterly: list[QuarterlyFinancials]
    promoter_holding_pct: float
    promoter_pledge_pct: float
    fii_holding_pct: float
    dii_holding_pct: float
    retail_holding_pct: float
    auditor_changes_5y: int
    auditor_qualification: str | None
    related_party_txn_pct_revenue: float
    contingent_liabilities_pct_equity: float
    equity_dilution_pct_3y: float
    dividend_payout_pct: float
    provenance: Provenance
    red_flag_notes: list[str] = field(default_factory=list)

    @property
    def latest(self) -> AnnualFinancials:
        return self.annual[-1]

    @property
    def fiscal_years(self) -> list[str]:
        return [a.fiscal_year for a in self.annual]


@dataclass
class NewsItem:
    headline: str
    published_at: datetime
    source: str
    url: str | None
    category: str  # earnings | regulatory | corporate | macro | sector
    kind: str  # FACT | OPINION
    summary: str
    sentiment: float  # -1 .. +1
    provenance: Provenance


@dataclass
class OptionChainRow:
    strike: float
    call_oi: int
    call_change_oi: int
    call_iv: float
    call_volume: int
    call_ltp: float
    call_delta: float
    call_gamma: float
    call_theta: float
    call_vega: float
    put_oi: int
    put_change_oi: int
    put_iv: float
    put_volume: int
    put_ltp: float
    put_delta: float
    put_gamma: float
    put_theta: float
    put_vega: float


@dataclass
class OptionChain:
    symbol: str
    spot: float
    expiry: date
    rows: list[OptionChainRow]
    meta: DatasetMeta
    lot_size: int = 0


class MarketDataProvider(ABC):
    """Everything the platform needs from an upstream source."""

    name: str = "abstract"
    #: True when values are generated rather than observed.
    is_synthetic: bool = False

    @abstractmethod
    def get_history(
        self, symbol: str, *, timeframe: str = "1d", lookback: int = 750
    ) -> Series: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_fundamentals(self, symbol: str) -> Fundamentals: ...

    @abstractmethod
    def get_news(self, symbol: str, limit: int = 12) -> list[NewsItem]: ...

    def get_option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        raise NotImplementedError(f"{self.name} does not provide option chains")

    def health(self) -> dict[str, object]:
        return {"provider": self.name, "is_synthetic": self.is_synthetic, "healthy": True}
