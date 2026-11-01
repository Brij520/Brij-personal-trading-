# 04 · Judging a backtest

A backtest that looks good is the default outcome of trying enough parameters. Your job is to
find the reason it is wrong.

## The five questions, in order

### 1. How many trades?
Under 20 and the number is noise, whatever the Sharpe ratio says. The platform flags this; the
flag is the finding.

### 2. What did costs do?
Read `total_costs` and `cost_drag_pct`. If the gross edge is smaller than the cost of
participating, the strategy does not exist in reality. Delivery STT alone is 0.10% each way;
a strategy trading twice a week pays for its own funeral.

### 3. Does it survive out of sample?
Run the train/test split. Most strategies look excellent in-sample and mediocre after. A large
`sharpe_degradation` is the normal result, not an anomaly — and it usually means the parameters
were fitted to a particular year.

### 4. Is the edge in every fold?
Read the walk-forward folds. One strong fold and three flat ones is a single regime, not an
edge. "Fragile" in the stability verdict means: do not trade this with real money.

### 5. What is the drawdown, in units of your patience?
`max_drawdown_pct` tells you the worst peak-to-trough. Ask: would I have kept running this
through that, without knowing it would recover? If no, the strategy is unusable regardless of
its CAGR.

## Red flags that mean "stop reading"

- Win rate > 80% with a small average win and a large average loss. One bad trade erases thirty
  good ones.
- A monotonic equity curve. Real strategies have flat periods; a curve with no flat periods is
  usually a lookahead bug or an over-fitted parameter.
- Outcomes that improve as you increase the sample's ending date. That is regime-dependence.
- Results computed on synthetic data being treated as evidence about markets. They are evidence
  about the *engine*, nothing more.

## What to do with a strategy that passes

Nothing, yet. The correct next step is not to trade it. It is to **paper trade it for 30
sessions** and compare its live behaviour to the backtest's assumptions. If the backtest assumed
5 bps of slippage and your fills are 15 bps worse, the strategy's entire edge may already be
gone — and now you know, for free.
