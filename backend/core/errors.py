"""Domain errors. Every error maps to a stable API error code."""

from __future__ import annotations


class BTIError(Exception):
    """Base class for all application errors."""

    code = "BTI_ERROR"
    http_status = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict:
        return {"error": self.code, "message": self.message, "details": self.details}


class NotFoundError(BTIError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(BTIError):
    code = "VALIDATION_ERROR"
    http_status = 422


class ProviderUnavailable(BTIError):
    """A real data provider could not be reached.

    This is deliberately *not* papered over with invented numbers. Callers either
    fall back to another configured provider or surface the failure.
    """

    code = "PROVIDER_UNAVAILABLE"
    http_status = 503


class InsufficientData(BTIError):
    """Not enough observations to compute a trustworthy result."""

    code = "INSUFFICIENT_DATA"
    http_status = 422


class RiskRejected(BTIError):
    """Raised by the risk agent when a proposal breaches hard limits.

    No other agent or caller may override this rejection.
    """

    code = "RISK_REJECTED"
    http_status = 200  # it is a valid research outcome, not a crash


class SafetyBlocked(BTIError):
    """An action was attempted that this build forbids outright."""

    code = "SAFETY_BLOCKED"
    http_status = 403
