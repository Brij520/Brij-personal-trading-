"""Run screener scans and write the results to a watchlist file.

    python3 examples/04_screener.py quality momentum

Every condition used is printed alongside the results — there is no hidden
composite score. Output goes to research/watchlists/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from common import get, table

OUT = Path(__file__).resolve().parents[1] / "research" / "watchlists"


def main(scans: list[str]) -> int:
    definitions = {d["key"]: d for d in get("/api/screener/definitions")["definitions"]}
    unknown = [s for s in scans if s not in definitions]
    if unknown:
        print(f"unknown scans: {unknown}. available: {sorted(definitions)}")
        return 2

    for scan in scans:
        payload = get(f"/api/screener?scans={scan}&limit=12")
        print(f"\n=== {scan} — {definitions[scan]['description']}")

        # Only show the columns this scan actually computes: a momentum scan does
        # not load statements, so printing "quality 0" would be a lie, not a zero.
        candidates = [
            ("quality_score", "quality", "{:.0f}"),
            ("roe_pct", "roe %", "{:.1f}"),
            ("revenue_cagr_3y_pct", "rev 3y %", "{:.1f}"),
            ("pe", "P/E", "{:.1f}"),
            ("momentum_6m_pct", "mom 6m %", "{:.1f}"),
            ("rsi14", "rsi", "{:.1f}"),
            ("distance_200dma_pct", "vs 200dma %", "{:.1f}"),
        ]
        present = [
            (key, label, fmt)
            for key, label, fmt in candidates
            if payload["results"] and payload["results"][0].get(key) is not None
        ]

        def cell(row, key, fmt):
            value = row.get(key)
            return "—" if value is None else fmt.format(value)

        rows = [
            [row["symbol"], row["sector"][:18]] + [cell(row, k, f) for k, _, f in present]
            for row in payload["results"]
        ]
        headers = ["symbol", "sector"] + [label for _, label, _ in present]
        print(table(headers, rows))
        print(f"universe scanned: {payload['universe']} · conditions: {payload['conditions']}")

        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{scan}.txt"
        path.write_text("\n".join(r[0] for r in rows) + "\n", encoding="utf-8")
        print(f"written {path}")

    print("\nA screen is a starting point for research, not a buy list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["quality", "momentum"]))
