"""Request/response schemas for the API.

Validation lives here: the API rejects malformed input with a 422 before any
service or agent runs. Trading-related request models deliberately have **no**
order endpoint — there is nothing to send an order to.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------ research
class ResearchRequest(BaseModel):
    lookback: int = Field(default=750, ge=260, le=2000)
    agents: list[str] | None = None
    symbol: str

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class AgentRunRequest(BaseModel):
    symbol: str
    agent: str | None = None


# ---------------------------------------------------------------------- risk
class PositionSizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital: float = Field(gt=0, le=1e12)
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=10)
    max_position_pct: float = Field(default=20.0, gt=0, le=100)
    lot_size: int = Field(default=1, ge=1)

    @field_validator("stop_loss")
    @classmethod
    def _stop_below_entry(cls, v: float, info) -> float:
        entry = info.data.get("entry")
        if entry and v >= entry:
            raise ValueError("stop_loss must be below entry for a long position")
        return v


class TradeValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Literal["LONG", "SHORT"] = "LONG"
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target: float = Field(gt=0)
    sector: str = "Unknown"
    atr: float | None = Field(default=None, gt=0)
    strategy: str = "unspecified"
    is_fno: bool = False
    capital: float | None = Field(default=None, gt=0)
    open_risk_pct: float = Field(default=0.0, ge=0, le=100)


# ----------------------------------------------------------------- backtest
class BacktestRequest(BaseModel):
    symbol: str
    strategy: str
    lookback: int = Field(default=1200, ge=300, le=3000)
    initial_capital: float = Field(default=1_000_000, gt=0)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    max_position_pct: float = Field(default=20.0, gt=0, le=100)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)
    segment: Literal["delivery", "intraday"] = "delivery"
    timeframe: Literal["1d", "15m", "60m"] = "1d"
    walk_forward_folds: int = Field(default=4, ge=0, le=8)
    out_of_sample_split: float = Field(default=0.7, gt=0.3, lt=0.95)


class StrategyCompareRequest(BaseModel):
    symbol: str
    strategies: list[str] = Field(min_length=1, max_length=10)
    lookback: int = Field(default=1200, ge=300, le=3000)


# --------------------------------------------------------------------- chart
class ChartRequest(BaseModel):
    timeframe: Literal["1d", "15m", "60m"] = "1d"
    bars: int = Field(default=400, ge=50, le=3000)


# ------------------------------------------------------------------- journal
class TradeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: Literal["LONG", "SHORT"] = "LONG"
    entry_date: date
    entry_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    strategy: str | None = None
    thesis: str | None = None
    market_conditions: str | None = None
    costs: float = Field(default=0.0, ge=0)

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class TradeClose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_price: float = Field(gt=0)
    exit_date: date | None = None
    costs: float = Field(default=0.0, ge=0)
    mistakes: str | None = None
    lessons: str | None = None


class NoteCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3)
    kind: Literal["research", "lesson", "market"] = "research"
    symbol: str | None = None
    tags: str | None = None


# ----------------------------------------------------------------- portfolio
class HoldingIn(BaseModel):
    symbol: str
    quantity: float = Field(gt=0)
    avg_price: float = Field(gt=0)
    name: str | None = None
    sector: str | None = None


class PortfolioImport(BaseModel):
    holdings: list[HoldingIn] = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ options
class OptionChainRequest(BaseModel):
    symbol: str
    expiry: date | None = None


class PayoffLeg(BaseModel):
    action: Literal["BUY", "SELL"]
    kind: Literal["CE", "PE"]
    strike: float = Field(gt=0)
    premium: float = Field(ge=0)
    quantity: int = Field(default=1, ge=1, le=50)


class PayoffRequest(BaseModel):
    legs: list[PayoffLeg] = Field(min_length=1, max_length=8)
    spot: float = Field(gt=0)
    lot_size: int = Field(default=1, ge=1)


# -------------------------------------------------------------------- system
class SystemStatus(BaseModel):
    app: str
    version: str
    owner: str
    environment: str
    data_mode: str
    safety: dict[str, Any]
    providers: dict[str, Any]
    coverage: dict[str, Any]
    agents: int
    strategies: int
    disclaimer: str
