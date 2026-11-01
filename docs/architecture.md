# Architecture

## Design rule

> **Arithmetic lives in `backend/analytics`. Interpretation lives in `backend/agents`.**

The analytics layer imports `pandas` and `numpy` and nothing else from this project
(`backend.core.provenance` at most). It has no knowledge of HTTP, no database, no LLM, and
no agent. That means every number the platform produces can be unit-tested as a pure function,
and an agent cannot silently change the definition of RSI or of a current ratio.

```
                    ┌──────────────────────────────────────────────┐
  frontend/         │  vanilla JS terminal, 18 pages, no build step│
                    └───────────────┬──────────────────────────────┘
                                    │ JSON over fetch()
                    ┌───────────────▼──────────────────────────────┐
  backend/api/      │  FastAPI: routing, validation, error mapping  │
                    └───────────────┬──────────────────────────────┘
                    ┌───────────────▼──────────────────────────────┐
  backend/services/ │  orchestrator · market · screener · reports   │
                    └──────┬────────────────────────┬──────────────┘
                           │                        │
        ┌──────────────────▼─────┐      ┌───────────▼───────────────┐
  backend/agents/  │ 14 agents + committee  │      │ backend/analytics/        │
        └──────────────────┬─────┘      │ indicators · fundamentals │
                           │            │ valuation · risk          │
        ┌──────────────────▼─────┐      └───────────┬───────────────┘
  backend/backtesting/│ engine · costs         │                  │
        └──────────────────┬─────┘                  │
        ┌──────────────────▼────────────────────────▼───────────────┐
  backend/data/    │ provider interface · registry · synthetic ·   │
                    │ NSE adapter · 81-name universe                │
                    └──────────────────┬───────────────────────────┘
                    ┌──────────────────▼───────────────────────────┐
  backend/journal/ │  SQLite ledger: trades, holdings, notes,      │
                    │  snapshots, saved reviews                     │
                    └──────────────────────────────────────────────┘
```

Dependency direction is strictly downward. `analytics` never imports `agents`; `data` never
imports `services`; nothing imports `api` except `api` itself. A violation is a bug, not a
style preference — it would mean a calculation could depend on presentation.

## Why the layers are shaped this way

**`analytics/` is the honest core.** It takes plain frames and dictionaries. It returns plain
dictionaries with explicit `None` for inputs it did not receive. It never interpolates, never
guesses a missing quarter, and never divides by zero quietly. Every metric that could be
misleading carries a companion reason string.

**`agents/` are opinionated readers.** Each agent receives a `ResearchContext` (bundle of price,
fundamentals, news, options from the registry) and returns an `AgentFinding`: a stance, a score
in −100…+100, a confidence in 0…1, evidence with sources, risks, and — importantly — a
`limitations` list. Agents compute nothing that analytics already defines; they call it.

**`services/orchestrator.py` is the only place that knows the pipeline order.** It builds the
context once, runs the 11 analysis agents, hands their findings to bull/bear, passes everything
to risk, and finally to the committee. The order is fixed so a finding can never be scored by a
committee that has not seen the risk veto.

**`data/registry.py` owns provenance.** No agent ever instantiates a provider. They ask the
registry, which returns a `Resolution` carrying the value *and* its provenance, plus warnings
about fallbacks. When `BTI_DATA_MODE=live` and a provider fails, the registry raises
`ProviderUnavailable` instead of substituting demo data.

## Anatomy of a research run

`POST /api/research/RELIANCE` (see `backend/services/orchestrator.py`):

1. **Symbol resolution.** `universe.resolve(symbol)` maps aliases (`reliance`, `RELIANCE.NS`,
   `INE002A01018`) to the canonical NSE symbol, or raises `SymbolNotFound`.
2. **Bundle build.** One registry pass: 5 years of daily OHLCV, the quote, six fiscal years of
   fundamentals, twelve news items, and an option chain for F&O-enabled names.
3. **Context.** The bundle plus settings, journal access, and a memoised helper
   (`bundle_from(ctx)`) so eleven agents do not refetch.
4. **Analysis agents** run in a fixed order, each receiving the growing context. Each returns
   an `AgentFinding`; a failure raises `AgentError`, which the orchestrator records as a failed
   agent (and the committee treats as missing evidence) rather than fabricating a finding.
5. **Debate.** `bull_research` and `bear_research` build opposing cases *from the collected
   evidence only*, and each must state what would invalidate it.
6. **Risk.** `risk_management` receives proposals, applies limits, and may veto. Its rejection
   is final (`overridable=False`).
7. **Committee.** Counts distinct, independent evidence types, checks source verification,
   applies the data-quality ceiling, and emits a classification plus a confidence.
8. **Report.** `report_generator.build_sections()` renders 25 sections; any of the six formats
   can be exported.

A run takes roughly 0.4–2.5 s on synthetic data. It is synchronous because a research run is a
deliberate act, not a stream.

## Determinism

- The synthetic engine anchors to a fixed calendar and seeds from the symbol, so the same
  request on the same day returns the same numbers, and a backtest is reproducible.
- Backtests execute on the **next bar's open**, and signal functions only see data up to the
  current index. A test truncates the frame to 600 bars and asserts identical signals.
- No layer calls `random` without a seed, and no layer reads the wall clock for anything but
  provenance timestamps.

## Errors

`backend/core/errors.py` defines one exception family mapped to HTTP status codes in
`app.py`:

| Exception | HTTP | Meaning |
|---|---|---|
| `ValidationError` | 422 | The request was understood and refused. |
| `SymbolNotFound` | 404 | Unknown symbol; the message lists how to discover valid ones. |
| `ProviderUnavailable` | 503 | Data source unreachable; no data was invented. |
| `AgentError` | 500 | An agent failed; its finding is absent, not zeroed. |
| `SafetyViolation` | 500 (startup) | A blocked capability was requested in config. |

Error bodies are `{"detail": ..., "code": ...}` so the frontend can distinguish "you asked
wrong" from "the data source is down".

## Prior art

The brief referenced several public repositories for structure and ideas (multi-agent research
pipelines, Indian-market trading bots, terminal-style dashboards). They were studied, not
cloned, and **no code was copied**: this repository's licence is MIT over original code only,
and the reference list is recorded here for transparency rather than as a dependency claim.

What was deliberately *not* adopted from that space: order execution, broker session
management, F&O ordering, and "signal" UX. Those are the parts that turn a research tool into
an account-destroying automation script.

## Scale boundaries

This is a single-user research terminal, and the code is sized for that:

- SQLite with a per-call connection is correct for one user, not for a team.
- The synthetic engine materialises ~2,200 bars per symbol on demand; the screener over 90
  names takes ~1.4 s.
- There is no job queue. A backtest over 8 strategies × 5 years is a few seconds and runs
  inline; anything much larger needs a worker (see `DEVELOPMENT_STATUS.md`).
