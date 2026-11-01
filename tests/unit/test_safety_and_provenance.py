"""Safety kernel and provenance contract.

These are the tests that protect the project's central promise: no live trading,
no fabricated data presented as real.
"""

from __future__ import annotations

import pytest

from backend.core.config import FORBIDDEN_FLAGS, SafetyViolation, Settings
from backend.core.provenance import (
    DatasetMeta,
    Freshness,
    Provenance,
    Verification,
    assess_quality,
    demo_provenance,
    quality_band,
)


def test_dangerous_flags_default_off():
    s = Settings()
    assert s.research_only is True
    assert s.paper_trading is True
    assert s.live_trading is False
    assert s.fno_enabled is False
    assert s.auto_execution is False


def test_flags_are_read_only_properties():
    s = Settings()
    with pytest.raises(AttributeError):
        s.live_trading = True  # type: ignore[misc]


@pytest.mark.parametrize("flag", FORBIDDEN_FLAGS)
def test_environment_cannot_enable_blocked_capability(flag, monkeypatch):
    monkeypatch.setenv(flag, "true")
    s = Settings()
    with pytest.raises(SafetyViolation):
        s.assert_safe()


@pytest.mark.parametrize("value", ["1", "yes", "on", "enabled", "TRUE"])
def test_all_truthy_spellings_blocked(value, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", value)
    with pytest.raises(SafetyViolation):
        Settings().assert_safe()


def test_prefixed_env_also_blocked(monkeypatch):
    monkeypatch.setenv("BTI_AUTO_EXECUTION", "yes")
    with pytest.raises(SafetyViolation):
        Settings().assert_safe()


def test_false_values_are_allowed(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "false")
    Settings().assert_safe()  # must not raise


def test_safety_snapshot_reports_orders_disabled():
    snapshot = Settings().safety_snapshot()
    assert snapshot["order_placement"] == "disabled"
    assert snapshot["live_trading"] is False
    assert snapshot["fno_enabled"] is False


def test_synthetic_data_is_never_labelled_live():
    p = demo_provenance("test")
    assert p.freshness is Freshness.SYNTHETIC
    assert p.verification is Verification.UNVERIFIED_SYNTHETIC
    assert p.is_synthetic is True
    assert p.freshness.is_tradable_now is False


def test_synthetic_data_caps_quality():
    meta = DatasetMeta(
        source="synthetic-demo", exchange="NSE", freshness=Freshness.SYNTHETIC,
        verification=Verification.UNVERIFIED_SYNTHETIC,
    )
    quality = assess_quality(meta, bars=1000)
    assert quality["score"] <= 55
    assert "synthetic" in quality["penalties"]
    assert any("Synthetic" in n for n in quality["notes"])


def test_verified_eod_data_scores_high():
    meta = DatasetMeta(
        source="nse/api/historical", exchange="NSE", freshness=Freshness.EOD,
        verification=Verification.VERIFIED_PRIMARY, rows=900,
    )
    from datetime import date

    meta.period_start = date(2020, 1, 1)
    meta.period_end = date(2024, 1, 1)
    quality = assess_quality(meta, bars=900)
    assert quality["score"] >= 90
    assert quality["band"] == "HIGH"


def test_stale_and_unverified_penalised():
    meta = DatasetMeta(
        source="scrape", freshness=Freshness.STALE, verification=Verification.UNVERIFIED,
    )
    quality = assess_quality(meta, bars=50)
    assert quality["score"] < 50
    assert {"stale", "unverified", "thin_history"} <= set(quality["penalties"])


def test_quality_bands():
    assert quality_band(95) == "HIGH"
    assert quality_band(75) == "MODERATE"
    assert quality_band(55) == "LOW"
    assert quality_band(10) == "VERY_LOW"


def test_provenance_label_contains_source_and_date():
    p = Provenance(source="nse/api", exchange="NSE", freshness=Freshness.EOD,
                   verification=Verification.VERIFIED_PRIMARY)
    label = p.label()
    assert "nse/api" in label and "NSE" in label and "EOD" in label


def test_registry_warns_when_falling_back_to_synthetic(registry):
    res = registry.history("TCS", lookback=300)
    assert res.is_synthetic is True
    assert any("SYNTHETIC" in w for w in res.warnings)


def test_unknown_symbol_raises_rather_than_inventing_data(registry):
    from backend.core.errors import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        registry.quote("NOTREAL")


def test_live_mode_fails_loudly_without_provider(settings):
    from backend.core.errors import ProviderUnavailable
    from backend.data.registry import DataRegistry

    strict = Settings(data_mode="live")
    registry = DataRegistry(strict)
    with pytest.raises(ProviderUnavailable):
        registry.fundamentals("TCS")
