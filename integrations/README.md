# Integrations

Optional adapters that connect the terminal to something outside this repository.
Everything here is **read-only by construction**, and nothing here is required — the
terminal runs fully in `demo` mode with zero credentials.

## The rule

> An integration may read. It may not write.

There is no order-placement method in this repository to call. The broker adapter below
exposes holdings and positions, and raises `SafeModeViolation` on any attempt to construct or
submit an order. That is not a configuration flag; it is the absence of code.

## What exists

| File | Status | Notes |
|---|---|---|
| [`data_provider_template.py`](data_provider_template.py) | Template, works | Copy it to `backend/data/providers/`, implement the methods you have data for, register it in `Registry._chain()`. |
| [`zerodha_readonly.py`](zerodha_readonly.py) | Skeleton | Read-only holdings/positions shape, with the write path raising. No network calls are implemented. |
| [`nse_adapter_notes.md`](nse_adapter_notes.md) | Notes | How to verify `backend/data/providers/nse.py` on a networked machine — it is unverified here. |

## Adding a data provider

1. Copy `data_provider_template.py` to `backend/data/providers/<vendor>.py`.
2. Implement only the methods the vendor actually serves. **Leave the rest raising
   `ProviderUnavailable` with a clear reason** — never return a plausible-looking zero.
3. Return `DatasetMeta` with real `source`, `freshness` and `verification`. An EOD bhavcopy is
   `Freshness.EOD` + `Verification.VERIFIED_PRIMARY`; a scraped quote is not.
4. Register it in `DataRegistry._chain()` behind the synthetic engine for `auto` mode, ahead of
   it for `live`.
5. Add a test that asserts an unreachable vendor raises rather than falling back silently.

## Credentials

Only the environment. Never commit a token, never put one in the frontend, and never log one:

```bash
BTI_ZERODHA_API_KEY=...
BTI_ZERODHA_ACCESS_TOKEN=...
```

`Settings` declares these fields so future read-only work does not change the config schema.
**Nothing in this release reads them.** If you add a call that uses one, add it to
`docs/data-sources.md` in the same commit.

## What will not be merged

- Any code path that submits, modifies or cancels an order.
- Any write-scope broker session.
- Any adapter that returns invented data when the vendor is unreachable.
