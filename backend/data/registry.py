"""Provider registry: one interface, explicit failover, honest labelling.

Resolution order is driven by ``BTI_DATA_MODE``:

``demo``  synthetic only — always available, always labelled synthetic.
``live``  real providers only; any failure raises (no silent substitution).
``auto``  try real providers, fall back to synthetic and record a warning on
          every affected response, so the UI can never mistake it for live data.

Provider failover never hides itself: :class:`Resolution` carries the provider
actually used plus the errors of the ones that failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from backend.core.config import Settings, get_settings
from backend.core.errors import ProviderUnavailable
from backend.core.logging import get_logger
from backend.data.providers.base import (
    Fundamentals,
    MarketDataProvider,
    NewsItem,
    OptionChain,
    Quote,
    Series,
)
from backend.data.providers.synthetic import SyntheticProvider, index_level_series
from backend.data.universe import BY_SYMBOL, INDEX_MEMBERSHIP

log = get_logger("data.registry")


@dataclass
class Resolution:
    """A payload plus an audit trail of how it was obtained."""

    value: object
    provider: str
    is_synthetic: bool
    failures: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        out = []
        if self.is_synthetic:
            out.append(
                "SYNTHETIC DEMO DATA — not a real market observation. "
                "Do not use for actual investment decisions."
            )
        for f in self.failures:
            out.append(f"Provider failover: {f}")
        return out


class DataRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._synthetic = SyntheticProvider()
        self._real: list[MarketDataProvider] = []
        if self.settings.data_mode in {"live", "auto"}:
            from backend.data.providers.nse import NSEProvider

            self._real.append(NSEProvider(timeout=self.settings.http_timeout_seconds))

    # ------------------------------------------------------------- helpers
    @property
    def mode(self) -> str:
        return self.settings.data_mode

    def _chain(self) -> list[MarketDataProvider]:
        if self.mode == "demo":
            return []
        if self.mode == "live":
            return list(self._real)
        return list(self._real)

    def _resolve(self, method: str, *args, **kwargs) -> Resolution:
        failures: list[str] = []
        for provider in self._chain():
            try:
                value = getattr(provider, method)(*args, **kwargs)
                return Resolution(value, provider.name, provider.is_synthetic, failures)
            except (ProviderUnavailable, NotImplementedError, KeyError) as exc:
                msg = getattr(exc, "message", str(exc))
                failures.append(f"{provider.name}: {msg}")
                log.warning("provider %s failed for %s: %s", provider.name, method, msg)
            except Exception as exc:  # noqa: BLE001 - never let a provider crash a request
                failures.append(f"{provider.name}: unexpected {exc.__class__.__name__}: {exc}")
                log.exception("unexpected provider error %s.%s", provider.name, method)
        if self.mode == "live":
            raise ProviderUnavailable(
                "Live data mode: no provider could serve this request.",
                details={"failures": failures},
            )
        try:
            value = getattr(self._synthetic, method)(*args, **kwargs)
            return Resolution(value, self._synthetic.name, True, failures)
        except KeyError as exc:
            raise ProviderUnavailable(
                f"Symbol {args[0] if args else ''} is not in the supported universe.",
                details={"failures": failures},
            ) from exc

    # ---------------------------------------------------------------- API
    def history(self, symbol: str, timeframe: str = "1d", lookback: int = 750) -> Resolution:
        return self._resolve("get_history", symbol, timeframe=timeframe, lookback=lookback)

    def quote(self, symbol: str) -> Resolution:
        return self._resolve("get_quote", symbol)

    def fundamentals(self, symbol: str) -> Resolution:
        return self._resolve("get_fundamentals", symbol)

    def news(self, symbol: str, limit: int = 12) -> Resolution:
        return self._resolve("get_news", symbol, limit=limit)

    def option_chain(self, symbol: str, expiry: date | None = None) -> Resolution:
        return self._resolve("get_option_chain", symbol, expiry=expiry)

    def index_history(self, index_name: str, lookback: int = 400) -> Resolution:
        """Index candles. Real feed is not implemented; synthetic indices are
        constructed from their own constituents (never a random walk in isolation)."""
        if self.mode in {"live", "auto"}:
            failures = [
                "nse: index historical endpoint not implemented in this release"
            ]
        else:
            failures = []
        if self.mode == "live":
            raise ProviderUnavailable(
                "No live index provider implemented. Use BTI_DATA_MODE=demo for "
                "synthetic index research.",
                details={"failures": failures},
            )
        if index_name not in INDEX_MEMBERSHIP:
            raise KeyError(index_name)
        frame = index_level_series(index_name).tail(lookback)
        # Wrap as a Series so callers get the same shape as stock history.
        df = frame.copy()
        df["open"] = df["close"].shift(1).fillna(df["close"])
        df["high"] = df[["open", "close"]].max(axis=1) * 1.002
        df["low"] = df[["open", "close"]].min(axis=1) * 0.998
        df["volume"] = 0
        df = df[["open", "high", "low", "close", "volume"]]
        from backend.core.provenance import DatasetMeta, Freshness, Verification

        meta = DatasetMeta(
            source="synthetic-demo/index-composite",
            exchange="NSE",
            freshness=Freshness.SYNTHETIC,
            verification=Verification.UNVERIFIED_SYNTHETIC,
            rows=len(df),
            period_start=df.index[0].date(),
            period_end=df.index[-1].date(),
            warnings=[
                "Index level computed as an equal-weighted composite of synthetic "
                "constituents. Not the official NIFTY methodology."
            ],
        )
        return Resolution(
            Series(symbol=index_name, frame=df, meta=meta), "synthetic", True, failures
        )

    # --------------------------------------------------------------- meta
    def health(self) -> dict:
        providers = [self._synthetic.health()] + [p.health() for p in self._real]
        return {
            "data_mode": self.mode,
            "providers": providers,
            "universe_size": len(BY_SYMBOL),
            "indices": list(INDEX_MEMBERSHIP),
        }


@lru_cache(maxsize=1)
def get_registry() -> DataRegistry:
    return DataRegistry()
