/* Pages: Dashboard, Market Overview, Watchlist, Screener. */

PAGES.dashboard = {
  title: 'Dashboard',
  async render(view) {
    const [overview, status] = await Promise.all([API.overview(), API.status().catch(() => State.status)]);
    State.overview = overview;
    const q = status?.safety || {};
    const synthetic = overview.is_synthetic;

    const indexCards = overview.indices.map((i) => {
      if (i.error) return UI.panel(i.name, `<div class="empty">${UI.esc(i.error)}</div>`);
      return UI.panel(
        i.name,
        `<div class="stat">
           <div class="value ${UI.cls(i.change_pct)}">${UI.num(i.last, 2)}</div>
           <div class="delta ${UI.cls(i.change_pct)}">${UI.pct(i.change_pct)} today · ${UI.pct(i.change_1m_pct)} 1M</div>
           <div class="note">50DMA ${UI.num(i.sma50, 0)} · 200DMA ${UI.num(i.sma200, 0)} · RSI ${UI.num(i.rsi14, 1)}</div>
         </div>
         <canvas class="chart" data-spark="${UI.esc(i.name)}"></canvas>`,
        { tight: false }
      );
    }).join('');

    view.innerHTML = `
      ${UI.pageHead(
        'Market dashboard',
        `${overview.regime.replace('_', ' ')} regime · breadth ${UI.num(overview.breadth.advance_decline_ratio, 2)} · ${overview.breadth.universe_size} instruments tracked`,
        `<button class="btn" id="refresh">Refresh</button>
         <a class="btn primary" href="#/research/${encodeURIComponent(State.symbol)}">Research ${UI.esc(State.symbol)}</a>`
      )}
      ${synthetic ? UI.banner(
        `<strong>Synthetic demonstration data.</strong> Every price, statement and agent finding on this
         terminal is generated deterministically for demonstration. It does not describe real companies and
         must not be used for investment decisions.`, 'danger') : ''}
      <div class="grid g4" style="margin-bottom:12px">${indexCards}</div>
      <div class="grid g-2-1" style="margin-bottom:12px">
        ${UI.panel('Sector performance (1-day average)',
          `<canvas class="chart" id="sector-bars"></canvas>`,
          { foot: 'Computed from constituent price changes in the platform universe.' })}
        ${UI.panel('Market state', `
          ${UI.kv([
            ['Regime', `<span class="chip ${overview.regime === 'RISK_ON' ? 'green' : overview.regime === 'RISK_OFF' ? 'red' : 'amber'}">${UI.esc(overview.regime)}</span>`],
            ['Advancing', UI.num(overview.breadth.advances, 0)],
            ['Declining', UI.num(overview.breadth.declines, 0)],
            ['Unchanged', UI.num(overview.breadth.unchanged, 0)],
            ['Advance / decline', UI.num(overview.breadth.advance_decline_ratio, 2)],
            ['Realised vol (20d, proxy)', UI.num(overview.volatility_pct, 2) + '%'],
          ])}
          <div style="margin-top:10px">
          ${UI.banner(UI.esc(overview.vix_note), 'info')}
          </div>`,
          { foot: 'India VIX, FII/DII flows and global cues are not available from the configured sources.' })}
      </div>
      <div class="grid g3">
        ${UI.panel('Top gainers', '<div id="mv-gainers">' + UI.loading() + '</div>', { tight: true })}
        ${UI.panel('Top losers', '<div id="mv-losers">' + UI.loading() + '</div>', { tight: true })}
        ${UI.panel('Most active', '<div id="mv-active">' + UI.loading() + '</div>', { tight: true })}
      </div>
      ${UI.panel('Safety posture', `
        <div class="grid g4">
          ${UI.stat('RESEARCH_ONLY', q.research_only ? 'TRUE' : 'FALSE', '', 'analysis only')}
          ${UI.stat('PAPER_TRADING', q.paper_trading ? 'TRUE' : 'FALSE', '', 'journal ledger')}
          ${UI.stat('LIVE_TRADING', q.live_trading ? 'TRUE' : 'FALSE', '', 'not implemented')}
          ${UI.stat('FNO_ENABLED', q.fno_enabled ? 'TRUE' : 'FALSE', '', 'options research only')}
        </div>`, { foot: 'No order can be placed, modified or cancelled from this terminal.' })}
    `;

    // sparklines
    overview.indices.forEach((idx) => {
      if (!idx.series) return;
      const canvas = view.querySelector(`canvas[data-spark="${CSS.escape(idx.name)}"]`);
      if (canvas) Charts.line(canvas, idx.series.map((p) => ({ value: p.close })), { height: 64 });
    });
    const sectorCanvas = view.querySelector('#sector-bars');
    Charts.bars(sectorCanvas, overview.sectors.slice(0, 10).map((s) => ({ label: s.sector, value: s.avg_change_pct })), { height: 240 });

    // movers tables
    const build = (rows) => UI.table(
      ['Sym', 'Name', 'Last', 'Chg', 'Vol'],
      rows.map((r) => [
        `<span class="sym" data-symbol="${UI.esc(r.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(r.symbol)}</span>`,
        `<span class="name">${UI.esc(r.name)}</span>`,
        UI.num(r.last, 2),
        `<span class="${UI.cls(r.change_pct)}">${UI.pct(r.change_pct)}</span>`,
        UI.compact(r.volume),
      ])
    );
    view.querySelector('#mv-gainers').innerHTML = build(overview.movers.gainers);
    view.querySelector('#mv-losers').innerHTML = build(overview.movers.losers);
    view.querySelector('#mv-active').innerHTML = build(overview.movers.active);

    view.querySelectorAll('[data-symbol]').forEach((el) => {
      el.onclick = () => {
        State.setSymbol(el.dataset.symbol);
        location.hash = `#/research/${el.dataset.symbol}`;
      };
    });
    view.querySelector('#refresh').onclick = () => renderRoute();
  },
};

PAGES.market = {
  title: 'Market Overview',
  async render(view) {
    const overview = await API.overview();
    view.innerHTML = `
      ${UI.pageHead('Market overview',
        'Indices, breadth, sector rotation and the gaps in what this platform can currently verify.',
        `<button class="btn" onclick="renderRoute()">Refresh</button>`)}
      ${overview.is_synthetic ? UI.banner('<strong>Synthetic data.</strong> Index levels are equal-weighted composites of synthetic constituents, not official index values.', 'danger') : ''}
      ${UI.panel('Indices', UI.table(
        ['Index', 'Last', 'Day', '1W', '1M', '1Y', '50DMA', '200DMA', 'RSI', 'Vol 20d'],
        overview.indices.filter((i) => !i.error).map((i) => [
          UI.esc(i.name),
          UI.num(i.last, 2),
          `<span class="${UI.cls(i.change_pct)}">${UI.pct(i.change_pct)}</span>`,
          `<span class="${UI.cls(i.change_1w_pct)}">${UI.pct(i.change_1w_pct)}</span>`,
          `<span class="${UI.cls(i.change_1m_pct)}">${UI.pct(i.change_1m_pct)}</span>`,
          `<span class="${UI.cls(i.change_1y_pct)}">${UI.pct(i.change_1y_pct)}</span>`,
          UI.num(i.sma50, 0), UI.num(i.sma200, 0), UI.num(i.rsi14, 1), UI.num(i.volatility_pct, 2) + '%',
        ])), { tight: true, foot: 'Delayed or synthetic data. Not a live tick feed.' })}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Sector rotation (1-day)', `<canvas class="chart" id="sec2"></canvas>`)}
        ${UI.panel('Sector detail', UI.table(['Sector', 'Avg chg', 'Advancing', 'N'],
          overview.sectors.map((s) => [
            UI.esc(s.sector),
            `<span class="${UI.cls(s.avg_change_pct)}">${UI.pct(s.avg_change_pct)}</span>`,
            UI.num(s.advancing_pct, 0) + '%', UI.num(s.constituents, 0),
          ])), { tight: true })}
      </div>
      ${UI.panel('Not available in this build', UI.list(overview.unavailable.map(UI.esc)),
        { foot: 'These are reported as missing rather than estimated.' })}
    `;
    Charts.bars(view.querySelector('#sec2'), overview.sectors.slice(0, 12).map((s) => ({ label: s.sector, value: s.avg_change_pct })), { height: 300 });
  },
};

PAGES.watchlist = {
  title: 'Watchlist',
  async render(view) {
    const symbols = JSON.parse(localStorage.getItem('bti.watchlist') || '["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK"]');
    view.innerHTML = `
      ${UI.pageHead('Watchlist', 'Personal list. Quotes refresh on demand; nothing here is a recommendation.',
        `<input id="add-sym" class="btn" style="width:120px;font-family:var(--mono)" placeholder="ADD SYMBOL" />
         <button class="btn" id="add-btn">Add</button>`)}
      <div id="wl-body">${UI.loading('Fetching quotes…')}</div>`;
    const body = view.querySelector('#wl-body');
    const quotes = await Promise.all(symbols.map(async (s) => {
      try {
        const [q, f] = await Promise.all([API.quote(s), API.fundamentals(s).catch(() => null)]);
        return { q, f };
      } catch (e) { return { symbol: s, error: e.message }; }
    }));
    body.innerHTML = UI.panel('Quotes', UI.table(
      ['Sym', 'Name', 'Last', 'Chg %', '52W H', '52W L', 'Fund. score', 'Quality', ''],
      quotes.map((row) => {
        if (row.error) return [`<span class="sym">${UI.esc(row.symbol)}</span>`, `<span class="down">${UI.esc(row.error)}</span>`, '', '', '', '', '', '', ''];
        const a = row.f?.analysis;
        return [
          `<span class="sym" data-symbol="${UI.esc(row.q.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(row.q.symbol)}</span>`,
          `<span class="name">${UI.esc(row.f?.company_name || '')}</span>`,
          UI.num(row.q.last_price, 2),
          `<span class="${UI.cls(row.q.change_pct)}">${UI.pct(row.q.change_pct)}</span>`,
          UI.num(row.q.week52_high, 2), UI.num(row.q.week52_low, 2),
          a ? UI.bar(a.quality_score, 100, a.quality_score >= 65 ? 'green' : a.quality_score >= 45 ? '' : 'red') : '—',
          a ? UI.chip(a.quality_band, a.quality_band === 'STRONG' ? 'green' : a.quality_band === 'GOOD' ? 'blue' : a.quality_band === 'AVERAGE' ? 'amber' : 'red') : '—',
          `<button class="btn small" data-remove="${UI.esc(row.q.symbol)}">✕</button>`,
        ];
      }), { tight: true }), { foot: 'Click a symbol to open its research terminal.' });

    body.querySelectorAll('[data-symbol]').forEach((el) => {
      el.onclick = () => { State.setSymbol(el.dataset.symbol); location.hash = `#/research/${el.dataset.symbol}`; };
    });
    body.querySelectorAll('[data-remove]').forEach((el) => {
      el.onclick = () => {
        const next = symbols.filter((s) => s !== el.dataset.remove);
        localStorage.setItem('bti.watchlist', JSON.stringify(next));
        renderRoute();
      };
    });
    view.querySelector('#add-btn').onclick = () => {
      const input = view.querySelector('#add-sym');
      const sym = input.value.trim().toUpperCase();
      if (!sym) return;
      if (!symbols.includes(sym)) symbols.push(sym);
      localStorage.setItem('bti.watchlist', JSON.stringify(symbols));
      renderRoute();
    };
  },
};

PAGES.screener = {
  title: 'Stock Screener',
  async render(view) {
    const defs = (await API.screenerDefs()).definitions;
    const universe = await API.universe();
    const quick = ['quality', 'high_roce', 'breakout', 'momentum'];
    view.innerHTML = `
      ${UI.pageHead('Stock screener',
        'Every condition used is printed with the results. Output is a research candidate list, never a buy list.')}
      <div class="grid g-1-2">
        ${UI.panel('Scans', `
          <div id="scans" style="display:flex;flex-direction:column;gap:6px;max-height:420px;overflow:auto">
            ${defs.map((d) => `
              <label style="display:flex;gap:8px;align-items:flex-start;font-size:11.5px;cursor:pointer">
                <input type="checkbox" value="${d.key}" ${quick.includes(d.key) ? 'checked' : ''} style="margin-top:2px" />
                <span><strong>${UI.esc(d.name)}</strong><br><span class="muted">${UI.esc(d.description)}</span></span>
              </label>`).join('')}
          </div>
          <div class="field" style="margin-top:10px">
            <label>Sector filter</label>
            <select id="sector"><option value="">All sectors</option>
              ${universe.sectors.map((s) => `<option>${UI.esc(s)}</option>`).join('')}</select>
          </div>
          <button class="btn primary" id="run" style="margin-top:10px;width:100%">Run screen</button>`,
          { foot: 'Narrow scans return few rows on purpose.' })}
        ${UI.panel('Results', `<div id="screen-out">${UI.loading('Running default screen…')}</div>`, { tight: true })}
      </div>`;

    const run = async () => {
      const scans = [...view.querySelectorAll('#scans input:checked')].map((i) => i.value);
      const sector = view.querySelector('#sector').value || null;
      const out = view.querySelector('#screen-out');
      out.innerHTML = UI.loading('Scanning universe…');
      try {
        const data = await API.screener(scans.length ? scans : ['quality'], sector, 40);
        const headers = ['Sym', 'Name', 'Sector'];
        if (data.needs_fundamental) headers.push('Score', 'ROE', 'ROCE', 'D/E', 'CFO/PAT');
        if (data.needs_technical) headers.push('RSI', '3M', 'RS', 'Vol×');
        headers.push('Matched');
        const rows = data.results.map((r) => {
          const cells = [
            `<span class="sym" data-symbol="${UI.esc(r.symbol)}" style="color:var(--accent);cursor:pointer">${UI.esc(r.symbol)}</span>`,
            `<span class="name">${UI.esc(r.name)}</span>`,
            `<span class="name">${UI.esc(r.sector)}</span>`,
          ];
          if (data.needs_fundamental) cells.push(
            UI.num(r.quality_score, 0), UI.num(r.roe_pct, 1) + '%', UI.num(r.roce_pct, 1) + '%',
            UI.num(r.debt_to_equity, 2), UI.num(r.cfo_to_pat, 2));
          if (data.needs_technical) cells.push(
            UI.num(r.rsi14, 1), UI.pct(r.return_3m_pct), UI.num(r.relative_strength_3m_pp, 1),
            UI.num(r.volume_ratio, 2));
          cells.push(r.matches.map((m) => UI.chip(m, 'blue')).join(' '));
          return cells;
        });
        out.innerHTML = `
          <div class="panel-head" style="border-bottom:1px solid var(--line)">
            <h3>${data.result_count} match(es) from ${data.universe} instruments</h3>
          </div>
          <div class="panel-body" style="padding-bottom:0">
            ${UI.list(data.conditions.map(UI.esc))}
          </div>
          ${UI.table(headers, rows, { tight: false })}
          <div class="panel-foot">${UI.esc(data.disclaimer)}</div>`;
        out.querySelectorAll('[data-symbol]').forEach((el) => {
          el.onclick = () => { location.hash = `#/research/${el.dataset.symbol}`; };
        });
      } catch (err) { out.innerHTML = UI.errorBox(err.message); }
    };
    view.querySelector('#run').onclick = run;
    run();
  },
};
