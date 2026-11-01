"""Compare the eight strategies on one symbol, honestly.

    python3 examples/03_backtest_compare.py TCS

Prints a table and, for the top strategy, its out-of-sample decay. Most
strategies look fine in-sample; the interesting number is the degradation.
"""

from __future__ import annotations

import sys

from common import get, post, table, warn_banner


def main(symbol: str) -> int:
    strategies = get("/api/backtest/strategies")["strategies"]
    keys = [s["key"] for s in strategies]
    print(warn_banner(get(f"/api/stocks/{symbol}/quote")))
    print()

    payload = post(
        "/api/backtest/compare",
        {"symbol": symbol, "strategies": keys, "lookback": 1500},
    )
    rows = []
    for item in payload["comparison"]:
        rows.append(
            [
                item["strategy"],
                f"{item['cagr_pct']:.2f}",
                f"{item['sharpe']:.2f}",
                f"{item['max_drawdown_pct']:.2f}",
                f"{item['trades']:.0f}",
                f"{item['win_rate_pct']:.0f}%",
                "small sample" if (item.get("trades") or 0) < 20 else "",
            ]
        )
    print(table(["strategy", "cagr %", "sharpe", "maxDD %", "trades", "win", "flag"], rows))

    best_key = next(s["key"] for s in strategies if s["name"] == payload["comparison"][0]["strategy"])
    detail = post(
        "/api/backtest/run",
        {"symbol": symbol, "strategy": best_key, "lookback": 1500},
    )
    wf = detail.get("walk_forward") or {}
    print(f"\nWalk-forward stability for {best_key}: {(wf.get('stability') or {}).get('verdict')}")
    for fold in wf.get("folds", []):
        m = fold["metrics"]
        print(f"  {fold['label']} {fold['start']}..{fold['end']}  sharpe {m['sharpe']:>6.2f}  "
              f"trades {m['trades']:>3.0f}  return {m['total_return_pct']:>7.2f}%")
    oos = detail.get("out_of_sample") or {}
    if oos:
        print(f"  out-of-sample Sharpe degradation: {oos.get('sharpe_degradation')}")
    print("\nThis is stability evidence, not a recommendation. No parameter was optimised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main((sys.argv[1] if len(sys.argv) > 1 else "TCS").upper()))
