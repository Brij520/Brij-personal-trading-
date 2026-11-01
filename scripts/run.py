#!/usr/bin/env python3
"""Development entrypoint.

Usage:
    python3 scripts/run.py            # http://0.0.0.0:8000
    PORT=8080 python3 scripts/run.py  # custom port

Binds to 0.0.0.0 so the sandbox preview proxy can reach it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "backend.api.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
        access_log=False,
    )
