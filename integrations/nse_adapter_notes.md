# Verifying the NSE adapter

`backend/data/providers/nse.py` is **unverified**. It was written in a sandbox with no route to
`nseindia.com`, so it has never received a live response. Treat it as untested code until you
have done the following on a networked machine.

## Why it might be broken

NSE's public endpoints are undocumented, rate-limited, and change shape without notice. The
adapter raises `ProviderUnavailable` on any schema mismatch rather than coercing values — so a
drift will be loud, not silent. That is the good news; it also means it will fail often.

## Verification procedure

```bash
BTI_DATA_MODE=live python3 scripts/run.py
```

1. `curl -s localhost:8000/api/stocks/RELIANCE/quote | python3 -m json.tool`
   Compare `last_price` to the NSE website **at the same moment**, and read the returned
   `freshness` and `verification` — they should say `DELAYED`/`VERIFIED_SECONDARY`, not `LIVE`.
2. `curl -s "localhost:8000/api/stocks/RELIANCE/chart?bars=60"` and check the last close against
   the exchange's official close for that date. One day off means the bhavcopy mapping is wrong.
3. `curl -s localhost:8000/api/system/status` — `providers` should show `healthy: true`.
4. Run `pytest -q`. The provenance tests assert that `live` mode without a working provider
   raises rather than silently substituting demo data.

## What is deliberately unimplemented

| Method | Behaviour |
|---|---|
| `get_fundamentals` | Raises `ProviderUnavailable` — XBRL filing parsing is not built. |
| `get_news` | Raises — announcement parsing is not built. |
| `get_option_chain` | Raises — and F&O ordering is disabled regardless. |
| intraday timeframes | Raises — the public endpoint used only serves daily candles. |

If you add any of these, keep the failure honest: raise with a reason, never return a
plausible-looking zero. Then update `docs/data-sources.md`.
