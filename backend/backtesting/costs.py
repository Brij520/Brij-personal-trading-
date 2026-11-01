"""Indian equity transaction cost model (equity delivery and intraday).

Rates reflect the published schedule for NSE cash-segment equity as of 2025-26
and are stored as data so they can be updated without touching the engine.
Tax rules change; keep this table under review (see docs/backtesting.md).

Slippage is modelled explicitly and separately, because transaction costs are
knowable and slippage is an assumption. Both are reported in every backtest.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Percentage rates applied to turnover (one side).
BROKERAGE_DELIVERY_PCT = 0.03        # discount-broker delivery brokerage, per side
BROKERAGE_INTRADAY_MAX_PCT = 0.03    # or flat cap per executed order
BROKERAGE_INTRADAY_FLAT = 20.0
STT_DELIVERY_PCT = 0.10              # both sides on delivery
STT_INTRADAY_SELL_PCT = 0.025        # sell side only
EXCHANGE_TXN_PCT = 0.00297
SEBI_TURNOVER_PCT = 0.0001
STAMP_DUTY_BUY_PCT = 0.015
IPFT_PCT = 0.0001
GST_PCT = 18.0                        # on brokerage + exchange + SEBI + IPFT


@dataclass
class CostConfig:
    segment: str = "delivery"  # delivery | intraday
    slippage_bps: float = 5.0
    brokerage_pct: float | None = None
    brokerage_flat: float | None = None
    gst_pct: float = GST_PCT

    def brokerage(self, turnover: float) -> float:
        if self.segment == "delivery":
            pct = self.brokerage_pct if self.brokerage_pct is not None else BROKERAGE_DELIVERY_PCT
            return turnover * pct / 100.0
        pct = self.brokerage_pct if self.brokerage_pct is not None else BROKERAGE_INTRADAY_MAX_PCT
        flat = self.brokerage_flat if self.brokerage_flat is not None else BROKERAGE_INTRADAY_FLAT
        return min(turnover * pct / 100.0, flat)

    def charges(self, turnover: float, side: str) -> dict[str, float]:
        """Statutory + broker charges for one side of one trade."""
        broker = self.brokerage(turnover)
        exchange = turnover * EXCHANGE_TXN_PCT / 100.0
        sebi = turnover * SEBI_TURNOVER_PCT / 100.0
        ipft = turnover * IPFT_PCT / 100.0
        gst = (broker + exchange + sebi + ipft) * self.gst_pct / 100.0
        if self.segment == "delivery":
            stt = turnover * STT_DELIVERY_PCT / 100.0
            stamp = turnover * STAMP_DUTY_BUY_PCT / 100.0 if side == "BUY" else 0.0
        else:
            stt = turnover * STT_INTRADAY_SELL_PCT / 100.0 if side == "SELL" else 0.0
            stamp = turnover * STAMP_DUTY_BUY_PCT / 100.0 if side == "BUY" else 0.0
        total = broker + exchange + sebi + ipft + gst + stt + stamp
        return {
            "brokerage": round(broker, 2),
            "exchange": round(exchange, 2),
            "sebi": round(sebi, 2),
            "ipft": round(ipft, 2),
            "gst": round(gst, 2),
            "stt": round(stt, 2),
            "stamp_duty": round(stamp, 2),
            "total": round(total, 2),
        }

    def slippage(self, price: float, side: str) -> float:
        """Fill price after slippage: buys fill higher, sells lower."""
        drift = price * self.slippage_bps / 10_000.0
        return price + drift if side == "BUY" else price - drift

    def round_trip_total(self, buy_value: float, sell_value: float) -> dict[str, float]:
        buy = self.charges(buy_value, "BUY")
        sell = self.charges(sell_value, "SELL")
        return {
            "buy": buy["total"],
            "sell": sell["total"],
            "total": round(buy["total"] + sell["total"], 2),
            "pct_of_buy_value": round((buy["total"] + sell["total"]) / buy_value * 100, 4)
            if buy_value
            else 0.0,
        }


@dataclass
class LiquidityConfig:
    #: Maximum percentage of a bar's traded volume a single order may consume.
    max_pct_of_bar_volume: float = 2.0
    #: Orders above this value are flagged as potentially market-moving.
    large_order_value: float = 5_000_000.0

    def capacity(self, bar_volume: int, price: float) -> float:
        return bar_volume * self.max_pct_of_bar_volume / 100.0 * price

    def check(self, quantity: int, price: float, bar_volume: int) -> dict[str, object]:
        value = quantity * price
        capacity = self.capacity(bar_volume, price)
        return {
            "order_value": round(value, 2),
            "bar_capacity_value": round(capacity, 2),
            "within_liquidity": value <= capacity,
            "large_order": value > self.large_order_value,
        }
