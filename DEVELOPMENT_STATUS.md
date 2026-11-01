# Development status

**Version:** 0.1.0 · **Date:** 2026-11-01 · **State:** usable for research, not finished.

This file is the honest inventory. It exists because a capability table that only lists
successes is a marketing document, and this repository is not one.

---

## Verified working

Everything below was exercised, not just written. Test counts are from the last full run.

### Data layer
- [x] 81-name NSE universe with sector, industry, index membership, F&O flag, ISIN.
- [x] Symbol resolution: `reliance`, `RELIANCE.NS`, ISIN → canonical symbol; unknown symbols raise.
- [x] Deterministic synthetic engine: shared calendar, seeded per-symbol series, internally
      consistent OHLCV, 6 fiscal years of statements with accounting identities, Black-Scholes
      option chains, dated news.
- [x] Registry provider chain with `demo` / `auto` / `live` modes, per-response provenance, and
      a hard failure instead of a silent substitute in `live` mode.
- [x] Data quality scoring with synthetic cap at 55/100.

### Analytics (60 unit tests)
- [x] 12 indicators, each tested against hand-computed values; Wilder RSI; ATR; Bollinger;
      MACD; ADX; OBV; 52-week position; relative strength.
- [x] Fundamental ratios, 3y/5y CAGRs with compounding, margin stability, working-capital days,
      interest coverage, quality score, bank-specific profile (`is_financial`, ROCE `null`).
- [x] FCFF DCF with explicit WACC build-up, sensitivity grid, bear/base/bull; justified P/B for
      lenders; relative multiples; every assumption surfaced in the response.
- [x] Risk: risk-based / ATR-based / volatility-targeted sizing, R:R gate at 1.5, heat,
      exposure, HHI concentration, historical VaR/CVaR, beta, daily-loss check.

### Backtesting (8 tests)
- [x] Event-driven engine, fills at **next bar open**, stop-before-target when both are touched,
      gap fills at open, cost + slippage on both sides.
- [x] Indian cost schedule (STT, brokerage with intraday cap, exchange, SEBI, stamp, GST)
      verified to the rupee against hand computations.
- [x] Metrics: CAGR, Sharpe, Sortino, max DD, Calmar, expectancy, profit factor, exposure,
      cost drag, sample-size warning under 20 trades.
- [x] Walk-forward folds with a stability verdict; refuses samples too short for the request.
- [x] In-sample vs out-of-sample split with Sharpe degradation.
- [x] 8 strategies, all with explicit stop and exit rules.
- [x] No-lookahead property test (signals on the first 600 bars are unchanged by truncation).

### Agents (14)
- [x] All 14 run end to end; average research run 0.4–2.5 s on synthetic data.
- [x] Contract tests: no evidence → `INSUFFICIENT_DATA`; confidence capped by data quality;
      limitations always populated; no agent can bypass risk.
- [x] Bull/bear debate built only from other agents' evidence.
- [x] Committee: independent-evidence counting, synthetic ceiling at `WATCHLIST`, risk veto
      forces `NO TRADE`, `<2 findings` → `INSUFFICIENT DATA`.
- [x] Forensic accounting flags (CFO/PAT divergence, receivable days, inventory build, pledge,
      dilution, contingent liabilities) — framed as questions, not verdicts.

### Reporting
- [x] 25-section report, six export formats (MD, HTML, PDF, CSV, XLSX, JSON), provenance header,
      disclaimer on every page.
- [x] `to_csv` tolerates absent `dcf`/`bank_valuation` (tested, was a real bug).

### API
- [x] 45 route entries (42 unique paths) under `/api`, OpenAPI at `/api/docs`.
- [x] Uniform error mapping, per-request id and timing, `X-Data-Policy` on every response.
- [x] Integration tests cover health, status/safety, market, universe/search, quote, chart,
      fundamentals, technical, valuation, news, options, research, report export, risk limits,
      position size, validation, strategies, backtest run/compare (including unknown strategy →
      422), screener + definitions, journal lifecycle, portfolio import/analysis.
- [x] **152 tests passing**, `pytest -q`.

### Journal & portfolio (SQLite)
- [x] Open / close / cancel paper trades; PnL, R-multiple, holding days; double-close rejected.
- [x] Performance summary, strategy breakdown, mistake analysis, discipline checks,
      weekly/monthly/quarterly review with `approved_automatically: false`.
- [x] Holdings upsert (case-insensitive), snapshots, notes.
- [x] Portfolio analysis: value, P&L, concentration, sector exposure, volatility, beta, VaR.

### Frontend
- [x] 18 pages, hash routing, global search, market ticker, statusbar with data mode and latency.
- [x] Canvas candlesticks with volume, EMA overlays and crosshair readout; line, bars, payoff.
- [x] Every page renders against the live API with no `undefined`/`NaN`/`[object Object]`
      (verified by `scripts/check_frontend.mjs`, 18/18).
- [x] All 9 JS files pass `node --check`.

### Safety
- [x] `live_trading`, `fno_enabled`, `auto_execution` are read-only `False` properties.
- [x] Truthy env vars for blocked capabilities raise `SafetyViolation` at startup.
- [x] No route contains order/place/execute/cancel/gtt.
- [x] `/api/system/status` exposes the posture; the UI shows it on every screen.

---

## Verified only partially — read this before trusting it

| Item | What was verified | What was not |
|---|---|---|
| **Visual layout** | HTML/CSS/JS served, all pages render in a DOM shim, class coverage checked against the stylesheet | **No browser was available in the development sandbox.** Fonts, wrapping, canvas rendering at real pixel sizes and responsive breakpoints were never seen. |
| **NSE provider** | Code path, error handling, schema guard | **Never received a live response** — no network route to nseindia.com. The endpoint shapes may have drifted. |
| **Frontend interactions** | Handlers are wired and callable in the shim | Real mouse/keyboard flows (crosshair, drag, tab switching) are unexercised. |
| **PDF export** | File is produced and opens | Layout of long tables in the PDF at print time is not visually checked. |
| **Performance** | Single-user timings on synthetic data | No load test; SQLite is per-call connections. |

The browser gap is the single largest risk in this release. The first thing to do on a machine
with Chrome is open the terminal and click through all 18 pages.

---

## Not implemented (declared, not faked)

| Capability | Why not | What the platform does instead |
|---|---|---|
| Live/real-time quotes | No feed subscription; NSE free feed is delayed | Labels data `EOD`/`DELAYED`/`SYNTHETIC` |
| Financial-statement ingestion (XBRL) | Needs a filing parser + mapping per company | `ProviderUnavailable`; synthetic statements in demo mode only |
| Corporate actions (splits/bonus) | Not modelled in the cost ledger | Documented as a backtest limitation |
| Options margin (SPAN/Exposure) | Would require an exchange margin file | Payoff panel reports `margin: null` with a reason |
| Futures | Out of scope — `fno_enabled` is a hard `False` | — |
| Order placement of any kind | **Deliberately absent** | No module, no route, no token with write scope |
| Broker session management | Same | Read-only credential fields exist but are unused |
| Parameter optimisation | Overfitting risk in a single-user tool | Walk-forward stability with fixed parameters |
| Multi-user / auth | Single-user terminal | Bind to localhost; do not expose publicly |
| Backtest over a universe | Single-symbol runs only | `compare()` over 8 strategies on one symbol |
| News from real sources | No licensed feed | Synthetic dated items, clearly labelled |

---

## Known defects and rough edges

1. **`market.sector_leaders` is a stub** — it returns sector aggregates, not named leaders with
   a rationale. It is labelled as such in the payload; it does not pretend to rank companies.
2. **TCS trend-following produces only 3 trades** on the synthetic series — a property of the
   generator, not a bug, but it makes that particular backtest uninformative.
3. **Walk-forward is stability only.** There is no rolling re-optimisation, and the docstring
   says so; a user expecting a true WFO will be surprised if they only read the metric names.
4. **Screener scans 81 names synchronously** (~1.2 s). Fine here, wrong above a few hundred.
5. **Journal is single-file SQLite** with a new connection per call. Correct for one user,
   unsuitable for anything else.
6. **Intraday bars are synthesised** by subdividing the daily range. They test mechanics only.

---

## Next milestones

**Milestone 2 — make the data real (highest value)**
1. Verify the NSE adapter from a networked machine; add a schema-drift test with a recorded
   fixture.
2. Add an XBRL/filing parser for annual statements, verified against one company's published
   numbers.
3. Corporate actions in the price series and the backtest ledger.
4. Licensed intraday feed (or accept EOD-only and remove the intraday pages' pretence of it).

**Milestone 3 — depth**
5. Rolling walk-forward optimisation with an explicit overfitting report.
6. Options margin model from an exchange file; spreads and calendar structures in the payoff.
7. Portfolio-level correlation-regime analysis; factor exposure.
8. Screener over the full NSE master list with incremental refresh.

**Milestone 4 — ergonomics**
9. Browser-based visual QA; screenshot regression.
10. Per-page load budgets and a request cache with visible staleness.
11. Journal-to-research loop: link a trade back to the report that justified it.

---

## How to verify this file

```bash
pytest -q                                  # expect: 152 passed
python3 scripts/run.py &                   # expect: application ready on :8000
node scripts/check_frontend.mjs            # expect: All pages rendered.
curl -s localhost:8000/api/system/status | python3 -m json.tool | head -40
```

If any of those disagree with what is written above, **this file is wrong and should be fixed
first** — an inaccurate status document is worse than none.
