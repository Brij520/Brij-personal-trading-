# The fourteen agents

All agents share one contract (`backend/agents/base.py`):

```python
AgentFinding(
    agent, symbol, headline,
    stance,          # BULLISH | NEUTRAL | BEARISH | INSUFFICIENT_DATA
    score,           # -100 .. +100   (direction × strength, NOT probability)
    confidence,      #  0 .. 1        (capped by data quality)
    evidence[],      # claim + value + unit + source + as_of + freshness
    risks[], limitations[], warnings[],
    data_quality{}, metrics{}, generated_by, run_id, duration_ms,
)
```

Rules enforced by the base class and asserted in `tests/agents/`:

1. **No evidence, no opinion.** An agent that cannot gather at least two independent pieces of
   evidence returns `INSUFFICIENT_DATA` with confidence `0`. It does not guess.
2. **Confidence is capped by data quality.** On synthetic data the ceiling is ≈0.55. A perfect
   score on unverified data is still a weak claim.
3. **Limitations are mandatory.** Every agent must say what it could *not* check. That list is
   printed in the report under "Data limitations".
4. **No agent can place, size an order beyond a proposal, or bypass risk.**
5. **Agents never overwrite a number from `analytics/`** — they quote it.

`generated_by` records whether prose came from the deterministic rule engine (default) or an
LLM. **The LLM never produces numbers**: it receives the already-computed findings and only
phrases them. With `BTI_LLM_PROVIDER=none` (the default) every agent still runs.

---

## Pipeline order

| # | Agent key | Responsibility |
|---|---|---|
| 1 | `market_intelligence` | Market regime, breadth, sector rotation and market risk |
| 2 | `fundamental_research` | Business quality and financial risk from reported statements |
| 3 | `valuation` | Intrinsic and relative valuation with transparent assumptions |
| 4 | `technical_analysis` | Trend, momentum, structure and volatility from price data |
| 5 | `forensic_accounting` | Accounting red flags and earnings-quality investigation |
| 6 | `news_sentiment` | News monitoring with strict fact/opinion separation |
| 7 | `options` | Chain, greeks, OI, PCR, max pain and payoff research |
| 8 | `swing_trading` | 4–8 week setups with explicit invalidation and a risk check |
| 9 | `intraday` | Intraday session structure in paper mode |
| 10 | `bull_research` | Strongest evidence-based bullish thesis |
| 11 | `bear_research` | Challenge to the bullish thesis, with evidence |
| 12 | `risk_management` | Sizing, exposure, and the right to reject |
| 13 | `portfolio_manager` | Holdings analysis, concentration and portfolio risk |
| 14 | `research_committee` | Verification, aggregation and classification |

Agents 1–9 run in that order. 10 and 11 read the outputs of 1–9. 12 reads everything,
including any trade proposals. 13 runs whenever holdings exist. 14 runs last, always.

---

## What each one actually checks

### 1. `market_intelligence`
Reads index history (NIFTY 50, SENSEX, NIFTY BANK, NIFTY MIDCAP 100, NIFTY SMALLCAP 100,
India VIX) and computes trend (price vs 50/200 DMA), breadth (advance/decline over the
universe), and sector rotation (20-day sector returns). Stance is a *context* not a buy signal:
a strong stock in a hostile tape is still a hostile tape, and the agent says so. It also sets
the market-risk multiplier the risk agent later uses to cut size.

### 2. `fundamental_research`
Calls `analytics/fundamental.py`: 5-year revenue/EBITDA/PAT/CFO trends, growth CAGR with
compounding (not averaged percentages), margin stability, ROE/ROCE decomposition, working
capital days, interest coverage, and the Piotroski-style quality score. It reports quality —
not price — and explicitly refuses to call a stock cheap or expensive (that is agent 3).

### 3. `valuation`
Runs the FCFF DCF with published assumptions (growth, margins, WACC derivation, terminal
growth, net debt), scenario bounds (bear/base/bull), sensitivity to WACC × growth, and
relative multiples against the peer group. Financials (banks/NBFC) get justified P/B from ROE
and cost of equity instead of a DCF, because a DCF on a lender is fiction. It reports an
intrinsic range — **never a target price**.

### 4. `technical_analysis`
Twelve indicators from `analytics/indicators.py` (EMA 20/50/100/200, SMA, RSI, MACD,
ATR, Bollinger, ADX, OBV, volume ratio, 52-week position, relative strength vs NIFTY), plus
structure: swing highs/lows, trend classification, support/resistance zones. Every indicator
is quoted with its window. It reports a *state*, and the confidence is capped harder when
fewer than 200 bars exist.

### 5. `forensic_accounting`
Beneish-style signals: CFO/PAT divergence, receivable days creeping up, inventory build faster
than sales, capitalised expenses, contingent-liability language, auditor changes, promoter
pledge. Each flag is a **question to investigate**, not an accusation, and the agent says
which filing would answer it.

### 6. `news_sentiment`
Separates **FACT** (a dated, attributed event) from **OPINION** (a view, a prediction, a
"target"). Sentiment is a count-weighted balance of the fact set, not a vibe. If fewer than
three recent items exist it returns `INSUFFICIENT_DATA` rather than extrapolating from one
headline. Synthetic headlines are labelled as such.

### 7. `options`
For F&O-enabled names: chain snapshot, ATM IV, PCR (OI and volume), max pain, OI change at the
strikes, Black-Scholes greeks, and an ATM straddle cost implying a move. The payoff builder
handles multi-leg structures and reports breakevens, max profit/loss, and a clearly labelled
stress-based research margin estimate. This is not SPAN/Exposure margin. Options are research
only — `fno_enabled` is a hard False, so no F&O order can be constructed.

### 8. `swing_trading`
Searches 4–8 week setups (breakout, pullback, base) with a defined entry zone, an
ATR-derived stop, and two targets at 2R/3R. It calls the risk engine on the proposal; if risk
refuses, the setup is reported as `REJECTED` with the reason, and the trade is not suggested.

### 9. `intraday`
Session structure (opening range, VWAP, first-hour volume distribution) on 5-minute synthetic
bars in demo mode. In paper mode it can describe a plan, but says plainly that it cannot watch
the tape and that intraday results on synthetic data mean nothing.

### 10–11. `bull_research` / `bear_research`
Both are constructed **only from the other agents' evidence**, with citations back to the agent
that produced each claim. Bull must state the strongest counter-argument it cannot answer;
bear must state the strongest bullish point it cannot dismiss. Neither may introduce new data
or a new calculation.

### 12. `risk_management`
Sizing, heat, exposure, and veto. See [risk-management.md](risk-management.md). Its rejection
overrides a bullish committee — verified by test.

### 13. `portfolio_manager`
Imports holdings (CSV paste or manual), values them, and reports concentration (HHI, top-1,
top-5), sector exposure against the 35% cap, correlation clusters, portfolio volatility, beta,
and 95/99% VaR from the actual return distribution. It flags overlap between holdings that look
diversified but are not (same sector, same factor).

### 14. `research_committee`
See below.

---

## The committee

The committee is the only agent allowed to produce a classification, and it is deliberately
stingy.

**Evidence counting.** It counts *independent evidence types*, not agents. Two agents citing
the same CFO/PAT series count once. Fewer than two independent findings → `INSUFFICIENT DATA`
regardless of scores.

**Classification order** (first match wins):

| Condition | Classification |
|---|---|
| risk veto | `NO TRADE` |
| < 2 independent findings | `INSUFFICIENT DATA` |
| composite ≥ threshold, no veto, verified data | `STRONG RESEARCH CANDIDATE` |
| composite ≥ lower threshold | `RESEARCH CANDIDATE` |
| mixed or negative | `WATCHLIST` |
| contradictory high-confidence evidence | `WATCHLIST` with "needs another look" |

**The synthetic ceiling.** If the underlying data is synthetic or unverified, the best
possible outcome is `WATCHLIST` — the committee downgrades `STRONG RESEARCH CANDIDATE`
explicitly and records why. This is tested, not aspirational.

**What the committee does not do.** It does not average scores into a verdict (it uses
evidence breadth and quality first), does not produce a price target, and does not advise
buying. Its output is a *label for further study*, with the exact reasons for the label.

---

## Extending the pipeline

Add a file under `backend/agents/`, subclass `BaseAgent`, implement `run(ctx)`, and register
the class in `PIPELINE` in `backend/services/orchestrator.py`. Then add a test that asserts it
returns `INSUFFICIENT_DATA` on an empty context — that single test catches most dishonest
agents before they ship.
