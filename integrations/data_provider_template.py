"""Template for a read-only market data provider.

Copy to ``backend/data/providers/<vendor>.py`` and implement what the vendor
actually serves. Anything you do not implement must raise ``ProviderUnavailable``
with a specific reason — a research platform that guesses is worse than one that
says "unknown".

The registry will record ``meta`` on every value, so the provenance fields are
not decoration: they decide the data-quality score, the agent confidence cap and
the committee's classification ceiling.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from backend.core.errors import ProviderUnavailable
from backend.core.provenance import DatasetMeta, Freshness, Verification
from backend.data.providers.base import (
    Fundamentals,
    MarketDataProvider,
    NewsItem,
    OptionChain,
    Quote,
    Series,
)


class ExampleProvider(MarketDataProvider):
    name = "example-vendor"
    #: False for a real vendor, True only for the synthetic engine.
    is_synthetic = False

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout

    # ------------------------------------------------------------- helpers
    def _unavailable(self, what: str) -> ProviderUnavailable:
        return ProviderUnavailable(
            f"{self.name}: {what} is not implemented. Refusing to fabricate data — "
            "run with BTI_DATA_MODE=demo or add the endpoint."
        )

    # ---------------------------------------------------------------- data
    def get_history(
        self, symbol: str, *, timeframe: str = "1d", lookback: int = 750
    ) -> Series:
        frame = self._fetch_ohlcv(symbol, timeframe, lookback)  # your code
        return Series(
            symbol=symbol,
            frame=frame,
            meta=DatasetMeta(
                source=f"{self.name}/history",
                exchange="NSE",
                freshness=Freshness.EOD,
                verification=Verification.VERIFIED_PRIMARY,
                rows=len(frame),
                period_start=frame.index[0].date(),
                period_end=frame.index[-1].date(),
                market_timestamp=datetime.combine(frame.index[-1].date(), datetime.min.time()),
                notes=["Official end-of-day values."],
            ),
            timeframe=timeframe,
        )

    def get_quote(self, symbol: str) -> Quote:
        quote = self._fetch_quote(symbol)  # your code
        # If the vendor's quote is delayed, say so. If you do not know, mark it
        # Freshness.UNKNOWN and accept the 15-point quality penalty.
        quote.meta = DatasetMeta(
            source=f"{self.name}/quote",
            exchange="NSE",
            freshness=Freshness.DELAYED,
            verification=Verification.VERIFIED_SECONDARY,
            notes=["Vendor indicates a 15-minute delay."],
        )
        return quote

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        raise self._unavailable("annual/quarterly statements")

    def get_news(self, symbol: str, limit: int = 12) -> list[NewsItem]:
        raise self._unavailable("news")

    def get_option_chain(self, symbol: str, expiry: date | None = None) -> OptionChain:
        raise self._unavailable("option chain")

    def health(self) -> dict[str, object]:
        return {"provider": self.name, "is_synthetic": False, "healthy": False,
                "error": "not configured"}

    # --------------------------------------------------------------- stubs
    def _fetch_ohlcv(self, symbol: str, timeframe: str, lookback: int) -> pd.DataFrame:
        raise self._unavailable("history endpoint")

    def _fetch_quote(self, symbol: str) -> Quote:
        raise self._unavailable("quote endpoint")
