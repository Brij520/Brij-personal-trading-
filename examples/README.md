# Examples

Runnable scripts that talk to the API over HTTP. They use **only the standard library**
(`urllib`), so they work in a bare Python environment with the server running.

```bash
python3 scripts/run.py &                       # terminal on :8000
python3 examples/01_research_report.py RELIANCE TCS
```

| Script | What it demonstrates |
|---|---|
| [`common.py`](common.py) | Tiny client, plain-text table renderer, honesty banner. Import it from your own scripts. |
| [`01_research_report.py`](01_research_report.py) | Runs all 14 agents, prints the classification and why, exports markdown to `research/reports/`. |
| [`02_position_size.py`](02_position_size.py) | Sizing under the limits **and the refusals** — wrong-side stops, R:R below 1.5, heat breaches. |
| [`03_backtest_compare.py`](03_backtest_compare.py) | Eight strategies side by side, then walk-forward stability and out-of-sample decay for the best one. |
| [`04_screener.py`](04_screener.py) | Runs scans, shows only the columns each scan actually computes, writes watchlists to `research/watchlists/`. |
| [`05_paper_trade_cycle.py`](05_paper_trade_cycle.py) | Opens and closes paper trades, then prints the performance summary and weekly review. |

## Things the examples deliberately show

- **`02` prints as many rejections as approvals.** The risk engine refusing a proposal is the
  feature; a demo that only shows approvals would teach the wrong lesson.
- **`03` prints the sample-size flag and the out-of-sample degradation**, not just the best
  Sharpe. A strategy with 5 trades is labelled as such.
- **`04` hides columns a scan did not compute** rather than printing `0`. A missing number and a
  zero are different things.
- **`05` prints `approved_automatically: False`** on every proposal, and the review refuses to
  recommend a strategy change below 20 closed trades.

## Resetting state

These scripts write to the paper journal (`var/journal.sqlite3`) and to `research/`. Both are
git-ignored. To start over:

```bash
rm -f var/journal.sqlite3 && rm -rf research/reports/* research/watchlists/*
```

## Writing your own

```python
from common import get, post

report = get("/api/research/INFY")
print(report["classification"], report["confidence"])
print("\n".join(report["limitations"][:5]))

decision = post("/api/risk/validate", {
    "symbol": "INFY", "side": "LONG",
    "entry": 1500, "stop_loss": 1450, "target": 1650,
    "capital": 500000,
})
print(decision["approved"], decision["reasons"])
```

Two habits worth keeping: check `data_quality.is_synthetic` before believing any number, and
read `reasons` on a rejection before adjusting the inputs to make it pass.
