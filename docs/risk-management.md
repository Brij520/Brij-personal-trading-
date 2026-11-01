# Risk management

Risk is the only agent in this platform with authority. Everything else produces evidence;
risk produces an *answer*, and `overridable` is hard-coded `False` in `RiskDecision`.

`backend/analytics/risk.py` is pure functions over numbers. `backend/agents/risk_management.py`
is the agent that calls them, attaches context, and reasons in prose.

## The six limits

```python
RiskLimits(
    capital                  = 20_000,     # attached ₹20,000 paper portfolio challenge
    max_position_risk_pct    = 2.0,        # risk per trade, % of capital
    max_portfolio_heat_pct   = 6.0,        # sum of open risk, % of capital
    max_single_stock_pct     = 15.0,       # position value, % of capital
    max_sector_pct           = 35.0,       # sector exposure, % of capital
    daily_loss_limit_pct     = 3.0,        # stop trading for the day
    min_reward_risk          = 1.5,
    max_leverage             = 1.0,        # no leverage, ever
)
```

All are environment-configurable (`BTI_MAX_POSITION_RISK_PCT`, …). **They are platform
defaults, not personal limits.** Any output of `POST /api/risk/position-size` is meaningless
until capital is set to reality — the UI requires you to type it and the API echoes it back.

## Sizing

Given capital `C`, entry `E`, stop `S`:

```
risk_per_share = |E − S|
risk_budget    = C × max_position_risk_pct / 100
qty_by_risk    = floor(risk_budget / risk_per_share)
qty_by_value   = floor(C × max_single_stock_pct / 100 / E)
qty            = min(qty_by_risk, qty_by_value)
```

Three sizing methods are available and all return their own worked derivation:

| Method | Use | Signature |
|---|---|---|
| Risk-based | Default; stops define size | `risk_based_sizing(capital, entry, stop, risk_pct, max_position_pct=…)` |
| ATR-based | Volatility-adaptive stop | `atr_based_sizing(capital, entry, atr, atr_multiplier, risk_pct)` → stop = `entry − k·ATR` |
| Volatility-targeted | Equalise volatility contribution | `volatility_targeted_size(capital, annual_vol, target_vol)` |

Worked example (asserted in `tests/unit/`): capital 5,00,000, entry 100, stop 95, risk 1% →
risk budget 5,000 → 1,000 shares. At ATR 2 and multiplier 2 the stop moves to 96, and size
becomes ≈1,250 shares. **The stop defines the size — never the other way round.**

Kelly is implemented (`kelly_fraction(p, avg_win, avg_loss)`) and used **only as an upper
bound**, capped at the 2% rule. Full Kelly on a handful of trades is how accounts die; the
agent says so in its limitations.

## What gets a proposal rejected

Checked in this order (`validate_proposal`):

1. **F&O** — rejected unconditionally: *"F&O trading is disabled in this build."*
2. **Non-positive prices** — rejected.
3. **Stop/target on the wrong side of entry** — rejected with the exact numbers.
4. **Reward:risk below 1.5** — rejected. The ratio is rounded to 2 dp before comparison, so a
   computed 1.4999996 does not produce the absurd message "1.50 is below 1.50".
5. **Size rounds to zero** — rejected, because "the stop is too wide for this capital" is real
   information, not a rounding detail.
6. **Position value > capital** — rejected (no leverage).
7. **Portfolio heat > 6%** — rejected, with the resulting heat shown.
8. **Non-positive capital** — rejected.

Warnings that do *not* reject but are always surfaced:

- stop > 12% away: "wide for a single trade";
- stop < 0.4% away: "inside typical noise, likely to be hit by spread";
- stop < 0.8× ATR: "random noise can stop this trade out";
- open risk already at 5%+ of the heat limit.

Every decision also returns a disclaimer: risk approval is a controls check, not a
recommendation and not authorisation to trade.

## Portfolio-level risk

`backend/analytics/risk.py` + `backend/agents/portfolio_manager.py`:

- **Concentration** — HHI, top-1 and top-5 weight. >15% single name or HHI >0.20 is flagged.
- **Sector exposure** — aggregated and compared with the 35% cap; excess is named per sector.
- **Correlation clusters** — holdings that move together are grouped, and the agent reports
  the *effective* number of independent positions rather than the raw count.
- **Volatility & beta** — annualised portfolio σ from the weighted return series, β vs NIFTY.
- **VaR** — historical, 95% and 99%, 1-day and scaled horizon, reported as a rupee loss and as
  a % of capital, with the explicit caveat that historical VaR says nothing about a gap.

Every portfolio metric that needs a return history returns `None` + a reason when it has
fewer than 60 observations. It does not compute a beta from 12 days.

## Daily loss limit

`daily_loss_check(day_pnl, capital, limits)` returns a hard `halt: True` once the day's loss
exceeds 3%. The UI renders it in red and the journal's discipline review counts any trade
opened after a halt was signalled as a process violation.

## Why this exists

Not because the maths is sophisticated — it is deliberately boring — but because the failure
mode of a research tool used by one person is not a bad model. It is **size**. A correct
thesis at 40% of capital is a wrong trade, and the only defence that works is a limit that
cannot be argued with at 09:20 while a position is moving against you.

## What this module does not model

- **SPAN/Exposure margin** for F&O — not implemented, so option payoff panels report margin as
  unknown rather than guessing.
- **Gap risk** — a stop is not a guarantee. Backtests fill at the stop only if the bar allows;
  a gap is filled at the open, and the results show it.
- **Liquidity impact** — modelled as a *check* (`LiquidityConfig`, ≤2% of bar volume), not as
  a price impact model. A position that fails the check is reported as capacity-constrained.
- **Taxes** beyond STT/stamp duty, and any personal tax position.
