# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · SemVer.

This is a single-user research tool. "Breaking" means a saved journal or an exported report
would need attention, not that a third-party client has to change.

---

## [0.1.0] — 2026-11-01

First release. Scope: research, backtesting and paper trading. **No order execution exists.**

### Added

**Data**
- 81-name NSE universe with sector, industry, index membership, F&O flag and ISIN.
- Deterministic synthetic market engine: shared trading calendar, one market factor driving
  correlated constituents, per-symbol seeded series, accounting-consistent statements,
  Black-Scholes option chains, dated news with FACT/OPINION tagging.
- Provider registry with `demo` / `auto` / `live` modes and a read-only NSE adapter for
  quotes and EOD history.
- Provenance on every value (source, retrieval time, market time, exchange, period, freshness,
  verification) and a 0–100 data-quality score that caps downstream confidence.

**Analytics**
- 12 indicators plus trend/structure classification.
- Fundamental ratios, compounded 3y/5y CAGRs, margin stability, working-capital days,
  quality score, and a distinct lender profile for banks/NBFCs.
- FCFF DCF with explicit WACC derivation, sensitivity grid and bear/base/bull scenarios;
  justified P/B for financials; relative multiples.
- Risk engine: three sizing methods, R:R gate, heat, exposure, concentration, VaR/CVaR, beta,
  daily-loss halt.

**Agents**
- 14 agents with a shared contract: stance, score, confidence, evidence, risks, limitations.
- Bull/bear debate constrained to existing evidence.
- Research committee with independent-evidence counting and a synthetic-data ceiling
  (`WATCHLIST` is the best possible on demo data).
- Risk agent with a non-overridable veto.

**Backtesting**
- Event-driven engine: next-bar-open fills, stop-before-target, gap handling, costs and
  slippage both sides.
- Indian cash-segment cost model as data (brokerage caps, STT by segment, exchange, SEBI,
  stamp, GST).
- Eight strategies; walk-forward stability folds; in-sample/out-of-sample split.
- Sample-size warnings below 20 trades.

**Reports**
- 25-section research report with provenance columns and a limitations section.
- Export to Markdown, HTML, PDF, CSV, XLSX, JSON.

**Journal & portfolio**
- SQLite paper ledger: trades, holdings, snapshots, notes, saved reviews.
- Performance summary, strategy breakdown, mistake analysis, discipline checks.
- Weekly/monthly/quarterly review where every proposal is `approved_automatically: false`.
- Portfolio import, concentration, sector exposure, volatility, beta, VaR.

**API & UI**
- 45 routes, OpenAPI at `/api/docs`, uniform error mapping, request ids, `X-Data-Policy`.
- Dark terminal: 18 pages, hash routing, global search, canvas candlesticks with crosshair,
  statusbar with data mode and request latency.
- Synthetic-data banners wherever synthetic data appears.

**Safety**
- `live_trading`, `fno_enabled`, `auto_execution` are read-only `False` properties.
- Truthy environment variables for blocked capabilities raise `SafetyViolation` at startup.

**Tests**
- 152 tests: indicators, fundamentals, valuation, risk, backtesting, agents, journal and costs,
  API integration, safety and provenance.
- `scripts/check_frontend.mjs` renders all 18 pages against the live API without a browser.

### Known limitations at release

- NSE adapter unverified (no network route during development); fundamentals, news and option
  chain are not implemented for it and raise rather than guess.
- Visual layout never inspected in a real browser.
- No corporate-action adjustment; no options margin model; no universe-wide backtest.
- `market.sector_leaders` is a stub over sector aggregates.
- Journal is single-file SQLite, sized for one user.

### Deliberately not added

Order placement, broker write sessions, F&O ordering, auto-execution, "signal" UX, price
targets, and profit claims. See `README.md` § *What this project refuses to do*.
