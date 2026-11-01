"""NSE India provider (best-effort, read-only, no scraping bypass).

Status: **experimental and unverified in this environment.** The development
sandbox has no network route to ``www.nseindia.com``, so none of these code
paths could be exercised against the live site. The implementation is written
defensively and every failure surfaces as :class:`ProviderUnavailable` instead
of returning invented numbers.

What the operator must know
---------------------------
* NSE endpoints require a browser-like session (cookies from the homepage) and
  are rate limited. Do not poll aggressively.
* Mappings below are the documented public endpoints; their response shapes can
  change without notice. Any schema drift raises rather than silently coercing.
* Only EOD/quote data is fetched here. Financial statements, filings and
  holdings would need the corporate-filings XBRL feed, which is **not**
  implemented. Those calls therefore raise, and the registry falls back to the
  synthetic provider with an explicit warning.
* This module never posts, orders or authenticates against a broker.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pandas as pd

from backend.core.errors import ProviderUnavailable
from backend.core.logging import get_logger
from backend.core.provenance import DatasetMeta, Freshness, Provenance, Verification
from backend.data.providers.base import MarketDataProvider, Quote, Series
from backend.data.universe import BY_SYMBOL

log = get_logger("provider.nse")

BASE = "https://www.nseindia.com"
HOME = f"{BASE}/"
QUOTE_EP = f"{BASE}/api/quote-equity?symbol={{symbol}}"
HIST_EP = f"{BASE}/api/historical/cm/equity?symbol={{symbol}}&series=[%22EQ%22]&from={{start}}&to={{end}}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE}/get-quotes/equity?symbol=RELIANCE",
}


class NSEProvider(MarketDataProvider):
    name = "nse"
    is_synthetic = False

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self._session: Any | None = None

    # ------------------------------------------------------------ plumbing
    def _client(self):
        if self._session is not None:
            return self._session
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("httpx is not installed") from exc
        client = httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True)
        try:
            # NSE requires a session cookie established by the homepage.
            client.get(HOME)
        except Exception as exc:  # noqa: BLE001
            client.close()
            raise ProviderUnavailable(
                f"NSE unreachable ({exc.__class__.__name__}). No live data available.",
                details={"provider": "nse", "action": "fall back or use demo mode"},
            ) from exc
        self._session = client
        return client

    def _get_json(self, url: str) -> dict:
        client = self._client()
        try:
            resp = client.get(url)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                f"NSE request failed: {exc.__class__.__name__}. Live data not available."
            ) from exc
        if resp.status_code != 200:
            raise ProviderUnavailable(
                f"NSE returned HTTP {resp.status_code} for {url.split('?')[0]}",
                details={"status": resp.status_code},
            )
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                "NSE response was not JSON (likely an interstitial/anti-bot page). "
                "Refusing to guess a payload."
            ) from exc

    # --------------------------------------------------------------- data
    def get_history(self, symbol: str, *, timeframe: str = "1d", lookback: int = 750) -> Series:
        if timeframe != "1d":
            raise ProviderUnavailable(
                "NSE public endpoints used here only expose daily candles; "
                f"timeframe {timeframe!r} is unsupported by this provider."
            )
        symbol = symbol.upper()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=int(lookback * 1.55))
        payload = self._get_json(HIST_EP.format(symbol=symbol, start=start, end=end))
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not rows:
            raise ProviderUnavailable(f"NSE returned no historical rows for {symbol}")
        try:
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime([r["mTIMESTAMP"] for r in rows], format="%d-%b-%Y"),
                    "open": [float(r["CH_OPENING_PRICE"]) for r in rows],
                    "high": [float(r["CH_TRADE_HIGH_PRICE"]) for r in rows],
                    "low": [float(r["CH_TRADE_LOW_PRICE"]) for r in rows],
                    "close": [float(r["CH_CLOSING_PRICE"]) for r in rows],
                    "volume": [int(float(str(r["CH_TOT_TRADED_QTY"]).replace(",", ""))) for r in rows],
                }
            ).set_index("date").sort_index()
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(
                "NSE historical response schema did not match expectations; refusing "
                "to coerce values."
            ) from exc
        frame = frame.tail(lookback)
        module = BY_SYMBOL.get(symbol)
        return Series(
            symbol=symbol,
            frame=frame,
            meta=DatasetMeta(
                source="nse/api/historical",
                exchange="NSE",
                freshness=Freshness.EOD,
                verification=Verification.VERIFIED_PRIMARY,
                rows=len(frame),
                period_start=frame.index[0].date(),
                period_end=frame.index[-1].date(),
                market_timestamp=datetime.combine(
                    frame.index[-1].date(), time(15, 30), tzinfo=timezone.utc
                ),
                notes=[f"Official NSE end-of-day series for {getattr(module, 'name', symbol)}."],
            ),
            timeframe="1d",
        )

    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        payload = self._get_json(QUOTE_EP.format(symbol=symbol))
        try:
            info = payload["priceInfo"]
            week = info.get("weekHighLow", {})
            last = float(info["lastPrice"])
            prev = float(info["previousClose"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(
                "NSE quote response schema did not match expectations."
            ) from exc
        return Quote(
            symbol=symbol,
            last_price=last,
            change=round(last - prev, 2),
            change_pct=round((last - prev) / prev * 100, 2) if prev else 0.0,
            day_open=float(info.get("open", last)),
            day_high=float(info.get("intraDayHighLow", {}).get("max", last)),
            day_low=float(info.get("intraDayHighLow", {}).get("min", last)),
            prev_close=prev,
            volume=int(payload.get("preOpenMarket", {}).get("totalTradedVolume", 0) or 0),
            week52_high=float(week.get("max", last)),
            week52_low=float(week.get("min", last)),
            provenance=Provenance(
                source="nse/api/quote-equity",
                source_url=QUOTE_EP.format(symbol=symbol),
                market_timestamp=datetime.now(timezone.utc),
                exchange="NSE",
                freshness=Freshness.DELAYED,
                verification=Verification.VERIFIED_PRIMARY,
                note="NSE quote endpoint is typically delayed by seconds to minutes.",
            ),
        )

    def get_fundamentals(self, symbol: str):  # type: ignore[override]
        raise ProviderUnavailable(
            "Financial statements from NSE corporate filings (XBRL) are not "
            "implemented in this release. Enable demo data or add a licensed "
            "fundamentals provider; the platform will not fabricate statements."
        )

    def get_news(self, symbol: str, limit: int = 12):  # type: ignore[override]
        raise ProviderUnavailable(
            "NSE announcement parsing is not implemented in this release."
        )

    def get_option_chain(self, symbol: str, expiry: date | None = None):  # type: ignore[override]
        raise ProviderUnavailable(
            "NSE option-chain retrieval is not implemented. F&O ordering is "
            "disabled anyway in this build."
        )

    def health(self) -> dict[str, object]:
        try:
            self._client()
            return {"provider": self.name, "is_synthetic": False, "healthy": True}
        except ProviderUnavailable as exc:
            return {
                "provider": self.name,
                "is_synthetic": False,
                "healthy": False,
                "error": exc.message,
            }
        finally:
            self.close()

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None
