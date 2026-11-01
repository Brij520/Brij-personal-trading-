/* Pages: Portfolio Manager, Trading Journal, Learning Centre. */

PAGES.portfolio = {
  title: 'Portfolio Manager',
  async render(view) {
    view.innerHTML = UI.pageHead('Portfolio manager',
      'Import holdings, then analyse concentration, sector exposure and portfolio risk. Nothing is auto-rebalanced.') + UI.loading();
    const holdings = (await API.holdings()).holdings;
    view.innerHTML = UI.pageHead('Portfolio manager',
      `${holdings.length} holding(s) imported`,
      `<button class="btn" id="snapshot">Take snapshot</button>`) + `
      ${UI.banner('Holdings are stored locally in <code>var/journal.sqlite3</code>, which is git-ignored. Nothing is uploaded anywhere, and no brokerage account is connected.', 'info')}
      <div class="grid g-1-2">
        ${UI.panel('Import holdings', `
          <div class="field">
            <label>Paste CSV — symbol, quantity, average price</label>
            <textarea id="csv" placeholder="RELIANCE,25,2450.50&#10;TCS,10,3800&#10;HDFCBANK,40,1600"></textarea>
          </div>
          <button class="btn primary" id="import" style="margin-top:8px;width:100%">Import</button>
          <div class="muted" style="font-size:10.5px;margin-top:8px">Sectors are resolved from the platform universe. Unknown symbols are grouped as Unknown.</div>`,
          { foot: 'Existing rows for the same symbol are replaced, not merged.' })}
        ${UI.panel('Holdings', `<div id="holdings-table">${UI.table(
          ['Symbol', 'Qty', 'Avg', 'Last', 'Value', 'P&L', 'Weight', ''],
          holdings.map((h) => [
            `<span class="sym" data-symbol="${UI.esc(h.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(h.symbol)}</span>`,
            UI.num(h.quantity, 0), UI.num(h.avg_price, 2), '—', '—', '—', '—',
            `<button class="btn small" data-del="${UI.esc(h.symbol)}">✕</button>`,
          ]), { empty: 'No holdings imported yet', tight: true })}</div>`,
          { tight: true, foot: 'Live prices come from the same registry as every other page; — means the symbol could not be priced, which is not the same as zero.' })}
      </div>
      <div id="analysis" style="margin-top:12px">${UI.loading('Analysing portfolio…')}</div>`;

    view.querySelector('#import').onclick = async () => {
      const raw = view.querySelector('#csv').value.trim();
      if (!raw) return;
      const rows = raw.split('\n').map((line) => line.split(',')).filter((c) => c.length >= 3);
      const payload = rows.map((c) => ({
        symbol: c[0].trim().toUpperCase(),
        quantity: Number(c[1]),
        avg_price: Number(c[2]),
      })).filter((r) => r.symbol && r.quantity > 0 && r.avg_price > 0);
      if (!payload.length) { UI.toast('No valid rows found', 'danger'); return; }
      try {
        await API.importHoldings(payload);
        UI.toast(`${payload.length} holding(s) imported`);
        renderRoute();
      } catch (err) { UI.toast(err.message, 'danger'); }
    };

    view.querySelectorAll('[data-del]').forEach((btn) => {
      btn.onclick = async () => {
        try { await fetch(`/api/portfolio/holdings/${btn.dataset.del}`, { method: 'DELETE' }); renderRoute(); }
        catch (err) { UI.toast(err.message, 'danger'); }
      };
    });
    view.querySelector('#snapshot').onclick = async () => {
      try { const r = await API.takeSnapshot(); UI.toast(`Snapshot stored · ₹${UI.compact(r.total_value)}`); }
      catch (err) { UI.toast(err.message, 'danger'); }
    };

    const host = view.querySelector('#analysis');
    const data = await API.portfolioAnalysis();
    const m = data.metrics || {};
    if (!m.exposure) {
      host.innerHTML = UI.banner(UI.esc(data.headline), 'info');
      return;
    }
    const exp = m.exposure;
    // Repaint the holdings table now that each holding has a live price.
    const priced = new Map((m.holdings || []).map((h) => [h.symbol, h]));
    view.querySelector('#holdings-table').innerHTML = UI.table(
      ['Symbol', 'Qty', 'Avg', 'Last', 'Value', 'P&L', 'Weight', ''],
      holdings.map((h) => {
        const p = priced.get(h.symbol) || {};
        const dash = (v) => (v === null || v === undefined ? '—' : v);
        return [
          `<span class="sym" data-symbol="${UI.esc(h.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(h.symbol)}</span>`,
          UI.num(h.quantity, 0),
          UI.num(h.avg_price, 2),
          dash(p.last_price) === '—' ? '—' : UI.num(p.last_price, 2),
          dash(p.value) === '—' ? '—' : '₹' + UI.compact(p.value),
          `<span class="${UI.cls(p.pnl)}">${dash(p.pnl) === '—' ? '—' : '₹' + UI.compact(p.pnl)}</span>`,
          dash(p.weight_pct) === '—' ? '—' : UI.num(p.weight_pct, 1) + '%',
          `<button class="btn small" data-del="${UI.esc(h.symbol)}">✕</button>`,
        ];
      }), { empty: 'No holdings imported yet', tight: true });
    const secRows = (m.sector_exposure || []).map((s) => [
      UI.esc(s.sector), '₹' + UI.compact(s.value), UI.num(s.weight_pct, 2) + '%',
      UI.bar(Math.min(100, s.weight_pct * 2), 100, s.weight_pct > 35 ? 'red' : 'green'),
    ]);
    host.innerHTML = `
      <div class="grid g4" style="margin-bottom:12px">
        ${UI.stat('Portfolio value', '₹' + UI.compact(exp.total_value), '', `${holdings.length} holdings`)}
        ${UI.stat('Unrealised P&L', '₹' + UI.compact(exp.unrealised_pnl), UI.cls(exp.unrealised_pnl), `invested ₹${UI.compact(exp.invested)}`)}
        ${UI.stat('Volatility (ann.)', UI.num(m.volatility_pct, 1) + '%', '', `beta ${m.beta === null ? 'n/a' : UI.num(m.beta, 2)}`)}
        ${UI.stat('1-day 95% VaR', UI.num(m.value_at_risk?.var_pct, 2) + '%', 'down', `CVaR ${UI.num(m.value_at_risk?.cvar_pct, 2)}%`)}
      </div>
      ${exp.breaches && exp.breaches.length ? UI.banner('<strong>Limit breaches:</strong> ' + exp.breaches.map(UI.esc).join(' · '), 'danger') : ''}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Holdings detail', UI.table(['Symbol', 'Weight', 'P&L', 'P&L %', 'Sector'],
          (m.holdings || []).map((h) => [
            `<span class="sym" data-symbol="${UI.esc(h.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(h.symbol)}</span>`,
            UI.num(h.weight_pct, 2) + '%',
            `<span class="${UI.cls(h.pnl)}">₹${UI.compact(h.pnl)}</span>`,
            `<span class="${UI.cls(h.pnl_pct)}">${UI.pct(h.pnl_pct)}</span>`,
            `<span class="name">${UI.esc(h.sector)}</span>`,
          ]), { tight: true }))}
        ${UI.panel('Sector exposure', UI.table(['Sector', 'Value', 'Weight', ''], secRows, { tight: true }),
          { foot: `Max single stock ${m.limits?.max_single_stock_pct}% · max sector ${m.limits?.max_sector_pct}%` })}
      </div>
      ${m.rebalance_simulation?.available ? UI.panel('Rebalancing simulation (equal weight, not executed)', UI.table(
        ['Symbol', 'Current', 'Target', 'Delta value', 'Delta qty'],
        m.rebalance_simulation.moves.map((r) => [
          UI.esc(r.symbol), UI.num(r.current_pct, 2) + '%', UI.num(r.target_pct, 2) + '%',
          `<span class="${UI.cls(r.delta_value)}">₹${UI.compact(r.delta_value)}</span>`, UI.num(r.delta_quantity, 2),
        ]), { tight: true, foot: UI.esc(m.rebalance_simulation.note) }), { class: 'grid', }) : ''}
      ${UI.panel('Risk observations', UI.list((data.risks || []).map(UI.esc))) }`;
    host.querySelectorAll('[data-symbol]').forEach((el) => {
      el.onclick = () => { location.hash = `#/research/${el.dataset.symbol}`; };
    });
  },
};

PAGES.journal = {
  title: 'Trading Journal',
  async render(view, params) {
    const tab = params.get('tab') || 'trades';
    const [trades, perf] = await Promise.all([API.trades(), API.journalPerformance()]);
    view.innerHTML = UI.pageHead('Trading journal',
      'Paper ledger with discipline checks. Behavioural patterns are described; strategies are never changed automatically.',
      `<button class="btn" id="new-trade">+ New paper trade</button>`) + `
      <div class="tabs">
        <button data-tab="trades" class="${tab === 'trades' ? 'active' : ''}">Trades</button>
        <button data-tab="performance" class="${tab === 'performance' ? 'active' : ''}">Performance</button>
        <button data-tab="reviews" class="${tab === 'reviews' ? 'active' : ''}">Reviews</button>
        <button data-tab="notes" class="${tab === 'notes' ? 'active' : ''}">Notes</button>
      </div>
      <div id="tab-body"></div>
      <div id="trade-form-wrap"></div>`;

    view.querySelectorAll('[data-tab]').forEach((b) => {
      b.onclick = () => { location.hash = `#/journal?tab=${b.dataset.tab}`; };
    });
    view.querySelector('#new-trade').onclick = () => showTradeForm(view);

    const body = view.querySelector('#tab-body');
    if (tab === 'trades') {
      const rows = trades.trades.map((t) => [
        UI.num(t.id, 0),
        `<span class="sym" data-symbol="${UI.esc(t.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(t.symbol)}</span>`,
        UI.chip(t.side, t.side === 'LONG' ? 'green' : 'red'),
        UI.date(t.entry_date), UI.num(t.entry_price, 2), UI.num(t.quantity, 0),
        t.stop_loss ? UI.num(t.stop_loss, 2) : '<span class="down">none</span>',
        t.target ? UI.num(t.target, 2) : '—',
        t.exit_price ? UI.num(t.exit_price, 2) : '—',
        t.pnl === null ? '—' : `<span class="${UI.cls(t.pnl)}">₹${UI.num(t.pnl, 0)}</span>`,
        t.r_multiple === null ? '—' : UI.num(t.r_multiple, 2),
        UI.chip(t.status, t.status === 'OPEN' ? 'amber' : t.status === 'CLOSED' ? 'green' : 'grey'),
        t.status === 'OPEN' ? `<button class="btn small" data-close="${t.id}">Close</button>` : '',
      ]);
      body.innerHTML = UI.panel('Paper trades', UI.table(
        ['#', 'Symbol', 'Side', 'Entry date', 'Entry', 'Qty', 'Stop', 'Target', 'Exit', 'P&L', 'R', 'Status', ''],
        rows, { empty: 'No paper trades recorded yet' }), { tight: true,
        foot: 'Every trade is PAPER mode. The ledger has no broker connection.' });
      body.querySelectorAll('[data-close]').forEach((btn) => {
        btn.onclick = () => closeTradeDialog(view, Number(btn.dataset.close));
      });
      body.querySelectorAll('[data-symbol]').forEach((el) => {
        el.onclick = () => { location.hash = `#/research/${el.dataset.symbol}`; };
      });
    } else if (tab === 'performance') {
      const s = perf.summary;
      const stratRows = perf.by_strategy.map((r) => [
        UI.esc(r.strategy), UI.num(r.trades, 0), `<span class="${UI.cls(r.pnl)}">₹${UI.num(r.pnl, 0)}</span>`,
        UI.num(r.win_rate_pct, 1) + '%', UI.chip(r.note, r.note === 'usable sample' ? 'green' : 'amber'),
      ]);
      body.innerHTML = `
        <div class="grid g4" style="margin-bottom:12px">
          ${UI.stat('Closed trades', UI.num(s.closed_trades, 0), '', `${UI.num(s.open_trades, 0)} open`)}
          ${UI.stat('Total P&L', '₹' + UI.compact(s.total_pnl), UI.cls(s.total_pnl), `win rate ${UI.num(s.win_rate_pct, 1)}%`)}
          ${UI.stat('Profit factor', UI.num(s.profit_factor, 2), '', `expectancy ₹${UI.compact(s.expectancy)}`)}
          ${UI.stat('Avg R', UI.num(s.avg_r_multiple, 2), '', `costs ₹${UI.compact(s.total_costs)}`)}
        </div>
        ${s.sample_warning ? UI.banner(UI.esc(s.sample_warning), 'info') : ''}
        <div class="grid g2" style="margin-top:12px">
          ${UI.panel('By strategy', UI.table(['Strategy', 'Trades', 'P&L', 'Win rate', 'Sample'], stratRows, { tight: true }))}
          ${UI.panel('Trade distribution', `<canvas class="chart" id="pnl-chart"></canvas>`)}
        </div>`;
      const closed = trades.trades.filter((t) => t.pnl !== null);
      Charts.bars(view.querySelector('#pnl-chart'),
        closed.slice(-14).map((t) => ({ label: `#${t.id} ${t.symbol}`, value: t.pnl })), { height: 220 });
    } else if (tab === 'reviews') {
      body.innerHTML = UI.loading('Building review…');
      const r = await API.review('weekly');
      body.innerHTML = `
        ${UI.panel(`${r.period} review — ${r.window_start} → ${r.window_end}`,
          UI.list(r.observations.map(UI.esc), 'Nothing to report'))}
        <div class="grid g2" style="margin-top:12px">
          ${UI.panel('Discipline findings', UI.table(['Check', 'Violations', 'Severity'],
            (r.mistakes.discipline_findings || []).map((f) => [
              UI.esc(f.check), UI.num(f.violations, 0),
              UI.chip(f.severity, f.severity === 'HIGH' ? 'red' : 'amber'),
            ]), { empty: 'No discipline violations recorded', tight: true }))}
          ${UI.panel('Proposals for human review', UI.list(
            (r.proposals || []).map((p) => `${UI.esc(p.proposal)} <span class="muted">(${UI.esc(p.requires)})</span>`)))}
        </div>
        ${UI.panel('Guardrails', UI.list(r.guardrails.map(UI.esc)), { class: 'grid' })}`;
    } else {
      body.innerHTML = UI.loading('Loading notes…');
      const notes = (await API.notes()).notes;
      body.innerHTML = UI.panel('Research memory', UI.list(
        notes.map((n) => `<strong>${UI.esc(n.title)}</strong> <span class="muted">${UI.esc(n.kind)} · ${UI.date(n.created_at)}</span><br><span class="muted">${UI.esc(n.body.slice(0, 240))}</span>`),
        'No notes yet')) + `
        ${UI.panel('Add note', `
          <div class="form-row">
            <div class="field"><label>Title</label><input id="note-title" /></div>
            <div class="field"><label>Kind</label>
              <select id="note-kind"><option>research</option><option>lesson</option><option>market</option></select></div>
          </div>
          <div class="field" style="margin-top:8px"><label>Body</label><textarea id="note-body"></textarea></div>
          <button class="btn primary" id="note-save" style="margin-top:8px">Save note</button>`) }`;
      view.querySelector('#note-save').onclick = async () => {
        const title = view.querySelector('#note-title').value.trim();
        const bodyText = view.querySelector('#note-body').value.trim();
        if (!title || !bodyText) { UI.toast('Title and body are required', 'danger'); return; }
        try {
          await API.addNote({ title, body: bodyText, kind: view.querySelector('#note-kind').value });
          UI.toast('Note saved'); renderRoute();
        } catch (err) { UI.toast(err.message, 'danger'); }
      };
    }
  },
};

function showTradeForm(view) {
  const host = view.querySelector('#trade-form-wrap');
  if (!host) return;
  host.innerHTML = UI.panel('New paper trade', `
    <div class="form-row">
      <div class="field"><label>Symbol</label><input id="tf-symbol" value="${UI.esc(State.symbol)}" /></div>
      <div class="field"><label>Side</label><select id="tf-side"><option>LONG</option><option>SHORT</option></select></div>
      <div class="field"><label>Entry date</label><input id="tf-date" type="date" value="${new Date().toISOString().slice(0, 10)}" /></div>
      <div class="field"><label>Entry price</label><input id="tf-entry" type="number" step="0.05" /></div>
      <div class="field"><label>Quantity</label><input id="tf-qty" type="number" /></div>
      <div class="field"><label>Stop loss</label><input id="tf-stop" type="number" step="0.05" /></div>
      <div class="field"><label>Target</label><input id="tf-target" type="number" step="0.05" /></div>
      <div class="field"><label>Strategy</label><input id="tf-strategy" placeholder="trend_following" /></div>
    </div>
    <div class="field" style="margin-top:8px"><label>Thesis (required for discipline)</label>
      <textarea id="tf-thesis" placeholder="What is the evidence, what invalidates it, and why now?"></textarea></div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <button class="btn primary" id="tf-save">Save paper trade</button>
      <button class="btn" id="tf-cancel">Cancel</button>
    </div>`);
  host.querySelector('#tf-cancel').onclick = () => { host.innerHTML = ''; };
  host.querySelector('#tf-save').onclick = async () => {
    const payload = {
      symbol: host.querySelector('#tf-symbol').value.trim().toUpperCase(),
      side: host.querySelector('#tf-side').value,
      entry_date: host.querySelector('#tf-date').value,
      entry_price: Number(host.querySelector('#tf-entry').value),
      quantity: Number(host.querySelector('#tf-qty').value),
      stop_loss: Number(host.querySelector('#tf-stop').value) || null,
      target: Number(host.querySelector('#tf-target').value) || null,
      strategy: host.querySelector('#tf-strategy').value || null,
      thesis: host.querySelector('#tf-thesis').value || null,
    };
    try {
      await API.addTrade(payload);
      UI.toast('Paper trade recorded');
      renderRoute();
    } catch (err) { UI.toast(err.message, 'danger'); }
  };
  host.scrollIntoView({ behavior: 'smooth' });
}

function closeTradeDialog(view, id) {
  const host = view.querySelector('#trade-form-wrap');
  host.innerHTML = UI.panel(`Close paper trade #${id}`, `
    <div class="form-row">
      <div class="field"><label>Exit price</label><input id="cl-price" type="number" step="0.05" /></div>
      <div class="field"><label>Exit date</label><input id="cl-date" type="date" value="${new Date().toISOString().slice(0, 10)}" /></div>
      <div class="field"><label>Costs</label><input id="cl-costs" type="number" value="0" /></div>
    </div>
    <div class="field" style="margin-top:8px"><label>Mistakes (comma separated)</label>
      <input id="cl-mistakes" placeholder="moved stop, sized too large, no thesis" /></div>
    <div class="field" style="margin-top:8px"><label>Lessons</label><textarea id="cl-lessons"></textarea></div>
    <button class="btn primary" id="cl-save" style="margin-top:8px">Close trade</button>`);
  host.querySelector('#cl-save').onclick = async () => {
    try {
      await API.closeTrade(id, {
        exit_price: Number(host.querySelector('#cl-price').value),
        exit_date: host.querySelector('#cl-date').value,
        costs: Number(host.querySelector('#cl-costs').value) || 0,
        mistakes: host.querySelector('#cl-mistakes').value || null,
        lessons: host.querySelector('#cl-lessons').value || null,
      });
      UI.toast('Trade closed');
      renderRoute();
    } catch (err) { UI.toast(err.message, 'danger'); }
  };
  host.scrollIntoView({ behavior: 'smooth' });
}

PAGES.learning = {
  title: 'Learning Centre',
  async render(view) {
    const status = State.status || await API.status();
    view.innerHTML = UI.pageHead('Learning centre',
      'Concepts this platform models, and — just as important — the ones it does not.') + `
      <div class="grid g2">
        ${UI.panel('Modelled correctly', UI.list([
          'Position sizing by fixed fractional risk, with a hard cap per trade.',
          'Reward-to-risk validation and stop-side checks before any plan is accepted.',
          'Indian transaction costs: brokerage, STT, exchange charge, SEBI fee, stamp duty, GST, plus explicit slippage.',
          'DCF with an explicit fade, a sensitivity grid and a terminal-value share warning.',
          'Justified P/B for lenders instead of an FCFF DCF, which would be structurally wrong.',
          'Historical-simulation VaR and CVaR, portfolio volatility from a covariance matrix.',
          'Walk-forward folds and an out-of-sample split for every strategy.',
          'Fact/opinion separation in news scoring: opinions never score sentiment.',
        ]))}
        ${UI.panel('Not modelled (stated, not hidden)', UI.list([
          'India VIX, FII/DII flows, global indices, currency, crude and bond yields.',
          'Options margins and span calculations.',
          'Corporate-action adjustment of historical prices.',
          'Survivorship bias: the universe is a fixed list of currently listed names.',
          'Intraday order book, delivery percentage, block and bulk deals.',
          'Mutual fund overlap and regulatory XBRL parsing of filings.',
          'Any live execution: this build cannot place, modify or cancel an order.',
        ]))}
      </div>
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Reading the classifications', UI.table(['Classification', 'Meaning'], [
          ['STRONG RESEARCH CANDIDATE', 'Multiple independent evidence groups agree, data quality is high.'],
          ['RESEARCH CANDIDATE', 'Positive evidence with material caveats.'],
          ['WATCHLIST', 'Mixed evidence; needs another angle or better data.'],
          ['AVOID', 'Evidence is negative, or accounting is unreliable.'],
          ['INSUFFICIENT DATA', 'The platform cannot support a conclusion. A valid answer.'],
          ['NO TRADE', 'The risk agent vetoed the plan. Not overridable.'],
        ], { tight: true }))}
        ${UI.panel('How to study with this', UI.list([
          'Start at the research terminal for one company and read the evidence lists, not the headline score.',
          'Re-run the same company after changing one DCF assumption and observe the sensitivity.',
          'Backtest a strategy on one symbol, then on five others, before believing the first result.',
          'Record every paper trade with a written thesis; the journal will flag missing stops.',
          'Read the "not modelled" list before trusting any conclusion.',
        ]))}
      </div>
      ${UI.panel('Agent catalogue', UI.table(['Agent', 'Responsibility', 'Requires'],
        status.agents.map((a) => [UI.esc(a.name), UI.esc(a.responsibility), `<span class="muted">${UI.esc(a.requires.join(', '))}</span>`]),
        { tight: true }))}`;
  },
};
