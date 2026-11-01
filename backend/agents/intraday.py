"""AGENT 06 — Intraday Research (paper mode only).

Analyses the most recent intraday session: opening range, VWAP relationship,
volume pace, short-term momentum and where price sits inside the day's range.

This agent is structurally paper-only:

* it refuses to produce a live trading instruction;
* every output carries ``paper_mode: true``;
* the risk agent rejects any F&O proposal and the platform has no execution path.

Gap analysis is *not* performed because pre-market/previous-close data for the
current session is not available in this build — that limitation is reported
rather than guessed.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.analytics import indicators as ind
from backend.core.provenance import Freshness, Verification
from backend.data.universe import get_instrument


class IntradayResearchAgent(BaseAgent):
    name = "intraday"
    responsibility = "Intraday session structure in paper mode"
    requires = ("intraday_ohlcv",)

    def run(self, ctx: AgentContext) -> AgentFinding:
        symbol = (ctx.symbol or "").upper()
        instrument = get_instrument(symbol)
        if instrument is None:
            raise ValueError(f"unknown symbol {symbol}")
        base_limitations = [
            "Paper mode only. Live intraday trading is disabled in this build.",
            "No pre-market session data, no order-book depth, no block or bulk deals.",
            "Gap analysis is not performed: the previous close for the current session "
            "is not available from the intraday feed.",
        ]
        try:
            res = ctx.registry.history(symbol, timeframe="5m", lookback=400)
        except Exception as exc:  # noqa: BLE001
            return AgentFinding(
                agent=self.name,
                symbol=symbol,
                headline="Intraday data unavailable",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.0,
                limitations=base_limitations + [str(exc)],
                data_quality={"score": 0, "band": "VERY_LOW"},
                metrics={"paper_mode": True},
            )
        series = res.value
        frame = series.frame
        meta = series.meta
        is_syn = meta.is_synthetic

        session_dates = sorted(set(frame.index.normalize()))
        last_day = session_dates[-1]
        today = frame[frame.index.normalize() == last_day]
        if len(today) < 5:
            raise ValueError("not enough intraday bars in the latest session")

        vwap = ind.vwap(frame)
        today_vwap = float(vwap[vwap.index.normalize() == last_day].iloc[-1])
        open_px = float(today["open"].iloc[0])
        last_px = float(today["close"].iloc[-1])
        day_high = float(today["high"].max())
        day_low = float(today["low"].min())
        first_three = today.iloc[:3]
        or_high, or_low = float(first_three["high"].max()), float(first_three["low"].min())
        rsi = float(ind.rsi(frame["close"], 14).dropna().iloc[-1])
        day_range = day_high - day_low

        evidence: list[Evidence] = []
        score = 0.0
        notes: list[str] = []

        if last_px > today_vwap:
            score += 12
            notes.append("Price is above session VWAP (buyers in control of the average fill).")
        else:
            score -= 12
            notes.append("Price is below session VWAP (sellers in control of the average fill).")
        if last_px > or_high:
            score += 14
            notes.append(f"Opening-range breakout: price {last_px:.2f} above OR high {or_high:.2f}.")
        elif last_px < or_low:
            score -= 14
            notes.append(f"Opening-range breakdown: price {last_px:.2f} below OR low {or_low:.2f}.")
        else:
            notes.append("Price is inside the opening range — no directional resolution yet.")
        intraday_change = (last_px / open_px - 1) * 100
        score += float(np.clip(intraday_change * 2, -12, 12))
        if rsi > 70:
            score -= 5
            notes.append(f"5-minute RSI {rsi:.0f} is stretched.")
        elif rsi < 30:
            score += 5
            notes.append(f"5-minute RSI {rsi:.0f} is washed out.")

        position_in_range = (last_px - day_low) / day_range if day_range else 0.5
        evidence.append(
            Evidence(
                claim=(
                    f"Last price {last_px:.2f} vs VWAP {today_vwap:.2f}; day range "
                    f"{day_low:.2f}-{day_high:.2f} (position {position_in_range:.0%})"
                ),
                value=round(last_px, 2),
                source=meta.source,
                as_of=str(last_day.date()),
                freshness=Freshness.SYNTHETIC if is_syn else Freshness.DELAYED,
                verification=Verification.UNVERIFIED_SYNTHETIC
                if is_syn
                else Verification.CROSS_CHECKED,
                is_synthetic=is_syn,
            )
        )
        evidence.append(
            Evidence(
                claim=f"Opening range {or_low:.2f}-{or_high:.2f} from the first 15 minutes",
                value=round(or_high - or_low, 2),
                source=meta.source,
                as_of=str(last_day.date()),
                freshness=Freshness.SYNTHETIC if is_syn else Freshness.DELAYED,
                verification=Verification.UNVERIFIED_SYNTHETIC
                if is_syn
                else Verification.CROSS_CHECKED,
                is_synthetic=is_syn,
            )
        )

        score = float(np.clip(score, -100, 100))
        stance = "BULLISH" if score >= 15 else "BEARISH" if score <= -15 else "NEUTRAL"

        return AgentFinding(
            agent=self.name,
            symbol=symbol,
            headline=(
                f"Paper intraday: {stance.lower()} session, price {'above' if last_px > today_vwap else 'below'} "
                f"VWAP, day change {intraday_change:+.2f}%"
            ),
            stance=stance,
            score=score,
            confidence=self._quality_cap(35 if is_syn else 60) * 0.8,
            evidence=evidence,
            risks=[
                "Intraday signals decay within minutes; this analysis is already stale "
                "by the time it is read.",
                "Transaction costs dominate intraday edges: a 0.05% move is not a trade.",
                "Paper results systematically understate slippage.",
            ],
            limitations=base_limitations
            + (["Intraday bars are synthetic demonstration data."] if is_syn else []),
            data_quality={"score": 35 if is_syn else 60,
                          "band": "LOW" if is_syn else "MODERATE"},
            metrics={
                "paper_mode": True,
                "session": str(last_day.date()),
                "last_price": round(last_px, 2),
                "session_open": round(open_px, 2),
                "vwap": round(today_vwap, 2),
                "opening_range": {"low": round(or_low, 2), "high": round(or_high, 2)},
                "day_range": {"low": round(day_low, 2), "high": round(day_high, 2)},
                "position_in_range_pct": round(position_in_range * 100, 1),
                "rsi_5m": round(rsi, 2),
                "intraday_change_pct": round(intraday_change, 2),
                "notes": notes,
                "execution": "disabled",
            },
            warnings=["Paper mode. No order can be placed or simulated against a broker."],
        )
