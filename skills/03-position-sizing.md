# 03 · Position sizing

Do this before every trade. It takes 60 seconds and it is the difference between a bad month
and a destroyed account.

## The procedure

1. **Set capital.** Risk page → capital field. The default ₹10,00,000 is a placeholder. Use the
   amount you would still be able to function with if it halved.
2. **Set the stop from the chart, not from the size.** Where is the setup actually wrong? A
   swing low, a structure break, 2× ATR. Not "wherever 2% is".
3. **Call `POST /api/risk/position-size`** (the Risk page does this): capital, entry, stop.
4. **Take the smaller of the two quantities**: risk-based and value-based. The engine already
   does this — do not override it upward.
5. **Check heat.** If the new position takes total open risk above 6%, the answer is no. Not
   "a smaller version of yes", no.
6. **Write the trade in the journal before placing anything** (you are paper trading anyway):
   entry, stop, target, R-multiple, and the invalidation sentence.

## The arithmetic everyone skips

```
qty = floor( (capital × risk% ) / |entry − stop| )
```

Capital ₹5,00,000, risk 1%, entry ₹1,000, stop ₹950:

```
risk budget = 5,000
risk/share  = 50
qty         = 100 shares → position ₹1,00,000 (20% of capital)
```

That is a large position for a 5% stop, which is why value-based sizing caps it at 15% of
capital here (75 shares). **A tight stop does not make a big position safe** — it makes the
position get stopped out by noise, repeatedly.

## Rules that are not negotiable

- **Never widen a stop to avoid being stopped.** The size was derived from it. Widening the stop
  turns a 1% risk into a 2%+ risk with no new information.
- **Never add to a loser.** That is doubling risk when evidence is negative.
- **Never size from a target.** "It could double" is not part of the formula.
- **One position per idea.** Two banks is one sector bet with two names.
- **F&O is rejected by the engine, always.** If you find yourself computing option margin by
  hand, you have left the tool's guard rails.

## After the trade

Record the R-multiple, not just the P&L. A +₹2,000 win on a 0.5R position and a −₹4,000 loss on
a 2R position are the *same trade* read two ways; only R tells you whether the process worked.
