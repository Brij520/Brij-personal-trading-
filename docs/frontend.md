# Frontend

A dense, dark, keyboard-friendly research terminal. **No framework, no bundler, no CDN, no
build step, no NPM dependency.** Nine plain scripts and one stylesheet, served straight from
disk by the backend.

## Why not React

For a single-user terminal this is not asceticism, it is maintenance:

- a 10 KB change is a 10 KB diff, not a lockfile churn;
- the whole thing works with `python3 scripts/run.py` and nothing else;
- there is no supply chain to audit for a tool that reads your portfolio;
- canvas charting is direct, and a virtual DOM would only add a layer between me and the pixels.

The cost is that rendering is string-based and state is a module-level object. That cost is
paid explicitly, once, in `app.js`.

## Files

| File | Lines | Responsibility |
|---|---|---|
| `index.html` | ~54 | Shell: topbar, ticker, rail, view, statusbar. Load order matters. |
| `css/terminal.css` | ~340 | The entire design system: tokens, layout, panels, tables, chips, verdicts, print styles. |
| `js/api.js` | ~80 | One `fetch` wrapper: JSON, error extraction, latency counter. No page calls `fetch` directly. |
| `js/charts.js` | ~290 | Canvas: candlesticks + volume + EMA overlays + crosshair, line, payoff, bars. |
| `js/components.js` | ~130 | `UI.*` helpers (`esc`, `num`, `pct`, `table`, `panel`, `stat`, `kv`, `list`, `toast`, `provenance`, `qualityBadge`) and `State`. |
| `js/pages_market.js` | dashboard, market, watchlist, screener |
| `js/pages_research.js` | research, fundamentals, valuation, technical, reports |
| `js/pages_trading.js` | swing, intraday, options, backtest |
| `js/pages_journal.js` | portfolio, journal, learning |
| `js/pages_system.js` | risk, settings |
| `js/app.js` | Router, nav, global search, ticker, statusbar, boot. |

Eighteen pages, each a `PAGES.<key> = { title, async render(view, params) }`.

## Routing

Hash-based: `#/technical/RELIANCE?tf=15m`.

```
renderRoute() → parse path + symbol + query → PAGES[key].render(view, params)
```

- Unknown key falls back to the dashboard (never a blank screen).
- A symbol in the path is written to `State`, which persists to `localStorage` and fires a
  `symbol-changed` event.
- Each render replaces `view.innerHTML` and scrolls to top. There is no diffing, so a page
  must be able to build its own DOM from scratch — which also means a refresh always works.

## Components

Every value that reaches the DOM goes through `UI.esc()` unless it is intentionally HTML.
**No page builds a table by hand**; `UI.table(headers, rows, opts)` handles the empty case with
a proper `colspan` row, and headers are always escaped.

Formatting rules:

- `UI.num(v, d)` — Indian digit grouping (`en-IN`), em-dash for `null`/`NaN`.
- `UI.compact(v)` — Cr / L / K, because ₹1,24,00,00,000 is unreadable at a glance.
- `UI.pct(v)` — always signed, because a delta without a sign is a guessing game.
- **`null` renders as `—`, never as `0` or `NaN`.** This is enforced by the smoke test.

`UI.provenance(p)` renders source · exchange · freshness · verification as a chip, with the
synthetic case in amber. `UI.qualityBadge(q)` renders the data-quality score with a colour band.

## Charts

`charts.js` draws on `<canvas>` with the device pixel ratio applied, so it is crisp on retina
and costs nothing at runtime.

- `candlestick(canvas, bars, {height, tooltip})` — price pane + volume pane, EMA20/50/200
  overlays, y-axis ticks from a "nice numbers" algorithm, x labels at 6 points, crosshair
  readout via a positioned tooltip element.
- `line(canvas, series, {height, color, fill})` — used for RSI, MACD, equity curves.
- `line(..., {height: 64})` doubles as the index sparkline on the dashboard, which keeps one
  code path for all series drawing.
- `payoff(canvas, points)` — option payoff diagram with zero line and breakeven marks.
- `bars(canvas, items)` — horizontal sector-rotation bars.

Charts redraw on `resize` (debounced) and are destroyed on route change by virtue of the inner
HTML being replaced. No `requestAnimationFrame` loop is left running on a page you left.

## Visual language

| Token | Value | Use |
|---|---|---|
| `--bg` | `#080b0f` | page |
| `--panel` | `#11161d` | cards |
| `--line` | `#1e2733` | 1 px separation, everywhere |
| `--accent` | `#f0b90b` | the one accent — brand, active nav, primary action |
| `--green` / `--red` | `#16c784` / `#ea3943` | up / down, used for *nothing else* |
| `--muted` | `#6b7889` | labels, footnotes |

Deliberate choices:

- **Numbers are monospaced with tabular figures**, so a updating value does not shift the
  column beside it.
- **12 px body text, 9.5 px labels** — this is a terminal for reading tables, not a marketing
  page.
- **One accent colour.** Red and green mean direction only; if red also meant "danger button"
  the whole screen would lose meaning.
- **Motion is minimal**: a 120 ms border transition and a 700 ms spinner. No skeletons fading
  in, no parallax.
- **Print styles** strip the chrome so a research page can be printed or saved as a PDF and
  still be legible.

## Accessibility and honesty in the UI

- Semantic landmarks (`header`, `nav`, `main`, `footer`), `aria-label` on search and nav.
- Visible `:focus-visible` rings; the search and every form control are keyboard reachable.
- `Esc` closes search results; `/` focuses search from anywhere.
- Colour is never the only signal: every stance/verdict also carries its word
  (`BULLISH`, `WATCHLIST`, `NO TRADE`).
- A **synthetic-data banner** appears on any page showing synthetic prices, and the statusbar
  always shows `data mode: demo`.
- There is no "Buy" button anywhere in the app. The risk page's most prominent element is the
  list of reasons a proposal was rejected.

## Performance

The heaviest page is the research terminal: one `POST /api/research/{symbol}` (0.4–2.5 s) and
then pure DOM. Every page renders in a single pass — no waterfall of per-widget fetches. Market
data is fetched once per page and passed down.

## Testing without a browser

`scripts/check_frontend.mjs` runs all nine scripts in a `vm` context with a minimal DOM shim
(element tree, `querySelector`/`querySelectorAll`, `classList`, `localStorage`, a Proxy-based
2D context) and a `fetch` pointed at the live API. It renders all 18 pages and fails if any
page throws or emits `undefined`, `NaN` or `[object Object]`.

```bash
node scripts/check_frontend.mjs            # all pages against http://localhost:8000
VERBOSE=1 node scripts/check_frontend.mjs  # stack traces on failure
```

This is not a substitute for looking at the screen — it catches data wiring and crashes, not
layout. See `DEVELOPMENT_STATUS.md` for what remains unverified visually.
