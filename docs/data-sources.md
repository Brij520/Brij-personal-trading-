# Data sources, provenance and honesty

## The one rule

> **Never present a number without saying where it came from, when, and how much it can be
> trusted — and never invent a number at all.**

`backend/core/provenance.py` exists to make that rule structural rather than aspirational.

## Provenance on every value

`Provenance` carries seven fields:

| Field | Example |
|---|---|
| `source` | `NSE India (bhavcopy)` · `Synthetic Market Engine v1` |
| `source_url` | `https://www.nseindia.com/…` |
| `retrieved_at` | when *we* fetched it |
| `market_timestamp` | when the market priced it |
| `exchange` | `NSE` |
| `reporting_period` | `FY2025` / `Q2 FY2026` |
| `freshness` | `LIVE` `DELAYED` `EOD` `HISTORICAL` `SYNTHETIC` `STALE` `UNKNOWN` |
| `verification` | `VERIFIED_PRIMARY` `VERIFIED_SECONDARY` `CROSS_CHECKED` `UNVERIFIED` `UNVERIFIED_SYNTHETIC` |

Values travel as `DataPoint[T]` (one number + its provenance) or `DatasetMeta` (a series or
payload + provenance for the whole set). `Resolution` wraps whatever the registry returned and
exposes `.warnings` for any fallback that happened.

The frontend renders `freshness` as a badge on every panel. There is no code path that maps
`SYNTHETIC` to `LIVE`.

## Data quality score

`data_quality_score(meta)` starts at 100 and subtracts:

| Condition | Penalty |
|---|---|
| synthetic | −45 |
| `UNVERIFIED` (not `UNVERIFIED_SYNTHETIC`) | −20 |
| stale | −20 |
| unknown freshness | −15 |
| missing reporting period / exchange | −5 each |
| fewer than 200 observations | −10 |

The score is clamped to **0–100** and banded `HIGH` (≥85) `/ MODERATE` (≥70) `/ LOW` (≥50) /
`VERY_LOW`. Synthetic data tops out at **55 — `LOW`** even with perfect internal consistency,
and verified end-of-day data from a primary source scores ≥90 (`HIGH`).

Downstream, the score is a hard **ceiling on agent confidence** and on committee
classification: with synthetic data the best possible classification is `WATCHLIST`.

## Modes

`BTI_DATA_MODE`:

| Mode | Behaviour |
|---|---|
| `demo` *(default)* | Deterministic synthetic engine only. Zero network. Labelled everywhere. |
| `auto` | Try real providers; on failure fall back to synthetic **and attach a warning**. |
| `live` | Real providers only. Any failure raises `ProviderUnavailable` → HTTP 503. |

`live` mode with no provider configured raises on the very first request rather than quietly
serving demo data. Tested.

## Providers

The interface (`backend/data/providers/base.py`) is five methods:

```python
get_history(symbol, timeframe="1d", lookback=750) -> Series
get_quote(symbol)                                 -> Quote
get_fundamentals(symbol)                          -> Fundamentals
get_news(symbol, limit=12)                        -> list[NewsItem]
get_option_chain(symbol, expiry=None)             -> OptionChain
```

`DataRegistry` resolves each call against an ordered provider chain and records which provider
answered. Symbols are validated against the universe first, so `NOTREAL` raises
`SymbolNotFound` instead of producing a synthetic series for a company that does not exist.

### Synthetic engine — `providers/synthetic.py`

Not random noise. It is a small deterministic market simulation:

- **Calendar**: real NSE trading days (weekends and the published holiday list removed), from
  a fixed anchor date, so every symbol shares one timeline.
- **Market factor**: a single seeded return series drives beta exposure for all symbols, so
  indices, breadth and sector rotation are mutually consistent. A day when NIFTY is down 1.2%
  is a day when most constituents are down.
- **Per-symbol**: beta, idiosyncratic vol, drift and momentum persistence, seeded from the
  symbol hash — reproducible across processes and days.
- **OHLCV**: open/close generated, high/low derived from intrabar range with ATR-scaled wicks;
  volume correlates with absolute return; no negative prices, no zero-volume sessions.
- **Fundamentals**: six fiscal years with accounting identities enforced —
  `EBITDA = Revenue × margin`, `PBT = EBITDA − D&A − interest`, `PAT = PBT × (1 − tax)`,
  balance sheet balances, CFO/PAT stays in a plausible band, banks follow a lender profile
  (no meaningful CFO, high leverage, P/B relevance).
- **Options**: chains on a real expiry calendar with strikes around spot, open interest shaped
  by distance from ATM, and **prices computed by Black-Scholes** from a synthetic IV surface.
  The greeks are therefore internally consistent with the prices, even though the surface is
  invented.
- **News**: dated items with explicit `FACT` / `OPINION` kinds and a synthetic source label.

Every result from this provider is stamped `Freshness.SYNTHETIC`,
`Verification.UNVERIFIED_SYNTHETIC`, and source `Synthetic Market Engine v1`.

### NSE adapter — `providers/nse.py`

Implements the public NSE endpoints (quote, historical, option chain) with the session/browser
headers NSE requires, timeouts, and honest error mapping. **It is unverified in this
environment**: this sandbox has no route to `nseindia.com`, so it has never returned a live
response here. It is written so that failure is loud (`ProviderUnavailable`), never silent.
Do not assume it works until you have run it from a machine with internet access and checked a
known value against the exchange site.

### What is *not* connected

Zerodha Kite, Dhan, Groww and any XBRL/filing parser. Configuration keys exist for read-only
tokens so the schema does not change later, but **no broker call is implemented anywhere**.
There is no order-placement module to disable, because it was never written.

## Universe

`backend/data/universe.py` holds 81 NSE names across 18 sectors with symbol, name, sector,
industry, index membership, F&O flag and ISIN. It powers search, the screener and symbol
resolution (alias, `.NS` suffix, ISIN). It is a curated static list, not a live master file:
names can be added by editing one dataclass.

## Freshness in practice

- A 5-year daily history is `EOD` / `HISTORICAL`; it is not "live" and the UI never calls it so.
- The quote for a symbol during market hours in `live` mode would be `DELAYED` (NSE's free feed
  is delayed by ~15 minutes) — the delay is stated, not hidden.
- A cached response older than `cache_ttl_seconds` (default 30 min) is marked `STALE` rather
  than silently served as fresh.

## Audit trail

Every research run gets a `run_id` shared by all fourteen findings and the report header. Given
a report, you can trace each claim to an agent, a source, and a timestamp. That is the whole
point: a conclusion you cannot audit is a rumour with arithmetic attached.
