"""Read-only broker adapter skeleton (Kite Connect shape).

This file exists to make one thing explicit: the platform can *read* holdings and
positions, and cannot do anything else. There is no order method here — not a
disabled one, not a stubbed one. ``SafeModeViolation`` is raised before any
network call could be made, and the class exposes no way around it.

Nothing here is wired into the application. Wiring it would require changing
``backend/core/config.py``, which refuses to start with live trading enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

READ_ONLY_SCOPES = ("profile", "holdings", "positions", "margins", "historical_data")


class SafeModeViolation(RuntimeError):
    """Raised on any attempt to reach a write-scope broker capability."""


@dataclass
class ZerodhaReadOnly:
    api_key: str | None = None
    access_token: str | None = None
    timeout: float = 8.0

    #: Values the platform uses for portfolio analysis. Read-only.
    def holdings(self) -> list[dict[str, Any]]:
        """Return ``[{symbol, quantity, avg_price, ...}]``.

        Implement with ``GET /portfolio/holdings`` using the read-only session.
        Map the vendor's keys to the platform's schema; do not pass raw payloads
        through, because the analyser needs stable field names.
        """
        raise NotImplementedError

    def positions(self) -> list[dict[str, Any]]:
        """Net open positions, read-only. Paper trades live in the journal."""
        raise NotImplementedError

    def margins(self) -> dict[str, Any]:
        """Available capital, used to *inform* limits — never to raise them."""
        raise NotImplementedError

    # ------------------------------------------------ write scope: forbidden
    def place_order(self, *args: Any, **kwargs: Any) -> None:
        raise SafeModeViolation(
            "Order placement does not exist in Brij Trading Intelligence. "
            "The platform is research-only and paper-trading-only by construction."
        )

    def modify_order(self, *args: Any, **kwargs: Any) -> None:
        raise SafeModeViolation("Order modification does not exist in this platform.")

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise SafeModeViolation("Order cancellation does not exist in this platform.")

    def __getattr__(self, item: str) -> None:
        # Any capability not explicitly read-only is refused, including vendor
        # SDK methods that happen to be attached later.
        raise SafeModeViolation(
            f"{item!r} is not a read-only capability and is refused by policy."
        )
