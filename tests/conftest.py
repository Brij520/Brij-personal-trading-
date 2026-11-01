"""Shared pytest fixtures.

Tests run against the deterministic synthetic provider so they are reproducible
offline. No test hits the network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("BTI_DATA_MODE", "demo")
os.environ.setdefault("BTI_ENVIRONMENT", "test")


@pytest.fixture(scope="session")
def settings():
    from backend.core.config import Settings

    return Settings(data_mode="demo", environment="test")


@pytest.fixture(scope="session")
def registry(settings):
    from backend.data.registry import DataRegistry

    return DataRegistry(settings)


@pytest.fixture(scope="session")
def bundle(registry):
    from backend.services.research_context import build_bundle

    return build_bundle(registry, "RELIANCE", lookback=600)


@pytest.fixture(scope="session")
def bank_bundle(registry):
    from backend.services.research_context import build_bundle

    return build_bundle(registry, "HDFCBANK", lookback=600)


@pytest.fixture()
def journal(tmp_path):
    from backend.journal.store import JournalStore

    return JournalStore(tmp_path / "journal_test.sqlite3")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.api.app import create_app

    return TestClient(create_app())
