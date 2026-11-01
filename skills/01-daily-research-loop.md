# 01 · The daily research loop

**Time:** 20 minutes, after the close. **Output:** one journal note and zero forced trades.

Most days the correct output is "nothing today". A loop that must produce a trade is a loop
that manufactures one.

## The loop

### 1. Read the tape, not the news (4 min)
Open **Dashboard**. Answer three questions and write the answers, not impressions:

- Is NIFTY above or below its 50- and 200-DMA? (breadth panel)
- Are advances > declines? By how much?
- Which two sectors led and which two lagged over 20 days?

If breadth is negative and the index is below the 200-DMA, **stop here**. There is no
"but this one stock" exception in a tape like that. Close the terminal.

### 2. Review open positions (5 min)
**Journal** → open trades. For each one, check only:

- Has the stop been hit? If yes, it is closed. No "it will come back."
- Has the thesis-invalidation condition (written when you opened it) occurred?
- Has the position drifted above 15% of capital?

Stops are not suggestions. The platform computes the size from the stop, so moving the stop
breaks the math that justified the position.

### 3. Screen, then research (8 min)
**Screener** → run `quality` and `momentum` separately. Do not average scan results; a stock
that scores well on both is a candidate, not a winner.

Pick **at most two** names. Run the research terminal on each. Read the report — genuinely:
[02-reading-a-research-report.md](02-reading-a-research-report.md).

If a name returns `INSUFFICIENT DATA`, that is the answer. Move on. It usually means the
statements or the history are too thin to judge, and thin data hides risk rather than removing
it.

### 4. Write the note (3 min)
**Journal** → new note, kind `observation`. One paragraph per name you looked at: why it
interested you, what you would need to see to act, what you would need to see to drop it.
Include the price now. You will need this in three weeks more than you need it today.

## What this loop does not do

- It does not chase a move already up 12% this week.
- It does not "average down". Averaging down is increasing position size precisely when the
  evidence has gone against you.
- It does not open a position in the last 10 minutes of a session.

## End-of-week addition

On Friday, run the **weekly review** in the Journal. Read `approved_automatically: false` next
to every proposal — the platform will not tell you what to change. That is the point: it gives
you the numbers, you make the call.
