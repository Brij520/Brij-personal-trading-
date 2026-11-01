# Backtesting

A backtest is a **falsification tool**. Its job is to kill a strategy cheaply, before the
market does it expensively. The engine is therefore built to be pessimistic, and its output is
never phrased as an expectation of profit.

## Execution model

- **Signal on bar *t*, fill at open of bar *t+1*.** There is no code path that fills at the
  close of the signal bar. A test truncates the frame to 600 bars and asserts the signals are
  byte-identical to the first 600 signals of the full run, which is what "no lookahead" means
  in practice.
- **Intrabar exits** use the bar's high/low. If a bar touches both the stop and the target, the
  **stop wins**. That choice is conservative and is not configurable.
- **Gaps** fill at the open, not at the stop. A stop is an instruction, not a guarantee.
- **One position at a time, long only.** No pyramiding, no shorts, no leverage. A strategy
  that needs those to work is not supported, and adding them would change every result.
- **Sizing is risk-based** (fixed fractional of current equity, default 1% risk per trade), so
  results cannot be inflated by compounding a fixed share count.
- **Warm-up** is 220 bars (the 200-DMA is the longest-lookback indicator). Signals before
  warm-up are ignored.

## Costs

`backend/backtesting/costs.py` implements the Indian cash-segment schedule (NSE, 2025-26) as
**data**, not as magic numbers, so it can be updated when rates change:

| Charge | Delivery | Intraday |
|---|---|---|
| Brokerage | 0.03% per side | 0.03%, capped ₹20 per order |
| STT | 0.10% both sides | 0.025%, sell side only |
| Exchange transaction | 0.00297% | 0.00297% |
| SEBI turnover | 0.0001% | 0.0001% |
| Stamp duty | 0.015% on buy | 0.015% on buy |
| GST | 18% on brokerage + exchange + SEBI | same |

Worked example, asserted in tests (₹1,00,000 turnover each side, delivery, zero slippage):
STT ₹100.00, brokerage ₹30.00, exchange ₹2.97, stamp duty ₹15.00.

**Slippage is separate and explicit** — default 5 bps, applied adversely on both sides (buys
fill higher, sells fill lower). The engine reports the cost breakdown of every trade, because a
strategy whose edge is smaller than its costs does not have an edge.

## Strategies shipped

| Key | Name | Idea | Invalidation |
|---|---|---|---|
| `trend_following` | Trend Following (EMA 50/200) | Fresh EMA50/EMA200 bullish cross while EMA200 is rising, 0.3% buffer against whipsaw | stop 2 ATR, target 5 ATR |
| `breakout` | Donchian Breakout (55-day) | 55-day high with volume ≥ 1.3× the 20-day average | stop 2 ATR, target 3R |
| `pullback` | Trend Pullback (RSI reset) | RSI(14) < 45 and turning up, price holding the EMA50, EMA200 rising | 1.5 ATR / structure |
| `momentum` | Absolute Momentum (6-month) | 126-day return crosses above 10%, price above the EMA100 | 2.5 ATR, momentum flip |
| `mean_reversion` | Bollinger Mean Reversion | 2σ lower-band tag with RSI < 35, long-term trend intact | target the 20-day mean |
| `ma_crossover` | SMA 20/50 Crossover (baseline) | The textbook cross — kept as a naive baseline to beat | opposite cross |
| `volume_breakout` | Volume Breakout (20-day, 2×) | 20-day high with volume ≥ 2× the 20-day average | stop 2 ATR |
| `opening_range_breakout` | Opening Range Breakout (15 min) | Intraday break of the first 15 minutes' range with volume | range low / 15:15 square-off |

Eight strategies, not eighty. Each exists to test whether a *boring, published* idea survives
costs — and several do not, which is the useful result.

Each is a pure function `signal_fn(frame) -> frame` with `entry`, `stop`, `target` columns
computed from data available at that bar. The rules are shown in the UI so a result cannot be
admired without being understood.

## Metrics reported

`total_return_pct`, `cagr_pct`, `sharpe`, `sortino`, `max_drawdown_pct`, `calmar`,
`win_rate_pct`, `avg_win`, `avg_loss`, `expectancy`, `profit_factor`, `avg_bars_held`,
`exposure_pct`, `trades`, `total_costs`, `cost_drag_pct`.

Anything with fewer than **20 trades** is flagged: `sample_warning` appears next to the metric
and the strategy comparison refuses to rank by Sharpe alone. A 100% win rate over 6 trades is
noise, and the platform says so in words, not just in a tooltip.

## Stability, not optimisation

There is **no parameter optimisation** in this release. Instead:

**`walk_forward(series, signal_fn, folds=4)`** slices the sample into sequential folds, runs
with the *same* parameters, and returns per-fold metrics plus a stability verdict
(`consistent` / `mixed` / `fragile`) based on how many folds have positive Sharpe. It refuses
to run at all when the sample is too short for the requested folds — it does not silently
produce two folds and call it four.

**`train_test_split_backtest(train_pct=0.7)`** reports in-sample vs out-of-sample metrics and
the **Sharpe degradation**. Most strategies degrade sharply out of sample. Showing that number
is the point.

## Why there is no "best strategy" ranking

`compare()` sorts by Sharpe descending, but the output is a table, not a recommendation, and it
carries the sample-size warning. On synthetic data, every result here is a **property of the
generator**, not a discovery about markets. The engine is honest; the data is not real. Both
facts are stated in the UI above the equity curve.

## Known limitations

- **Survivorship bias**: the universe is a static list of currently listed names. Delisted
  companies cannot appear, so long-only results are optimistic.
- **No corporate-action adjustment** beyond the synthetic series being generated continuously.
  Splits and bonuses are not modelled in the cost ledger.
- **Slippage is a constant**, not a function of size. Real impact is worse in small caps.
- **Liquidity** is a capacity *check* (max 2% of bar volume), not a price-impact model.
- **Taxes** beyond STT and stamp duty are ignored (STCG/LTCG are personal and time-dependent).
- **Intraday strategies** on synthetic 5-minute bars test the mechanics, not an edge.

Every one of these appears in the report's "Data limitations" section when a backtest is cited
as evidence.
