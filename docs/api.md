# API reference

Base URL: `http://localhost:8000/api`. Interactive docs: `/api/docs` (OpenAPI at
`/api/openapi.json`). All responses are JSON unless a file is requested.

## Envelope

Every JSON response is a plain object with named keys — `{"limits": …}`, `{"symbol": …,
"classification": …}`, `{"items": [...]}`. There is no generic `data` wrapper, and no response
is ever a bare array. Errors are always:

```json
{ "detail": "human-readable explanation", "code": "SYMBOL_NOT_FOUND" }
```

| HTTP | When |
|---|---|
| 400 | Malformed request. |
| 404 | Unknown symbol or trade id. |
| 422 | The request was understood and refused (bad stop, R:R < 1.5, F&O proposal…). |
| 503 | Data provider unreachable (only possible in `live`/`auto` mode). |
| 500 | An agent failed. Its finding is absent — never zeroed. |

Every response carries three diagnostic headers:

```
X-Request-Id:      2210a702751f
X-Response-Time-Ms: 18.4
X-Data-Policy:     data-mode=demo; research-only; no order routing
```

so a client can detect demo data and the safety posture without parsing the body.

## System

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness only. |
| `GET` | `/system/status` | App, safety snapshot, provider health, coverage counts, limits, LLM mode, disclaimer. |
| `GET` | `/agents` | All 14 agents with name, responsibility, inputs and outputs. |
| `POST` | `/agents/{agent_name}/run?symbol=…` | Runs one agent in isolation (useful for debugging). |

`GET /system/status` → `safety` is the machine-readable proof of the platform's posture:

```json
" safety": {
  "research_only": true, "paper_trading": true,
  "live_trading": false, "fno_enabled": false, "auto_execution": false,
  "order_placement": "disabled"
}
```

## Market and universe

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/market/overview` | — | Indices with change, breadth (advances/declines), sector rotation, top movers, VIX, regime label + provenance. |
| `GET` | `/market/indices` | — | Index quotes only. |
| `GET` | `/universe` | `sector` | All instruments (81) with sector/industry/index/F&O flags. |
| `GET` | `/universe/search` | `q`, `limit≤50` | Alias/ISIN/symbol search. Empty `q` returns the first `limit` names. |

## Stocks

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/stocks/{symbol}/quote` | — | Last price, change, OHLC, volume, 52w range, market cap, provenance. |
| `GET` | `/stocks/{symbol}/chart` | `timeframe` (`1d`, `5m`, `15m`, `60m`), `bars` 50–3000 | OHLCV arrays + indicator overlays (EMA20/50/200) + provenance. |
| `GET` | `/stocks/{symbol}/fundamentals` | — | Six fiscal years of statements, computed ratios, quality score, sector profile, `is_financial`. |
| `GET` | `/stocks/{symbol}/technical` | `timeframe` | Twelve indicators, trend classification, support/resistance, score, evidence. |
| `GET` | `/stocks/{symbol}/valuation` | — | DCF assumptions, bear/base/bull values, sensitivity grid, multiples, limitations. |
| `GET` | `/stocks/{symbol}/news` | `limit≤30` | Dated items, each tagged `FACT` or `OPINION`, with sentiment and source. |
| `GET` | `/stocks/{symbol}/options` | `expiry` | Chain with greeks, PCR, max pain, ATM IV. 404-shaped error for non-F&O names. |

Symbols accept `RELIANCE`, `reliance`, `RELIANCE.NS` and ISINs.

## Options research

`POST /options/payoff`

```json
{ "symbol": "NIFTY", "spot": 24500, "legs": [
    { "action": "BUY",  "option_type": "CE", "strike": 24500, "premium": 120, "quantity": 50 },
    { "action": "SELL", "option_type": "CE", "strike": 24700, "premium": 60,  "quantity": 50 }
] }
```

Returns the payoff curve, breakevens, max profit/loss, net premium, and a
`margin_estimate` object. The estimate uses a wide expiry stress grid plus a
20% short-option notional buffer; it is explicitly **not** exchange SPAN/Exposure
margin and must not be used as a broker funding requirement. `fno_enabled` remains
`false`: this endpoint researches structures, it does not build orders.

## Research

| Method | Path | Notes |
|---|---|---|
| `POST` | `/research/{symbol}` | Body optional: `{"lookback": 750}`. Runs all 14 agents. |
| `GET` | `/research/{symbol}` | Same, with `lookback` 260–2000. |
| `GET` | `/research/{symbol}/report?format=markdown|html|pdf|csv|xlsx|json` | File download with proper media type. |

The response contains:

```jsonc
{
  "symbol": "RELIANCE",
  "run_id": "cbeabae4ced1",          // shared by all findings and the report
  "generated_at": "2026-11-01T04:26:20Z",
  "duration_ms": 129.6,
  "classification": "WATCHLIST",
  "confidence": 0.4125,
  "summary": "WATCHLIST: evidence is mixed and does not justify a research candidate",
  "data_mode": "demo",
  "data_quality": {"score": 55, "band": "LOW", "penalties": {"synthetic": 45}},
  "bundle": {"company", "sector", "industry", "price", "bars", "provenance"},
  "committee": {"classification", "rationale", "composite_score", "corroboration",
                "contributions", "confidence", "stance", "limitations"},
  "risk": {"decision": {"approved", "quantity", "risk_amount", "overridable", ...},
           "headline", "stance", "limitations"},
  "debate": {"bull": {"headline", "score", "narrative", "pillars"},
             "bear": {"headline", "score", "narrative", "attacks"}},
  "limitations": ["... 51 distinct caveats, de-duplicated across agents ..."],
  "safety": {"research_only": true, "order_placement": "disabled", ...},
  "findings": {"<agent>": {"headline", "stance", "score", "confidence",
                            "evidence": [...], "risks": [...], "limitations": [...]}},
  "failures": [],
  "disclaimer": "…"
}
```

The 25 written report sections are produced by the **export** endpoint, not inlined here:
`GET /api/research/{symbol}/report?format=markdown|html|pdf|csv|xlsx|json`.

A research run over synthetic data returns `classification: "WATCHLIST"` at best. That is a
tested invariant, not a coincidence.

## Risk

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/risk/limits` | — | Current limits plus the warning that they are platform defaults. |
| `POST` | `/risk/position-size` | `capital`, `entry`, `stop`, optional `atr`, `risk_pct`, `method` | Quantity from each method, rupee risk, heat, warnings, worked steps. |
| `POST` | `/risk/validate` | `symbol`, `side`, `entry`, `stop_loss`, `target`, `sector`… | `RiskDecision`: approved, reasons, warnings, size, R:R, `overridable: false`. |

```bash
curl -X POST localhost:8000/api/risk/validate -H 'content-type: application/json' -d '{
  "symbol":"RELIANCE","side":"LONG","entry":2900,"stop_loss":2820,"target":3100
}'
```

## Backtesting

| Method | Path | Body |
|---|---|---|
| `GET` | `/backtest/strategies` | — (8 strategies with their rules) |
| `POST` | `/backtest/run` | `symbol`, `strategy`, `bars`, `capital`, `segment`, `costs`, `slippage_bps` |
| `POST` | `/backtest/compare` | `symbol`, `strategies[]`, same inputs → table sorted by Sharpe |

Unknown strategy keys return **422**, not 500. Results include the full trade ledger, equity
curve, cost breakdown, and the explicit statement that the fill is next-bar-open.

## Screener

| Method | Path | Query |
|---|---|---|
| `GET` | `/screener` | `scans` (comma-separated keys), `sector`, `limit≤100` |
| `GET` | `/screener/definitions` | — |

`scans` keys: `quality`, `momentum`, `value`, `breakout`, `reversal`, `growth`, `dividend`,
`low_vol`. Every condition is disclosed in `/screener/definitions` — no hidden magic score.

## Journal (paper trading)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/journal/trades` | Filters: `status`, `symbol`, `limit`. |
| `POST` | `/journal/trades` | Opens a paper trade. Rejects non-paper modes. |
| `POST` | `/journal/trades/{id}/close` | Requires exit price; computes PnL, R-multiple, holding days. Double-close → 422. |
| `POST` | `/journal/trades/{id}/cancel` | Void a planned trade with a reason. |
| `GET` | `/journal/performance` | Win rate, expectancy, profit factor, avg R, best/worst, equity curve, `sample_warning`. |
| `GET` | `/journal/review?period=weekly|monthly|quarterly` | Structured review with `approved_automatically: false` on every proposal. |
| `GET`/`POST` | `/journal/notes` | Mistakes, lessons, rule violations, tagged. |

## Portfolio

| Method | Path | Notes |
|---|---|---|
| `GET` | `/portfolio/holdings` | Stored holdings with live valuation. |
| `POST` | `/portfolio/import` | CSV paste or JSON rows: `symbol, quantity, avg_price[, sector]`. Upserts case-insensitively. |
| `DELETE` | `/portfolio/holdings/{symbol}` | Remove one. |
| `GET` | `/portfolio/analysis?include_agents=false` | Concentration, sector exposure, volatility, beta, VaR, correlation clusters. |
| `GET`/`POST` | `/portfolio/snapshots` | Value history for the equity chart. |

## Conventions worth knowing

- **Nothing is cached in the client's interest.** Every response carries `retrieved_at`; the
  UI shows it. If a number looks stale, it is stale on purpose and labelled.
- **`null` means unknown.** It never means zero. A ratio that cannot be computed is `null`
  with an adjacent `note`.
- **Units are in the key name** (`roce_pct`, `risk_amount`, `market_cap_cr`). Currency is INR;
  market caps are in crore.
- **Rates are percentages**, not fractions, in API payloads (`0.03` for 3% would be a bug).
