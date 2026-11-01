"""Full paper-trade lifecycle, ending with an honest review.

    python3 examples/05_paper_trade_cycle.py

Opens two trades, closes one at a loss and one at a profit, then prints the
performance summary and the weekly review. Trades are written to the same
paper journal the UI uses — delete var/journal.sqlite3 to reset.
"""

from __future__ import annotations

from datetime import date

from common import get, post, table


def main() -> int:
    before = get("/api/journal/performance")["summary"]
    print(f"closed trades before: {before['closed_trades']}")

    opened = []
    for symbol, entry, stop, target in [
        ("RELIANCE", 2900.0, 2820.0, 3100.0),
        ("TCS", 3900.0, 3820.0, 4150.0),
    ]:
        trade = post(
            "/api/journal/trades",
            {
                "symbol": symbol,
                "side": "LONG",
                "quantity": 10,
                "entry_date": date.today().isoformat(),
                "entry_price": entry,
                "stop_loss": stop,
                "target": target,
                "strategy": "example-script",
                "thesis": "example script trade — delete var/journal.sqlite3 to reset",
            },
        )
        opened.append(trade["trade"])
        print(f"opened #{trade['trade']['id']} {symbol} 10 @ {entry}")

    # One stopped out, one target hit — the realistic ratio, not a curated win.
    closed_loss = post(
        f"/api/journal/trades/{opened[0]['id']}/close",
        {"exit_price": 2820.0, "mistakes": "entered_without_reading_the_report"},
    )
    closed_win = post(
        f"/api/journal/trades/{opened[1]['id']}/close",
        {"exit_price": 4150.0},
    )
    for record in (closed_loss["trade"], closed_win["trade"]):
        print(
            f"closed #{record['id']} {record['symbol']} pnl ₹{record['pnl']:.2f} "
            f"({record['r_multiple']:.2f}R)"
        )

    stats = get("/api/journal/performance")["summary"]
    rows = [
        ["closed trades", stats["closed_trades"]],
        ["win rate", f"{stats['win_rate_pct']:.1f}%"],
        ["expectancy", f"₹{stats['expectancy']:.2f}"],
        ["profit factor", "n/a" if stats["profit_factor"] is None else f"{stats['profit_factor']:.2f}"],
        ["average R", f"{stats['avg_r_multiple']:.2f}"],
        ["sample warning", stats["sample_warning"] or "none"],
    ]
    print()
    print(table(["metric", "value"], [[str(a), str(b)] for a, b in rows]))

    review = get("/api/journal/review?period=weekly")
    print("\nWeekly review proposals (never auto-applied):")
    for proposal in review.get("proposals", [])[:4]:
        print(f"  - {proposal['proposal']}")
        if proposal.get("requires"):
            print(f"    requires: {proposal['requires']}")
        print(f"    approved_automatically: {proposal['approved_automatically']}")
    for observation in review.get("observations", [])[:3]:
        print(f"  observation: {observation}")

    print("\nThe journal records what you did. It does not tell you what to do next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
