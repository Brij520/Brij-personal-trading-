# BRIJ TRADING INTELLIGENCE

**A personal, research-first Indian equity research laboratory.**

Fourteen specialist agents, a deterministic analytics engine, a backtesting lab with a real
Indian cost model, and a paper-trading journal — behind a dark institutional terminal.

> **This is not a trading bot.** It cannot place, modify or cancel an order. There is no
> broker connection with write access, no auto-execution, and no F&O ordering. Those
> capabilities are not "disabled by configuration" — they are not implemented.

---

## What it actually does

| Capability | Status | Where |
|---|---|---|
| Market overview (indices, breadth, sector rotation) | ✅ working | `backend/services/market.py` |
| Stock search over an 81-name NSE universe | ✅ working | `backend/data/universe.py` |
| Fundamental analysis (5-year ratios, quality score) | ✅ working | `backend/analytics/fundamental.py` |
| Technical analysis (12 indicators + structure) | ✅ working | `backend/analytics/indicators.py` |
| Valuation (FCFF DCF, scenarios, sensitivity, justified P/B for banks) | ✅ working | `backend/analytics/valuation.py` |
| Risk engine with veto (sizing, heat, exposure) | ✅ working | `backend/analytics/risk.py` |
| 14-agent research pipeline with committee classification | ✅ working | `backend/agents/` |
| 25-section research report → MD / HTML / PDF / CSV / XLSX / JSON | ✅ working | `backend/services/report_generator.py` |
| Screener with 16 disclosed conditions | ✅ working | `backend/services/market.py` |
| Backtesting: 8 strategies, costs, slippage, walk-forward, out-of-sample | ✅ working | `backend/backtesting/` |
| Options research: chain, greeks, PCR, max pain, payoff builder | ✅ working (research) | `backend/agents/options_intelligence.py` |
| Paper trading journal + reviews + discipline checks | ✅ working | `backend/journal/` |
| Portfolio import and risk analysis | ✅ working | `backend/agents/portfolio_manager.py` |
| Live NSE/BSE data | ⚠️ **unverified** — no network route here | `backend/data/providers/nse.py` |
| Real financial-statement ingestion (XBRL) | ❌ not implemented | — |
| Options margin modelling | ❌ not implemented | — |
| Live/automated order execution | ❌ **deliberately absent** | — |

Anything marked ❌ is declared, not faked. See [`DEVELOPMENT_STATUS.md`](DEVELOPMENT_STATUS.md).

## Data honesty

This sandbox cannot reach NSE/BSE, so the default `BTI_DATA_MODE=demo` uses a
**deterministic synthetic market engine** (`backend/data/providers/synthetic.py`):

- seeded per symbol, anchored to a fixed calendar → a run today gives the same answer tomorrow;
- a shared market factor drives every stock, so indices, breadth and sector rotation agree;
- OHLCV is structurally valid, fundamentals satisfy basic accounting identities, option greeks
  are real Black-Scholes values on a synthetic surface.

Every value carries provenance: **source, retrieval time, market time, exchange, reporting
period, freshness, verification status**. Synthetic data is labelled `Freshness.SYNTHETIC`
everywhere — in the API, the report header, and a persistent banner in the UI. Data quality
is scored, and the committee caps its own confidence by that score: **synthetic data can never
produce a "STRONG RESEARCH CANDIDATE"**, only a `WATCHLIST` at best.

When a real provider fails, the registry fails loudly (`BTI_DATA_MODE=live`) or falls back and
labels the fallback (`auto`). It never invents a number.

## Quick start

```bash
pip install -r requirements.txt      # 6 required packages + optional httpx
python3 scripts/run.py               # http://localhost:8000
```

Open the terminal at `/`, API docs at `/api/docs`. No credentials needed.

```bash
pytest -q                            # 152 tests
node scripts/check_frontend.mjs      # executes all 18 pages against the live API
```

## Architecture at a glance

```
frontend/  vanilla JS + canvas terminal (18 pages, no build step, no CDN)
   │  fetch
   ▼
backend/api/          FastAPI routes → services
backend/services/     orchestration, reports, market, screener
backend/agents/       14 agents (deterministic engines, optional LLM narration)
backend/analytics/    indicators, fundamentals, valuation, risk   ← the trustworthy core
backend/backtesting/  event-driven engine + Indian cost model
backend/data/         provider interface, synthetic engine, NSE provider, registry
backend/journal/      SQLite paper ledger + review analytics
```

The **analytics layer has no dependency on agents or HTTP**. It is pure functions over data
structures, and it is where the arithmetic is tested. Agents interpret; they do not calculate.

Detailed: [`docs/architecture.md`](docs/architecture.md) · [`docs/agents.md`](docs/agents.md) ·
[`docs/risk-management.md`](docs/risk-management.md) · [`docs/data-sources.md`](docs/data-sources.md).

## The safety kernel

```python
# backend/core/config.py
@property
def live_trading(self) -> bool:      return False   # not a setting, not a flag
@property
def fno_enabled(self) -> bool:       return False
@property
def auto_execution(self) -> bool:    return False
```

Setting `LIVE_TRADING=true` (or `BTI_AUTO_EXECUTION=yes`) in the environment raises
`SafetyViolation` **at startup** — the app refuses to boot rather than running in a dangerous
state. Tests assert this for every truthy spelling (`1`, `yes`, `on`, `enabled`, `TRUE`).

The risk agent's rejection is final: `overridable` is a hard-coded `False`, and
`NO TRADE` overrides an otherwise bullish committee.

## What this project refuses to do

- Promise or imply profits. There is no "signal of the day", no BUY badge, no target price.
- Present delayed data as live, or synthetic data as real.
- Fabricate a value for a missing input. Missing means missing, and it is shown as a limitation.
- Let agent agreement count as evidence. The committee measures *independent evidence types*.
- Change a strategy because of a handful of paper trades. Reviews below 20 closed trades are
  descriptive only, and every proposal is flagged `approved_automatically: false`.

## Configuration

Everything is environment-based (`.env` is git-ignored; see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `BTI_DATA_MODE` | `demo` | `demo` synthetic · `auto` real-then-synthetic · `live` real only |
| `BTI_MAX_POSITION_RISK_PCT` | `2.0` | max risk per trade |
| `BTI_MAX_PORTFOLIO_HEAT_PCT` | `6.0` | aggregate open risk |
| `BTI_MIN_REWARD_RISK` | `1.5` | minimum reward-to-risk |
| `BTI_LLM_PROVIDER` | `none` | `openai`/`anthropic`/`gemini`/`ollama` for prose only |
| `BTI_ZERODHA_API_KEY` | unset | read-only research credentials |

The limits are **platform defaults, not Brij's personal limits**. Set capital explicitly
before using any size output.

## Licence

MIT for this repository's own code (`LICENSE`). The reference repositories listed in the
project brief were studied for structure and ideas only; **no code was copied**. See
[`LICENSE`](LICENSE) and `docs/architecture.md#prior-art`.

---

*Built as a tool for independent, evidence-based research — not for automated gambling.*
