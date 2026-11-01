"""API integration tests. These assert the safety contract at the HTTP boundary."""

from __future__ import annotations

import zipfile

import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_exposes_safety_flags(client):
    body = client.get("/api/system/status").json()
    assert body["safety"]["live_trading"] is False
    assert body["safety"]["auto_execution"] is False
    assert body["safety"]["order_placement"] == "disabled"
    assert body["coverage"]["agents"] == 14
    assert body["coverage"]["strategies"] >= 8


def test_no_order_endpoints_exist(client):
    """There must be no route that could place or cancel an order."""
    paths = {route.path for route in client.app.routes}
    forbidden = ("order", "place", "execute", "cancel-order", "gtt")
    offenders = [p for p in paths if any(f in p.lower() for f in forbidden)]
    assert offenders == []


def test_market_overview(client):
    body = client.get("/api/market/overview").json()
    assert body["indices"]
    assert body["breadth"]["universe_size"] > 50
    assert body["is_synthetic"] is True
    assert any("VIX" in item for item in body["unavailable"])


def test_search(client):
    body = client.get("/api/universe/search?q=tata").json()
    assert any(r["symbol"] == "TCS" for r in body["results"])


def test_unknown_symbol_returns_404(client):
    r = client.get("/api/stocks/NOTREAL/quote")
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"


def test_quote_has_provenance(client):
    body = client.get("/api/stocks/TCS/quote").json()
    assert body["provenance"]["freshness"] == "SYNTHETIC"
    assert body["provenance"]["source"]
    assert body["warnings"]


def test_chart_and_technical(client):
    chart = client.get("/api/stocks/TCS/chart?bars=200").json()
    assert len(chart["bars"]) == 200
    tech = client.get("/api/stocks/TCS/technical").json()
    assert "rsi14" in tech["indicators"]
    assert set(tech["trend"]) == {"primary", "intermediate", "short_term"}


def test_fundamentals_endpoint(client):
    body = client.get("/api/stocks/HDFCBANK/fundamentals").json()
    assert body["analysis"]["latest_ratios"]["roce_pct"] is None  # lender
    assert body["analysis"]["is_financial"] is True
    assert len(body["annual"]) >= 3


def test_position_size_endpoint(client):
    r = client.post("/api/risk/position-size", json={
        "capital": 500_000, "entry": 100, "stop_loss": 95, "risk_pct": 1.0})
    assert r.status_code == 200
    body = r.json()
    assert body["quantity"] == 1000
    assert body["risk_amount"] == pytest.approx(5000)


def test_position_size_validation_rejects_bad_stop(client):
    r = client.post("/api/risk/position-size", json={
        "capital": 500_000, "entry": 100, "stop_loss": 105})
    assert r.status_code == 422


def test_risk_validate_rejects_fno(client):
    r = client.post("/api/risk/validate", json={
        "symbol": "RELIANCE", "entry": 100, "stop_loss": 95, "target": 120,
        "is_fno": True, "capital": 500_000})
    body = r.json()
    assert body["approved"] is False
    assert body["overridable"] is False


def test_risk_validate_accepts_good_plan(client):
    r = client.post("/api/risk/validate", json={
        "symbol": "RELIANCE", "entry": 100, "stop_loss": 95, "target": 115,
        "capital": 500_000})
    body = r.json()
    assert body["approved"] is True
    assert body["reward_risk"] == 3.0


def test_backtest_endpoint(client):
    r = client.post("/api/backtest/run", json={
        "symbol": "TCS", "strategy": "trend_following", "lookback": 700})
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body and "assumptions" in body
    assert body["assumptions"]["is_synthetic_data"] is True
    assert "walk_forward" in body and "out_of_sample" in body


def test_backtest_unknown_strategy(client):
    r = client.post("/api/backtest/run", json={"symbol": "TCS", "strategy": "magic"})
    assert r.status_code in {404, 422}


def test_screener_discloses_conditions(client):
    body = client.get("/api/screener?scans=quality&limit=5").json()
    assert body["conditions"]
    assert "not recommendations" in body["disclaimer"]
    for row in body["results"]:
        assert row["matches"]


def test_options_endpoint(client):
    body = client.get("/api/stocks/RELIANCE/options").json()
    assert body["metrics"]["fno_enabled"] is False
    assert body["metrics"]["pcr"] is not None
    assert body["metrics"]["chain"]


def test_payoff_endpoint(client):
    r = client.post("/api/options/payoff", json={
        "spot": 1000, "lot_size": 50,
        "legs": [{"action": "BUY", "kind": "CE", "strike": 1000, "premium": 20}]})
    body = r.json()
    assert body["max_loss"] == pytest.approx(-20 * 50)
    assert body["max_profit"] == "unlimited"
    assert body["breakevens"] == [pytest.approx(1020, abs=1)]


def test_research_run_and_classification(client):
    body = client.post("/api/research/RELIANCE", json={"symbol": "RELIANCE", "lookback": 500}).json()
    assert body["classification"] in {
        "RESEARCH CANDIDATE", "WATCHLIST", "AVOID", "INSUFFICIENT DATA", "NO TRADE"}
    assert len(body["findings"]) >= 10
    assert body["safety"]["order_placement"] == "disabled"
    assert "investment advice" in body["disclaimer"].lower()


def test_report_export_formats(client):
    for fmt, expected in [("markdown", b"Research Report"), ("html", b"<!doctype html"),
                          ("pdf", b"%PDF-1.4"), ("csv", b"section,metric"),
                          ("json", b"{")]:
        r = client.get(f"/api/research/TCS/report?format={fmt}")
        assert r.status_code == 200, fmt
        assert expected in r.content, fmt


def test_xlsx_export_is_valid_zip(client):
    r = client.get("/api/research/TCS/report?format=xlsx")
    assert r.status_code == 200
    import io

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
    assert "xl/workbook.xml" in names
    assert "xl/worksheets/sheet1.xml" in names


def test_unsupported_export_format(client):
    r = client.get("/api/research/TCS/report?format=docx")
    assert r.status_code == 422


def test_journal_endpoints(client):
    created = client.post("/api/journal/trades", json={
        "symbol": "TCS", "entry_date": "2026-10-01", "entry_price": 760,
        "quantity": 10, "stop_loss": 720, "thesis": "test"}).json()["trade"]
    assert created["status"] == "OPEN"
    closed = client.post(f"/api/journal/trades/{created['id']}/close",
                         json={"exit_price": 800}).json()["trade"]
    assert closed["status"] == "CLOSED"
    perf = client.get("/api/journal/performance").json()
    assert "summary" in perf
    review = client.get("/api/journal/review?period=monthly").json()
    assert review["period"] == "monthly"


def test_portfolio_import_and_analysis(client):
    r = client.post("/api/portfolio/import", json={"holdings": [
        {"symbol": "TCS", "quantity": 10, "avg_price": 700},
        {"symbol": "INFY", "quantity": 20, "avg_price": 1400},
    ]})
    assert r.status_code == 200
    analysis = client.get("/api/portfolio/analysis").json()
    assert analysis["metrics"]["holdings"]
    assert analysis["metrics"]["sector_exposure"]
    assert "rebalance_simulation" in analysis["metrics"]


def test_response_headers_carry_policy(client):
    r = client.get("/api/health")
    assert r.headers["X-Data-Policy"].startswith("data-mode=")
    assert "no order routing" in r.headers["X-Data-Policy"]


def test_static_terminal_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"BRIJ TRADING INTELLIGENCE" in r.content
