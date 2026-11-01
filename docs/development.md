# Development

## Setup

```bash
git clone <repo> && cd Brij-personal-trading-
python3 -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements-dev.txt
cp .env.example .env                                    # optional; defaults work
python3 scripts/run.py                                  # http://localhost:8000
```

Python **3.11+**. Six runtime dependencies (plus optional `httpx` for the live NSE adapter), no build
step for the frontend, no external services, no credentials required.

| Command | What it does |
|---|---|
| `python3 scripts/run.py` | Dev server (uvicorn, `HOST`/`PORT` env, reload off by default). |
| `pytest -q` | The full suite (152 tests, ~5 s). |
| `pytest tests/unit -q` | Pure-function tests only — the arithmetic. |
| `node scripts/check_frontend.mjs` | Renders all 18 pages against the live API. |
| `ruff check backend tests` | Lint. |

`scripts/run.py` inserts the repository root on `sys.path`, so it works when invoked as a file
from any working directory. Run it from the repo root anyway; the SQLite journal and exported
reports live under `var/`.

## The test pyramid

```
tests/integration/test_api.py        endpoints, status codes, safety headers
tests/agents/test_agents.py          contracts: no evidence -> INSUFFICIENT_DATA
tests/risk/test_risk_engine.py       sizing, veto, exposure, VaR
tests/strategies/test_backtest.py    next-bar fills, stop-first, no look-ahead
tests/unit/test_indicators.py        RSI/EMA/ATR vs hand-computed values
tests/unit/test_fundamentals.py      ratios, CAGR, bank profile
tests/unit/test_valuation.py         DCF vs closed form, monotonicity
tests/unit/test_safety_and_provenance.py   the honesty invariants
tests/unit/test_journal_and_costs.py       cost schedule, journal algebra
```

Two rules for this repository's tests:

1. **Never weaken a safety assertion to make a test pass.** If
   `synthetic data cannot produce STRONG RESEARCH CANDIDATE` fails, the bug is in the code.
2. **Test the refusal, not just the happy path.** The interesting behaviour of a research
   platform is what it declines to say.

## Safety invariants (checked continuously)

- `Settings().live_trading / fno_enabled / auto_execution` are properties returning `False`;
  assigning to them raises `AttributeError`.
- Every `FORBIDDEN_FLAGS` env var set to `1`, `yes`, `on`, `enabled`, `TRUE` (with or without
  the `BTI_` prefix) raises `SafetyViolation` at startup.
- No route path contains `order`, `place`, `execute`, `cancel-order` or `gtt`.
- `/api/system/status` returns `safety.order_placement == "disabled"`.
- Synthetic data is capped at quality ≤55 and classification ≤`WATCHLIST`.
- A `risk_management` veto forces `NO TRADE` even when every other agent is bullish.

If you add an agent or a route, keep these green. They are the reason the project exists in
this shape.

## Conventions

- **Type hints** on public functions; `from __future__ import annotations` everywhere.
- **Docstrings say why**, not what. `"""Return RSI."""` is noise; `"""Wilder RSI.

  Uses Wilder's smoothing rather than a simple average so the value matches charting
  platforms; the first value is None rather than a seeded guess."""` is not.
- **No mutable default arguments**, no bare `except:`, no `print` (use `core.logging`).
- **Money in rupees, percentages as percentages** (2.0 means 2%). The key name carries the unit.
- **`None` for unknown.** Never `0` for a missing number, never `-1` as a sentinel.
- **Deterministic code** — seeded randomness only, and the seed comes from the symbol.

## Adding things

**A new indicator** → `backend/analytics/indicators.py` (pure function) → test it against a
hand-computed series → expose in `/stocks/{symbol}/technical` → show it in `pages_research.js`.

**A new agent** → subclass `BaseAgent` in `backend/agents/` → register in `PIPELINE` →
add to `describe_agents()` → write a test proving it returns `INSUFFICIENT_DATA` on an empty
context → document it in `docs/agents.md`.

**A new strategy** → `backend/strategies/library.py` with an explicit stop and exit rule →
`tests/strategies/` for the no-lookahead property → it appears in the UI automatically.

**A new endpoint** → route in `backend/api/routes.py` + pydantic model in `schemas.py` →
integration test asserting status code **and** the safety header → add to `docs/api.md`.

**A new data provider** → implement `MarketDataProvider` → register in `Registry._chain()` →
it must return honest `Provenance` and raise `ProviderUnavailable` rather than substituting.

## Debugging

- `GET /api/system/status` — safety, providers, coverage counts, limits.
- `POST /api/agents/{name}/run?symbol=RELIANCE` — run one agent in isolation.
- `BTI_LOG_LEVEL=DEBUG python3 scripts/run.py` — per-request timing and agent durations.
- Every response carries `X-Request-Id`; the same id appears in the server log line.
- `node scripts/check_frontend.mjs` with `VERBOSE=1` prints the stack of a failing page.

## Release checklist

1. `pytest -q` green, no skipped safety tests.
2. `node scripts/check_frontend.mjs` renders all 18 pages.
3. `GET /api/system/status` reports the expected safety posture and provider health.
4. `.env` is not committed; `.gitignore` still covers `var/` and `research/reports/`.
5. `CHANGELOG.md` and `DEVELOPMENT_STATUS.md` updated — including what got *worse* or is still
   unverified.
6. No new dependency without a sentence in the changelog explaining why it is worth it.

## What this repository will not accept

- Any code that can place, modify or cancel an order.
- Any change that lets synthetic data be labelled as live.
- Any feature whose output implies a guaranteed return.
- A test weakened to accommodate a defect.

Those are not style preferences; they are the contract described in `README.md`.
