# Skills — operating the terminal

Documentation tells you what the software does. These files tell you **what to do with it, in
what order, and what to write down.** They are written for one operator (Brij) working alone,
and they assume the platform is running at `http://localhost:8000`.

| # | Skill | Use it when |
|---|---|---|
| 01 | [The daily research loop](01-daily-research-loop.md) | Every trading day, 20 minutes, after the close. |
| 02 | [Reading a research report](02-reading-a-research-report.md) | Before acting on any classification. |
| 03 | [Position sizing](03-position-sizing.md) | Before every trade, without exception. |
| 04 | [Judging a backtest](04-judging-a-backtest.md) | Before believing any strategy. |
| 05 | [Journal discipline](05-journal-discipline.md) | Weekly, and after every loss. |
| 06 | [Options research](06-options-research.md) | Before touching any F&O idea. |
| 07 | [₹20,000 portfolio challenge](07-20000-portfolio-challenge.md) | The full research, scoring, allocation and monitoring workflow. |

## The three rules that sit above all of them

1. **The platform never tells you to buy.** A classification is a label on a research file, not
   a permission slip. The BUY decision is yours and is not modelled anywhere in the code.
2. **If you cannot state the invalidation, you do not have a trade.** "It will go up" is not an
   invalidation. A price, a level, or a fact that would make you wrong is.
3. **Write it down before you know the outcome.** The journal is worthless if entries are
   written after the result. Every skill below ends with a written artefact for this reason.

## What these skills assume

- Data is `demo` unless you have verified the NSE adapter. **Anything you learn about the
  *companies* from this terminal in demo mode is fiction.** Only the mechanics — sizing,
  costs, journal, report structure — transfer.
- Capital is set explicitly in the risk page. The default ₹10,00,000 is a placeholder.
- You have 20–40 minutes a day, not four hours. These are deliberately short.
