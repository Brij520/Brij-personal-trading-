"""AGENT 04 — Technical Analysis.

Multi-timeframe structure: primary trend (200-DMA), intermediate (50-DMA),
short-term (20-EMA + MACD), momentum (RSI), volatility (ATR/Bollinger),
participation (volume, OBV) and price structure (support/resistance, fib).

Every statement is a *description of the tape*, not a prediction. Confidence is
capped by data quality and by how many independent confirmations agree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.analytics import indicators as ind
from backend.core.provenance import Freshness, Verification


class TechnicalAnalysisAgent(BaseAgent):
    name = "technical_analysis"
    responsibility = "Trend, momentum, structure and volatility from price data"
    requires = ("ohlcv",)

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        frame = bundle.technical_frame
        clean = frame.dropna(subset=["rsi14", "ema200"])
        if len(clean) < 60:
            raise ValueError("insufficient history for a technical read")
        row = clean.iloc[-1]
        close = float(row["close"])
        meta = bundle.series.meta
        is_syn = meta.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else meta.freshness
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.CROSS_CHECKED
        )

        def ev(claim: str, value: float | None = None, unit: str | None = None) -> Evidence:
            return Evidence(
                claim=claim,
                value=None if value is None else round(float(value), 2),
                unit=unit,
                source=meta.source,
                as_of=str(meta.period_end),
                freshness=freshness,
                verification=verification,
                is_synthetic=is_syn,
            )

        evidence: list[Evidence] = []
        votes: list[float] = []

        # -------------------------------------------------------- trend stack
        ema20, ema50, ema200 = float(row["ema20"]), float(row["ema50"]), float(row["ema200"])
        above_200 = close > ema200
        above_50 = close > ema50
        above_20 = close > ema20
        stack_bull = ema20 > ema50 > ema200
        stack_bear = ema20 < ema50 < ema200
        trend_score = (
            (15 if above_200 else -20)
            + (8 if above_50 else -8)
            + (6 if above_20 else -6)
            + (8 if stack_bull else -8 if stack_bear else 0)
        )
        votes.append(trend_score)
        evidence.append(
            ev(
                f"Price {close:,.2f} is "
                f"{'above' if above_200 else 'below'} the 200-DMA ({ema200:,.2f}); "
                f"EMA stack is {'bullish' if stack_bull else 'bearish' if stack_bear else 'mixed'}",
                trend_score,
            )
        )

        # ----------------------------------------------------------- momentum
        rsi = float(row["rsi14"])
        macd_hist = float(row["macd_hist"])
        macd_score = 0.0
        if rsi >= 70:
            macd_score -= 4
            evidence.append(ev(f"RSI {rsi:.1f} is overbought — extension risk", rsi))
        elif rsi <= 30:
            macd_score += 4
            evidence.append(ev(f"RSI {rsi:.1f} is oversold — mean-reversion risk both ways", rsi))
        elif rsi >= 55:
            macd_score += 8
            evidence.append(ev(f"RSI {rsi:.1f} shows momentum in the bullish half", rsi))
        elif rsi <= 45:
            macd_score -= 8
            evidence.append(ev(f"RSI {rsi:.1f} shows momentum in the bearish half", rsi))
        macd_score += 10 if macd_hist > 0 else -10
        evidence.append(
            ev(
                f"MACD histogram {'positive' if macd_hist > 0 else 'negative'} "
                f"({macd_hist:.3f})",
                macd_hist,
            )
        )
        votes.append(float(np.clip(macd_score, -20, 20)))

        # ------------------------------------------------------------- ADX
        adx_v = float(row["adx14"]) if pd.notna(row["adx14"]) else 0.0
        di_plus, di_minus = float(row["plus_di"] or 0), float(row["minus_di"] or 0)
        if adx_v >= 25:
            votes.append(10 if di_plus > di_minus else -10)
            evidence.append(
                ev(f"ADX {adx_v:.1f} confirms a directional move ({'bulls' if di_plus > di_minus else 'bears'} in control)")
            )
        else:
            evidence.append(ev(f"ADX {adx_v:.1f}: no strong directional trend"))

        # ------------------------------------------------- volume / structure
        vol_ratio = float(row["vol_ratio"]) if pd.notna(row["vol_ratio"]) else 1.0
        recent = clean.tail(60)
        obv_slope = float(np.polyfit(np.arange(len(recent)), recent["obv"], 1)[0])
        if abs(vol_ratio - 1) > 0.5:
            direction = 1 if float(row["ret_1d"]) > 0 else -1
            votes.append(4 * direction)
            evidence.append(
                ev(
                    f"Volume {vol_ratio:.2f}x the 20-day average with a "
                    f"{'positive' if direction > 0 else 'negative'} close — "
                    f"{'accumulation' if direction > 0 else 'distribution'} signal",
                    vol_ratio,
                )
            )
        evidence.append(
            ev(
                f"OBV slope {'rising' if obv_slope > 0 else 'falling'} over 60 sessions "
                f"({'confirms' if (obv_slope > 0) == above_200 else 'diverges from'} price)",
            )
        )
        if (obv_slope > 0) != above_50:
            votes.append(-6)

        # ------------------------------------------------------- divergence
        div = ind.detect_divergence(clean["close"], clean["rsi14"])
        if div["type"] != "none":
            votes.append(8 if div["type"] == "bullish" else -8)
            evidence.append(ev(f"{div['type'].title()} RSI divergence: {div['detail']}"))

        # ----------------------------------------------------------- levels
        sr = ind.support_resistance(frame, close)
        atr = float(row["atr14"])
        swing_low = float(frame["low"].tail(60).min())
        swing_high = float(frame["high"].tail(60).max())
        fib = ind.fibonacci_levels(swing_low, swing_high)
        dist_res = ((sr["resistance"][0] / close - 1) * 100) if sr["resistance"] else None
        dist_sup = ((sr["support"][0] / close - 1) * 100) if sr["support"] else None

        # ----------------------------------------------------- multi timeframe
        weekly = bundle.series.frame["close"].resample("W-FRI").last().dropna()
        weekly_trend = "up" if len(weekly) > 30 and weekly.iloc[-1] > ind.sma(weekly, 30).iloc[-1] else "down"
        daily_trend = "up" if above_200 else "down"
        alignment = "ALIGNED_UP" if (daily_trend == weekly_trend == "up") else (
            "ALIGNED_DOWN" if (daily_trend == weekly_trend == "down") else "CONFLICTING"
        )
        if alignment == "ALIGNED_UP":
            votes.append(10)
        elif alignment == "ALIGNED_DOWN":
            votes.append(-10)

        raw = float(np.clip(sum(votes), -100, 100))
        score = raw * 0.9
        stance = "BULLISH" if score >= 15 else "BEARISH" if score <= -15 else "NEUTRAL"
        # Agreement bonus/penalty: independent signals pointing the same way.
        directional = [v for v in votes if abs(v) > 3]
        agreement = (
            abs(sum(np.sign(directional))) / len(directional) if directional else 0.0
        )
        confidence = self._quality_cap(bundle.data_quality["score"]) * (0.55 + 0.45 * agreement)

        headline = (
            f"{bundle.symbol}: {alignment.replace('_', ' ').lower()} structure, "
            f"price {close:,.2f} vs 200-DMA {ema200:,.2f}, RSI {rsi:.1f}, "
            f"ATR {atr:,.2f} ({atr / close * 100:.1f}% of price)"
        )

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=headline,
            stance=stance,
            score=score,
            confidence=round(confidence, 3),
            evidence=evidence,
            risks=[
                f"Nearest resistance {sr['resistance'][0]:,.2f} ({dist_res:+.1f}%)" if dist_res is not None
                else "No clear resistance cluster above price.",
                f"Nearest support {sr['support'][0]:,.2f} ({dist_sup:+.1f}%)" if dist_sup is not None
                else "No clear support cluster below price.",
                f"Overbought RSI ({rsi:.0f}) raises pullback risk." if rsi > 70 else
                f"Oversold RSI ({rsi:.0f}) can stay oversold in a downtrend." if rsi < 30 else
                "Technical signals are interpretations of past prices, not forecasts.",
            ],
            limitations=[
                "No intraday order-flow, delivery-percentage or block-deal data.",
                "Indicator parameters are conventional defaults, not optimised for this stock.",
                "Technical analysis performs poorly around news gaps and corporate actions.",
            ]
            + (["Price series is SYNTHETIC demonstration data."] if is_syn else []),
            data_quality=bundle.data_quality,
            metrics={
                "price": round(close, 2),
                "indicators": bundle.latest_technical(),
                "trend_stack": {"ema20": ema20, "ema50": ema50, "ema200": ema200},
                "alignment": alignment,
                "weekly_trend": weekly_trend,
                "support": sr["support"],
                "resistance": sr["resistance"],
                "fibonacci": fib,
                "swing_60d": {"low": round(swing_low, 2), "high": round(swing_high, 2)},
                "atr_pct_of_price": round(atr / close * 100, 2),
                "rsi": round(rsi, 2),
                "divergence": div,
                "vote_breakdown": {
                    "trend": trend_score,
                    "momentum": macd_score,
                    "total": round(score, 1),
                },
                "agreement": round(agreement, 2),
            },
        )
