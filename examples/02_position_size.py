"""Position sizing under the platform's risk limits — including refusals.

    python3 examples/02_position_size.py

Shows why a stop defines the size, and what a rejection looks like. The capital
is a placeholder: change it to something real before using any number here.
"""

from __future__ import annotations

from common import get, post, table

CAPITAL = 500_000.0


def main() -> int:
    limits = get("/api/risk/limits")
    print("Platform limits (defaults, not personal limits):")
    for key, value in limits["limits"].items():
        print(f"  {key:<26} {value}")
    print()

    cases = [
        ("Tight stop, normal size", "RELIANCE", 2900, 2820, 3100),
        ("Wide stop, small size", "RELIANCE", 2900, 2600, 3400),
        ("Stop too far for R:R", "TCS", 3900, 3700, 3980),
        ("Stop on wrong side", "INFY", 1500, 1520, 1700),
        ("Absurd target, tiny stop", "SBIN", 800, 798, 900),
    ]

    rows = []
    for label, symbol, entry, stop, target in cases:
        decision = post(
            "/api/risk/validate",
            {
                "symbol": symbol,
                "side": "LONG",
                "entry": entry,
                "stop_loss": stop,
                "target": target,
                "capital": CAPITAL,
            },
        )
        rows.append(
            [
                label,
                "APPROVED" if decision["approved"] else "REJECTED",
                decision["quantity"],
                decision["risk_amount"],
                decision["reward_risk"],
                (decision["reasons"] or [""])[0][:52],
            ]
        )

    print(table(["case", "verdict", "qty", "risk ₹", "R:R", "first reason"], rows))
    print()
    print("Rejections are the feature, not an error. The risk engine cannot be")
    print("overridden in code, and no order is placed by this platform.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
