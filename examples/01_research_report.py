"""Run the full 14-agent pipeline and save the research report.

    python3 examples/01_research_report.py RELIANCE TCS HDFCBANK

Output: a summary table in the terminal and one markdown report per symbol in
research/reports/. Read the classification column carefully: on demo data the
best possible outcome is WATCHLIST, by design.
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import get, table, text, warn_banner

OUT = Path(__file__).resolve().parents[1] / "research" / "reports"


def main(symbols: list[str]) -> int:
    print(warn_banner(get("/api/market/overview")))
    print()
    rows = []
    for symbol in symbols:
        report = get(f"/api/research/{symbol}")
        risk = (report.get("risk") or {}).get("decision") or {}
        rows.append(
            [
                report["symbol"],
                report["classification"],
                f"{report['confidence'] * 100:.0f}%",
                str(len(report.get("findings", []))),
                "yes" if risk.get("approved") else "no",
                f"{report['data_quality']['score']}/100",
            ]
        )
        slug = f"{report['symbol']}-{report['run_id']}.md"
        OUT.mkdir(parents=True, exist_ok=True)
        markdown = text(f"/api/research/{symbol}/report?format=markdown")
        (OUT / slug).write_text(markdown, encoding="utf-8")
        print(f"saved {OUT / slug}")

        # Show the single most important sentence: why it was classified so.
        rationale = (report.get("committee") or {}).get("rationale") or report["summary"]
        print(f"  reason: {rationale}")
        for limitation in report.get("limitations", [])[:2]:
            print(f"  limitation: {limitation}")

    print()
    print(table(["symbol", "classification", "conf", "agents", "risk ok", "quality"], rows))
    print("\nClassification is a label for further study, never a recommendation.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or ["RELIANCE", "TCS", "HDFCBANK"]
    raise SystemExit(main([a.upper() for a in args]))
