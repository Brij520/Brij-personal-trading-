"""Tiny stdlib-only client for the BTI API, shared by the example scripts.

Deliberately uses urllib rather than requests/httpx so the examples run in a
bare Python 3.11 environment with the server already running.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def call(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Cannot reach {BASE}. Start the server first: python3 scripts/run.py\n{exc}"
        ) from exc


def get(path: str) -> dict:
    return call("GET", path)


def text(path: str) -> str:
    """Fetch a plain-text response (report exports, CSV) rather than JSON."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"GET {path} -> HTTP {exc.code}: {exc.read().decode()}") from exc


def post(path: str, body: dict | None = None) -> dict:
    return call("POST", path, body or {})


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Plain-text table that stays readable in a terminal with no dependencies."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(out)


def warn_banner(payload: dict) -> str:
    """Print the data-honesty banner every example should show."""
    quality = payload.get("data_quality") or {}
    synthetic = quality.get("is_synthetic", True)
    score = quality.get("score", "?")
    kind = "SYNTHETIC DEMO DATA — not real market data" if synthetic else "real data"
    return f"[{kind}] quality {score}/100"


if __name__ == "__main__":
    status = get("/api/system/status")
    print(json.dumps(status.get("safety", {}), indent=2))
    print(table(["page", "endpoint"], [["system", "/api/system/status"]]))
    sys.exit(0)
