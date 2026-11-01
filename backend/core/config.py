"""Application configuration and the safety policy kernel.

Safety policy is enforced here, not in the UI and not in the browser:

    RESEARCH_ONLY = True   PAPER_TRADING = True   LIVE_TRADING = False
    FNO_ENABLED   = False  AUTO_EXECUTION = False

The three dangerous switches (live trading, auto execution, F&O) can never be
turned on through environment variables in this release. They are read-only
properties. Attempting to set a conflicting env var raises at startup, so a
misconfigured deployment fails loudly instead of silently trading.

Secrets are only ever read from the environment; nothing is hard-coded.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "var"

#: Environment variables that must never be set to a truthy value.
FORBIDDEN_FLAGS = (
    "LIVE_TRADING",
    "AUTO_EXECUTION",
    "AUTO_ORDER_PLACEMENT",
    "FNO_ENABLED",
)
_TRUTHY = {"1", "true", "yes", "on", "enabled"}


class SafetyViolation(RuntimeError):
    """Raised when configuration attempts to enable a blocked capability."""


class Settings(BaseSettings):
    """Runtime settings. Values come from the environment or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="BTI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- identity
    app_name: str = "Brij Trading Intelligence"
    version: str = "0.1.0"
    owner: str = "Brij Nandan Sharma"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    # ------------------------------------------------------------- data layer
    #: ``demo``   -> deterministic synthetic research data only (default).
    #: ``live``   -> only real upstream providers; fail if unreachable.
    #: ``auto``   -> try real providers, fall back to synthetic with a warning.
    data_mode: Literal["demo", "live", "auto"] = "demo"
    data_dir: Path = DEFAULT_DATA_DIR
    http_timeout_seconds: float = 8.0
    cache_ttl_seconds: int = 60 * 30
    historical_years: int = 4

    # ---------------------------------------------------------------- limits
    max_position_risk_pct: float = 2.0
    max_portfolio_heat_pct: float = 6.0
    max_single_stock_pct: float = 15.0
    max_sector_pct: float = 35.0
    daily_loss_limit_pct: float = 3.0
    min_reward_risk: float = 1.5

    # ---------------------------------------------------------- integrations
    # Read-only / analysis-only credentials. Never used to place orders.
    zerodha_api_key: str | None = None
    zerodha_access_token: str | None = None
    dhan_access_token: str | None = None
    groww_access_token: str | None = None

    # LLM integration is provider independent and disabled by default. Without
    # a key every agent still runs, using its deterministic rule engine.
    llm_provider: Literal["none", "openai", "anthropic", "gemini", "ollama"] = "none"
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_model: str | None = None
    llm_base_url: str | None = None

    # ------------------------------------------------------------------- inf
    database_url: str | None = None  # reserved for Postgres; SQLite used now
    cors_origins: str = "*"

    # -------------------------------------------------------------- safety
    research_only: bool = True
    paper_trading: bool = True

    @field_validator("data_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    # ------------------------------------------------------- immutable flags
    @property
    def live_trading(self) -> bool:
        """Always False in this release."""
        return False

    @property
    def fno_enabled(self) -> bool:
        """Options research is available; *ordering* F&O is not."""
        return False

    @property
    def auto_execution(self) -> bool:
        """No unattended execution, ever, without a human-confirmed ticket."""
        return False

    @property
    def sqlite_path(self) -> Path:
        """The single place the paper-journal database location is defined."""
        return self.data_dir / "journal.sqlite3"

    @property
    def is_demo_data(self) -> bool:
        return self.data_mode in {"demo", "auto"}

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def safety_snapshot(self) -> dict[str, object]:
        """Machine-readable safety state, exposed by ``GET /api/system/status``."""
        return {
            "research_only": self.research_only,
            "paper_trading": self.paper_trading,
            "live_trading": self.live_trading,
            "fno_enabled": self.fno_enabled,
            "auto_execution": self.auto_execution,
            "order_placement": "disabled",
            "broker_integrations": "read-only analysis",
            "data_mode": self.data_mode,
            "llm_provider": self.llm_provider,
        }

    def assert_safe(self) -> None:
        """Fail fast if the environment tries to enable a blocked capability."""
        problems: list[str] = []
        for flag in FORBIDDEN_FLAGS:
            for prefix in ("BTI_", ""):
                raw = os.getenv(f"{prefix}{flag}")
                if raw and raw.strip().lower() in _TRUTHY:
                    problems.append(f"{prefix}{flag}={raw!r}")
        if problems:
            raise SafetyViolation(
                "Blocked capability requested via environment: "
                + ", ".join(problems)
                + ". This build is research/paper only. Live trading, F&O "
                "ordering and auto-execution are not implemented."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_safe()
    return settings


def override_settings(**kwargs: object) -> Settings:
    """Test helper: build a settings object without touching the cache."""
    return Settings(**kwargs)  # type: ignore[arg-type]
