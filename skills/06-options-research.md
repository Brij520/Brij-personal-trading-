# 06 · Options research

The platform researches option structures. It cannot price margin and cannot place anything.
Read the disclaimers as literal.

## What the options page gives you

- **Chain** with IV, OI, volume, and change in OI at each strike.
- **Greeks** from Black-Scholes on the observed IV.
- **PCR** (OI and volume) — a positioning gauge, not a prediction.
- **Max pain** — the strike with the largest pain to option holders. It is a description of
  where open interest sits, not a magnet you can trade.
- **ATM straddle cost** — the move the market is pricing over the expiry.
- **Payoff builder** — multi-leg structures with breakevens and max profit/loss.

## The four uses that are genuinely research

1. **Reading expectation, not direction.** A straddle costing 2.5% implies a ±2.5% move. If your
   thesis needs 6%, the market disagrees with you by a lot — useful information either way.
2. **Positioning.** PCR at an extreme with falling OI tells you a crowd is unwinding, not that a
   reversal is coming.
3. **Structure comparison.** Two structures with the same view, different breakevens and
   capital at risk. Build both, compare payoffs at −3%, 0, +3%, +6%.
4. **Cost of being wrong.** Max loss on a defined-risk structure is knowable in advance. If you
   cannot state it, the structure is not defined-risk, whatever it is called.

## What the page deliberately does not do

- **Margin.** It returns `margin: null` with a reason. SPAN and Exposure margins are not
  modelled, and a guessed number here is worse than no number.
- **Order construction.** There is no basket, no order ticket, no broker session. `fno_enabled`
  is `false` in code, not in a setting.
- **Probability of profit.** It is not computed, because a probability derived from a synthetic
  IV surface would be a fabricated number wearing a percentage sign.

## The discipline

Options reward being precisely wrong, which is why they punish imprecision so well. Before any
F&O idea: what is the maximum loss, what is the breakeven, what is the expiry risk, and what
happens if implied volatility drops 20% with the underlying unchanged? If all four answers are
not immediate, the idea is not ready.
