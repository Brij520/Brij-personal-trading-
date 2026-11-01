"""Data provenance: the contract that keeps this platform honest.

Every value that reaches an agent or the UI carries:

1. source                 2. retrieval timestamp      3. market timestamp
4. exchange               5. reporting period         6. data freshness
7. verification status

This module also computes a transparent *data quality* score that downstream
agents and the research committee use to cap their own confidence. Synthetic
demo data can never be presented as live market data: the freshness enum has no
path from ``SYNTHETIC`` to ``LIVE``, and the API surfaces a banner.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Freshness(str, Enum):
    LIVE = "LIVE"                    # streaming / tick
    DELAYED = "DELAYED"              # vendor delay, must state the delay
    EOD = "EOD"                      # end-of-day official close
    HISTORICAL = "HISTORICAL"        # from the archive
    SYNTHETIC = "SYNTHETIC"          # generated for demonstration / tests
    STALE = "STALE"                  # past its freshness budget
    UNKNOWN = "UNKNOWN"

    @property
    def is_tradable_now(self) -> bool:
        return self in {Freshness.LIVE, Freshness.DELAYED}


class Verification(str, Enum):
    VERIFIED_PRIMARY = "VERIFIED_PRIMARY"        # exchange filing / primary doc
    VERIFIED_SECONDARY = "VERIFIED_SECONDARY"    # reputable secondary source
    CROSS_CHECKED = "CROSS_CHECKED"              # two independent sources agree
    UNVERIFIED = "UNVERIFIED"
    UNVERIFIED_SYNTHETIC = "UNVERIFIED_SYNTHETIC"


class Provenance(BaseModel):
    """Where a value came from and how much it can be trusted."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    market_timestamp: datetime | None = None
    exchange: str | None = None
    reporting_period: str | None = None
    freshness: Freshness = Freshness.UNKNOWN
    verification: Verification = Verification.UNVERIFIED
    note: str | None = None

    @property
    def is_synthetic(self) -> bool:
        return self.freshness is Freshness.SYNTHETIC or (
            self.verification is Verification.UNVERIFIED_SYNTHETIC
        )

    def label(self) -> str:
        """Human-readable one-liner used in reports."""
        bits = [self.source]
        if self.exchange:
            bits.append(self.exchange)
        if self.reporting_period:
            bits.append(self.reporting_period)
        stamp = self.market_timestamp or self.retrieved_at
        bits.append(f"as of {stamp:%Y-%m-%d}")
        bits.append(self.freshness.value)
        return " | ".join(bits)


class DataPoint(BaseModel, Generic[T]):
    """A single traceable value."""

    model_config = ConfigDict(extra="forbid")

    value: T
    provenance: Provenance
    unit: str | None = None
    label: str | None = None

    def display(self) -> str:
        return f"{self.value}{f' {self.unit}' if self.unit else ''}"


class DatasetMeta(BaseModel):
    """Provenance for a whole series or payload (not one number)."""

    source: str
    retrieved_at: datetime = Field(default_factory=utcnow)
    market_timestamp: datetime | None = None
    exchange: str | None = None
    freshness: Freshness = Freshness.UNKNOWN
    verification: Verification = Verification.UNVERIFIED
    rows: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def is_synthetic(self) -> bool:
        return self.freshness is Freshness.SYNTHETIC or (
            self.verification is Verification.UNVERIFIED_SYNTHETIC
        )

    def to_provenance(self, reporting_period: str | None = None) -> Provenance:
        return Provenance(
            source=self.source,
            retrieved_at=self.retrieved_at,
            market_timestamp=self.market_timestamp,
            exchange=self.exchange,
            reporting_period=reporting_period,
            freshness=self.freshness,
            verification=self.verification,
        )


# --------------------------------------------------------------------- quality

#: Points deducted from a perfect data quality score, per condition.
_QUALITY_PENALTIES: dict[str, int] = {
    "synthetic": 45,
    "unverified": 20,
    "stale": 20,
    "unknown_freshness": 15,
    "missing_period": 5,
    "missing_exchange": 5,
    "thin_history": 10,
}

QUALITY_LABELS = (
    (85, "HIGH"),
    (70, "MODERATE"),
    (50, "LOW"),
    (0, "VERY_LOW"),
)


def quality_band(score: int) -> str:
    for threshold, label in QUALITY_LABELS:
        if score >= threshold:
            return label
    return "VERY_LOW"


def assess_quality(
    meta: DatasetMeta | Provenance,
    *,
    bars: int | None = None,
    min_bars: int = 200,
) -> dict[str, Any]:
    """Return ``{score, band, penalties, notes}`` for a dataset or datapoint.

    Deliberately conservative. Synthetic demo data tops out around 50/100 which
    prevents the committee from ever issuing a high-confidence classification
    on it.
    """
    penalties: dict[str, int] = {}
    notes: list[str] = []

    is_synthetic = meta.is_synthetic
    if is_synthetic:
        penalties["synthetic"] = _QUALITY_PENALTIES["synthetic"]
        notes.append(
            "Synthetic demonstration data: not a real market observation. "
            "Treat every number as illustrative."
        )

    verification = meta.verification
    if verification is Verification.UNVERIFIED:
        penalties["unverified"] = _QUALITY_PENALTIES["unverified"]
        notes.append("Source not independently verified.")
    elif verification is Verification.UNVERIFIED_SYNTHETIC:
        pass  # already covered by synthetic penalty

    if meta.freshness is Freshness.STALE:
        penalties["stale"] = _QUALITY_PENALTIES["stale"]
        notes.append("Data has exceeded its freshness budget.")
    elif meta.freshness is Freshness.UNKNOWN:
        penalties["unknown_freshness"] = _QUALITY_PENALTIES["unknown_freshness"]
        notes.append("Freshness of the source is unknown.")

    if isinstance(meta, DatasetMeta):
        if meta.period_start is None or meta.period_end is None:
            penalties["missing_period"] = _QUALITY_PENALTIES["missing_period"]
        if not meta.exchange and meta.exchange is not None:
            penalties["missing_exchange"] = _QUALITY_PENALTIES["missing_exchange"]
    else:
        if not meta.reporting_period:
            penalties["missing_period"] = _QUALITY_PENALTIES["missing_period"]

    if bars is not None and bars < min_bars:
        penalties["thin_history"] = _QUALITY_PENALTIES["thin_history"]
        notes.append(f"Only {bars} observations available (need {min_bars}).")

    score = max(0, 100 - sum(penalties.values()))
    return {
        "score": score,
        "band": quality_band(score),
        "penalties": penalties,
        "notes": notes,
    }


def demo_provenance(
    source: str = "synthetic-demo",
    *,
    exchange: str = "NSE",
    reporting_period: str | None = None,
    note: str | None = None,
    market_timestamp: datetime | None = None,
    source_url: str | None = None,
) -> Provenance:
    return Provenance(
        source=source,
        source_url=source_url,
        market_timestamp=market_timestamp or utcnow(),
        exchange=exchange,
        reporting_period=reporting_period,
        freshness=Freshness.SYNTHETIC,
        verification=Verification.UNVERIFIED_SYNTHETIC,
        note=note
        or ("Generated deterministically for demonstration. Not real market data."),
    )
