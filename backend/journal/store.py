"""Personal trading journal and paper-trading ledger (SQLite).

Privacy: this database lives in ``var/`` which is git-ignored. It is the one
place personal holdings and trade history are stored, and it is never committed.

Everything here is *paper*. The ledger records intended trades and their
outcomes for review. It has no connection to a broker and no function that can
submit an order.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from backend.core.errors import NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.core.provenance import utcnow

log = get_logger("journal")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol            TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('LONG','SHORT')),
    status            TEXT NOT NULL DEFAULT 'OPEN'
                      CHECK (status IN ('OPEN','CLOSED','CANCELLED')),
    mode              TEXT NOT NULL DEFAULT 'PAPER' CHECK (mode IN ('PAPER')),
    strategy          TEXT,
    thesis            TEXT,
    market_conditions TEXT,
    entry_date        TEXT NOT NULL,
    entry_price       REAL NOT NULL,
    quantity          REAL NOT NULL,
    stop_loss         REAL,
    target            REAL,
    exit_date         TEXT,
    exit_price        REAL,
    costs             REAL DEFAULT 0,
    pnl               REAL,
    pnl_pct           REAL,
    r_multiple        REAL,
    mistakes          TEXT,
    lessons           TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    sector      TEXT,
    quantity    REAL NOT NULL,
    avg_price   REAL NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at    TEXT NOT NULL,
    total_value REAL NOT NULL,
    invested    REAL NOT NULL,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- research | lesson | market
    symbol      TEXT,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    tags        TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    period      TEXT NOT NULL,          -- daily | weekly | monthly
    period_key  TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
"""


@dataclass
class TradeRecord:
    id: int
    symbol: str
    side: str
    status: str
    mode: str
    strategy: str | None
    thesis: str | None
    market_conditions: str | None
    entry_date: str
    entry_price: float
    quantity: float
    stop_loss: float | None
    target: float | None
    exit_date: str | None
    exit_price: float | None
    costs: float
    pnl: float | None
    pnl_pct: float | None
    r_multiple: float | None
    mistakes: str | None
    lessons: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


TRADE_FIELDS = (
    "id", "symbol", "side", "status", "mode", "strategy", "thesis",
    "market_conditions", "entry_date", "entry_price", "quantity", "stop_loss",
    "target", "exit_date", "exit_price", "costs", "pnl", "pnl_pct", "r_multiple",
    "mistakes", "lessons", "created_at",
)


class JournalStore:
    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            from backend.core.config import get_settings

            path = get_settings().sqlite_path
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- trades
    def add_trade(self, payload: dict[str, Any]) -> TradeRecord:
        required = ("symbol", "entry_price", "quantity", "entry_date")
        missing = [k for k in required if payload.get(k) in (None, "")]
        if missing:
            raise ValidationError(f"trade is missing required fields: {missing}")
        side = str(payload.get("side", "LONG")).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValidationError("side must be LONG or SHORT")
        entry_price = float(payload["entry_price"])
        quantity = float(payload["quantity"])
        if entry_price <= 0 or quantity <= 0:
            raise ValidationError("entry_price and quantity must be positive")
        now = utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (symbol, side, status, mode, strategy, thesis,
                    market_conditions, entry_date, entry_price, quantity, stop_loss,
                    target, costs, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload["symbol"]).upper(),
                    side,
                    "OPEN",
                    "PAPER",
                    payload.get("strategy"),
                    payload.get("thesis"),
                    payload.get("market_conditions"),
                    str(payload["entry_date"]),
                    entry_price,
                    quantity,
                    payload.get("stop_loss"),
                    payload.get("target"),
                    float(payload.get("costs") or 0.0),
                    now,
                ),
            )
            trade_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return TradeRecord(**dict(row))

    def close_trade(self, trade_id: int, payload: dict[str, Any]) -> TradeRecord:
        exit_price = float(payload.get("exit_price") or 0)
        if exit_price <= 0:
            raise ValidationError("exit_price must be positive")
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"trade {trade_id} not found")
            if row["status"] != "OPEN":
                raise ValidationError(f"trade {trade_id} is already {row['status']}")
            entry = float(row["entry_price"])
            qty = float(row["quantity"])
            sign = 1 if row["side"] == "LONG" else -1
            gross = (exit_price - entry) * qty * sign
            costs = float(row["costs"] or 0) + float(payload.get("costs") or 0)
            pnl = gross - costs
            invested = entry * qty
            per_share_risk = (
                (entry - float(row["stop_loss"])) if row["side"] == "LONG" and row["stop_loss"]
                else (float(row["stop_loss"]) - entry) if row["stop_loss"] else None
            )
            r_multiple = (
                (pnl / (per_share_risk * qty)) if per_share_risk and per_share_risk > 0 else None
            )
            conn.execute(
                """
                UPDATE trades SET status='CLOSED', exit_date=?, exit_price=?, costs=?,
                    pnl=?, pnl_pct=?, r_multiple=?, mistakes=?, lessons=?
                WHERE id=?
                """,
                (
                    str(payload.get("exit_date") or date.today().isoformat()),
                    exit_price,
                    costs,
                    round(pnl, 2),
                    round(pnl / invested * 100, 2) if invested else None,
                    None if r_multiple is None else round(r_multiple, 2),
                    payload.get("mistakes"),
                    payload.get("lessons"),
                    trade_id,
                ),
            )
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return TradeRecord(**dict(row))

    def cancel_trade(self, trade_id: int, reason: str | None = None) -> TradeRecord:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"trade {trade_id} not found")
            if row["status"] != "OPEN":
                raise ValidationError(f"trade {trade_id} is already {row['status']}")
            conn.execute(
                "UPDATE trades SET status='CANCELLED', lessons=COALESCE(?, lessons) WHERE id=?",
                (reason, trade_id),
            )
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return TradeRecord(**dict(row))

    def list_trades(
        self, *, status: str | None = None, symbol: str | None = None, limit: int = 200
    ) -> list[TradeRecord]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status=?"
            params.append(status.upper())
        if symbol:
            query += " AND symbol=?"
            params.append(symbol.upper())
        query += " ORDER BY entry_date DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [TradeRecord(**dict(r)) for r in rows]

    def get_trade(self, trade_id: int) -> TradeRecord:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"trade {trade_id} not found")
        return TradeRecord(**dict(row))

    # -------------------------------------------------------------- holdings
    def upsert_holdings(self, rows: list[dict[str, Any]]) -> int:
        now = utcnow().isoformat()
        count = 0
        with self._conn() as conn:
            for row in rows:
                symbol = str(row["symbol"]).upper().strip()
                if not symbol:
                    continue
                conn.execute(
                    """
                    INSERT INTO holdings (symbol, name, sector, quantity, avg_price, updated_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        quantity=excluded.quantity,
                        avg_price=excluded.avg_price,
                        name=COALESCE(excluded.name, holdings.name),
                        sector=COALESCE(excluded.sector, holdings.sector),
                        updated_at=excluded.updated_at
                    """,
                    (
                        symbol,
                        row.get("name"),
                        row.get("sector"),
                        float(row["quantity"]),
                        float(row["avg_price"]),
                        now,
                    ),
                )
                count += 1
        return count

    def list_holdings(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM holdings ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    def delete_holding(self, symbol: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM holdings WHERE symbol=?", (symbol.upper(),))
        return cur.rowcount > 0

    # ------------------------------------------------------------- snapshots
    def add_snapshot(self, total_value: float, invested: float, payload: str | None = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (taken_at, total_value, invested, payload) VALUES (?,?,?,?)",
                (utcnow().isoformat(), total_value, invested, payload),
            )
            return int(cur.lastrowid)

    def list_snapshots(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY taken_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- notes
    def add_note(self, payload: dict[str, Any]) -> int:
        if not payload.get("title") or not payload.get("body"):
            raise ValidationError("note requires title and body")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO notes (created_at, kind, symbol, title, body, tags) VALUES (?,?,?,?,?,?)",
                (
                    utcnow().isoformat(),
                    payload.get("kind", "research"),
                    (payload.get("symbol") or None),
                    payload["title"],
                    payload["body"],
                    payload.get("tags"),
                ),
            )
            return int(cur.lastrowid)

    def list_notes(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM notes"
        params: list[Any] = []
        if kind:
            query += " WHERE kind=?"
            params.append(kind)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def save_review(self, period: str, period_key: str, payload: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO reviews (created_at, period, period_key, payload) VALUES (?,?,?,?)",
                (utcnow().isoformat(), period, period_key, payload),
            )
            return int(cur.lastrowid)

    def list_reviews(self, period: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        query = "SELECT * FROM reviews"
        params: list[Any] = []
        if period:
            query += " WHERE period=?"
            params.append(period)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            trades = conn.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]
            open_trades = conn.execute(
                "SELECT COUNT(*) c FROM trades WHERE status='OPEN'"
            ).fetchone()["c"]
            holdings = conn.execute("SELECT COUNT(*) c FROM holdings").fetchone()["c"]
        return {"trades": trades, "open_trades": open_trades, "holdings": holdings,
                "database": str(self.path)}
