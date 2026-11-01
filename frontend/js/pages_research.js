/* Pages: AI Research Terminal, Fundamentals, Valuation, Technical, Reports. */

const VERDICT_TONE = {
  'STRONG RESEARCH CANDIDATE': 'strong',
  'RESEARCH CANDIDATE': 'candidate',
  'WATCHLIST': 'watchlist',
  'AVOID': 'avoid',
  'INSUFFICIENT DATA': 'insufficient',
  'NO TRADE': 'no-trade',
};

PAGES.research = {
  title: 'AI Research Terminal',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = `
      ${UI.pageHead(`AI research terminal — ${UI.esc(symbol)}`,
        'Fourteen specialist agents, one committee classification. Every claim carries its source.',
        `<button class="btn" id="rerun">Re-run pipeline</button>
         <a class="btn" href="#/fundamentals/${UI.esc(symbol)}">Fundamentals</a>
         <a class="btn" href="#/technical/${UI.esc(symbol)}">Technical</a>
         <a class="btn" href="#/valuation/${UI.esc(symbol)}">Valuation</a>`)}
      <div id="research-body">${UI.loading('Running agents: market, fundamentals, valuation, technical, forensics, news, options, swing, intraday, bull, bear, risk, portfolio, committee…')}</div>`;
    view.querySelector('#rerun').onclick = () => renderRoute();

    let report;
    try {
      report = await API.research(symbol);
    } catch (err) {
      view.querySelector('#research-body').innerHTML = UI.errorBox(err.message);
      return;
    }
    const body = view.querySelector('#research-body');
    const b = report.bundle;
    const committee = report.findings.research_committee || {};
    const cm = committee.metrics || {};
    const thesis = cm.thesis || {};
    const synthetic = b.is_synthetic;

    const agentRows = Object.entries(report.findings)
      .filter(([k]) => k !== 'research_committee')
      .map(([name, f]) => `
        <div class="agent-row">
          <span class="an">${UI.esc(name)}</span>
          ${UI.stanceChip(f.stance)}
          <span class="ah" title="${UI.esc(f.headline)}">${UI.esc(f.headline)}</span>
        </div>`).join('');

    body.innerHTML = `
      ${synthetic ? UI.banner('<strong>Synthetic demonstration data.</strong> The classification below demonstrates the method; it says nothing about the real company.', 'danger') : ''}
      <div class="grid g-1-2" style="margin-bottom:12px">
        <div class="verdict ${VERDICT_TONE[report.classification] || ''}">
          <div class="v-class">${UI.esc(report.classification)}</div>
          <div class="v-reason">${UI.esc(cm.rationale || '')}</div>
          <div style="margin-top:12px">${UI.kv([
            ['Composite score', UI.num(cm.composite_score, 1)],
            ['Evidence groups', UI.esc(cm.corroboration?.groups || 'n/a')],
            ['Risk veto', cm.risk_veto ? '<span class="up">none</span>' : '<span class="up">no veto</span>'],
            ['Forensic flags', `${cm.critical_forensic_flags || 0} high severity`],
            ['Valuation upside', cm.valuation_upside_pct === null ? 'n/a' : UI.pct(cm.valuation_upside_pct)],
            ['Run time', `${report.duration_ms} ms`],
          ])}</div>
          <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
            ${UI.qualityBadge(b.data_quality)}
            ${UI.chip(b.sector, 'blue')}${UI.chip(b.industry, 'grey')}
          </div>
        </div>
        ${UI.panel('Agent panel', agentRows, { foot: `${Object.keys(report.findings).length} agents reported · agreement is not independent evidence.` })}
      </div>

      <div class="grid g2" style="margin-bottom:12px">
        ${UI.panel('Investment thesis', `
          <p style="margin-top:0">${UI.esc(thesis.one_line || '')}</p>
          ${UI.kv([
            ['Fundamental view', UI.esc(thesis.fundamental_view || '')],
            ['Technical view', UI.esc(thesis.technical_view || '')],
            ['Valuation view', UI.esc(thesis.valuation_view || '')],
          ])}
          <h4 style="margin:14px 0 6px;font-size:11px;letter-spacing:.08em;color:var(--muted);text-transform:uppercase">Thesis invalidation</h4>
          ${UI.list((cm.thesis_invalidation || []).map(UI.esc))}`)}
        ${UI.panel('Bull vs bear', `
          <h4 style="margin:0 0 6px;font-size:11px;letter-spacing:.08em;color:var(--up);text-transform:uppercase">Bull</h4>
          <p style="margin:0 0 10px;font-size:12px;color:var(--text-dim)">${UI.esc(cm.bull_case || 'not constructed')}</p>
          <h4 style="margin:0 0 6px;font-size:11px;letter-spacing:.08em;color:var(--red);text-transform:uppercase">Bear</h4>
          <p style="margin:0;font-size:12px;color:var(--text-dim)">${UI.esc(cm.bear_case || 'not constructed')}</p>
          <div style="margin-top:10px">${UI.list((cm.bull_concessions || []).map((c) => 'Conceded: ' + UI.esc(c)))}</div>`)}
      </div>

      ${UI.panel('Evidence by agent', Object.entries(report.findings)
        .filter(([k, f]) => k !== 'research_committee' && (f.evidence || []).length)
        .map(([name, f]) => `
          <details style="border-bottom:1px solid var(--line);padding:8px 0">
            <summary style="cursor:pointer;font-size:12px">
              <span class="num" style="color:var(--accent)">${UI.esc(name)}</span>
              <span class="muted"> — ${f.evidence.length} evidence item(s), confidence ${UI.num(f.confidence * 100, 0)}%</span>
            </summary>
            <ul class="list" style="margin-top:8px">
              ${f.evidence.map((e) => `<li><span class="li-dot">·</span><span>${UI.esc(e.claim)}
                <span class="muted" style="font-size:10.5px">[${UI.esc(e.source)}${e.as_of ? ' · ' + UI.esc(String(e.as_of).slice(0, 10)) : ''}${e.freshness ? ' · ' + UI.esc(e.freshness) : ''}]</span>
              </span></li>`).join('')}
            </ul>
            ${f.limitations && f.limitations.length ? `<div class="muted" style="font-size:10.5px;margin-top:6px">Limitations: ${f.limitations.map(UI.esc).join('; ')}</div>` : ''}
          </details>`).join(''), { foot: 'Each item states its source, date and freshness class.' })}

      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Export', `
          <div class="grid g4">
            ${['markdown', 'html', 'pdf', 'csv', 'xlsx', 'json'].map((f) =>
              `<a class="btn" href="/api/research/${UI.esc(symbol)}/report?format=${f}" target="_blank">${f.toUpperCase()}</a>`).join('')}
          </div>`, { foot: 'Reports are generated on request and written to var/reports/.' })}
        ${UI.panel('Data limitations', UI.list((committee.limitations || []).map(UI.esc)))}
      </div>
      <div style="margin-top:12px">${UI.banner(UI.esc(report.disclaimer), 'info')}</div>`;

    // provenance chips
    const prov = b.provenance || {};
    body.insertAdjacentHTML('beforeend',
      `<div style="margin-top:8px">${UI.provenance({ ...prov, source: prov.source, freshness: prov.freshness, verification: prov.verification })}</div>`);
  },
};

PAGES.fundamentals = {
  title: 'Fundamental Analysis',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Fundamental analysis — ${UI.esc(symbol)}`, 'Reported statements only; every ratio computed from the filed numbers.') + UI.loading();
    const data = await API.fundamentals(symbol);
    const a = data.analysis;
    const L = a.latest_ratios;
    const ratioRows = a.history.map((r) => [
      UI.esc(r.fiscal_year), UI.num(r.revenue_cr, 0), UI.pct(r.revenue_growth_pct),
      UI.num(r.ebitda_margin_pct, 1) + '%', UI.num(r.net_margin_pct, 1) + '%',
      UI.num(r.roe_pct, 1) + '%', UI.num(r.roce_pct, 1) + '%', UI.num(r.debt_to_equity, 2),
      UI.num(r.interest_coverage, 2), UI.num(r.cfo_to_pat, 2), UI.num(r.fcf_cr, 0),
    ]);
    view.innerHTML = UI.pageHead(`Fundamental analysis — ${UI.esc(symbol)}`,
      `${UI.esc(data.company_name)} · ${UI.esc(data.sector)} / ${UI.esc(data.industry)} · market cap ₹${UI.compact(data.market_cap_cr)} Cr`,
      `<a class="btn" href="#/valuation/${UI.esc(symbol)}">Valuation</a>
       <a class="btn" href="#/research/${UI.esc(symbol)}">Full research</a>`) + `
      ${UI.banner(UI.esc(data.provenance.note || ''), 'info')}
      <div class="grid g4" style="margin:12px 0">
        ${UI.stat('Quality score', `${a.quality_score}<span class="muted" style="font-size:12px">/100</span>`, '', a.quality_band)}
        ${UI.stat('Revenue CAGR (3y)', UI.pct(a.revenue_cagr_3y_pct), '', `5y ${UI.pct(a.revenue_cagr_5y_pct)}`)}
        ${UI.stat('ROE', UI.num(L.roe_pct, 1) + '%', '', `ROCE ${UI.num(L.roce_pct, 1)}%`)}
        ${UI.stat('CFO / PAT', UI.num(L.cfo_to_pat, 2), '', `FCF ₹${UI.compact(L.fcf_cr)} Cr`)}
      </div>
      <div class="grid g-2-1">
        ${UI.panel('Five-year ratio history', UI.table(
          ['FY', 'Revenue', 'Growth', 'EBITDA', 'Net mgn', 'ROE', 'ROCE', 'D/E', 'Int cov', 'CFO/PAT', 'FCF'],
          ratioRows), { tight: true, foot: 'All monetary values in INR crore.' })}
        <div class="grid" style="gap:12px">
          ${UI.panel('Score build', `
            ${UI.bar(a.quality_score, 100, a.quality_score >= 65 ? 'green' : a.quality_score >= 45 ? '' : 'red')}
            <div style="margin-top:10px">
              <div class="muted" style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px">Strengths</div>
              ${UI.list(a.strengths.map(UI.esc), 'None identified')}
              <div class="muted" style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;margin:10px 0 4px">Concerns</div>
              ${UI.list(a.concerns.map(UI.esc), 'None identified')}
            </div>`)}
          ${UI.panel('Cash conversion', `<canvas class="chart" id="cfo-chart"></canvas>`)}
        </div>
      </div>
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Quarterly results', UI.table(['Period', 'Revenue', 'EBITDA', 'PAT', 'EPS'],
          data.quarterly.map((q) => [UI.esc(q.period), UI.num(q.revenue_cr, 0), UI.num(q.ebitda_cr, 0), UI.num(q.pat_cr, 0), UI.num(q.eps, 2)]), { tight: true }))}
        ${UI.panel('Shareholding & governance', `
          ${UI.kv([
            ['Promoter', UI.num(data.shareholding.promoter_pct, 2) + '%'],
            ['Promoter pledge', UI.num(data.shareholding.promoter_pledge_pct, 2) + '%'],
            ['FII', UI.num(data.shareholding.fii_pct, 2) + '%'],
            ['DII', UI.num(data.shareholding.dii_pct, 2) + '%'],
            ['Public / others', UI.num(data.shareholding.retail_pct, 2) + '%'],
          ])}
          <div style="margin-top:10px">${UI.list(data.red_flag_notes.map(UI.esc), 'No red flags in the disclosure inputs')}</div>`,
          { foot: 'Shareholding is a point-in-time snapshot; quarter-on-quarter changes need the filings feed.' })}
      </div>
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Annual revenue & margin', `<canvas class="chart" id="rev-chart"></canvas>`)}
        ${UI.panel('Data limitations', UI.list((a.insufficient_data || []).concat([
          'Segment results, order book and management guidance are not ingested.',
          'Notes to accounts and related-party schedules are not parsed.',
        ]).map(UI.esc)))}
      </div>`;

    Charts.line(view.querySelector('#cfo-chart'),
      a.history.map((r) => ({ value: r.cfo_to_pat || 0 })), { height: 120 });
    Charts.line(view.querySelector('#rev-chart'),
      a.history.map((r) => ({ value: r.revenue_cr })), { height: 180 });
  },
};

PAGES.valuation = {
  title: 'Valuation',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Valuation — ${UI.esc(symbol)}`, '') + UI.loading('Running valuation models…');
    const f = await API.valuation(symbol);
    const m = f.metrics || {};
    const dcf = m.dcf;
    const bank = m.bank_valuation;
    const scenarios = m.scenarios || [];
    const multiples = m.multiples || [];

    const scenarioTable = scenarios.length ? `
      ${UI.table(['Scenario', 'Growth', 'Margin', 'WACC', 'Terminal g', 'Value/share', 'Note'],
        scenarios.map((s) => [
          `<strong>${UI.esc(s.name)}</strong>`,
          UI.num(s.growth * 100, 1) + '%',
          UI.num(s.margin * 100, 1) + '%',
          UI.num(s.wacc * 100, 1) + '%',
          UI.num(s.terminal_growth * 100, 1) + '%',
          UI.num(s.value_per_share, 2),
          `<span class="name" style="white-space:normal">${UI.esc(s.note)}</span>`,
        ]), { tight: false })}
      <div style="padding:12px"><canvas class="chart" id="scenario-bars"></canvas></div>` : '';

    view.innerHTML = UI.pageHead(`Valuation — ${UI.esc(symbol)}`,
      UI.esc(f.headline), `<a class="btn" href="#/fundamentals/${UI.esc(symbol)}">Fundamentals</a>
      <a class="btn" href="#/research/${UI.esc(symbol)}">Full research</a>`) + `
      ${UI.banner('Valuation is a model output built from stated assumptions. It is not a price target and not a forecast.', 'info')}
      <div class="grid g4" style="margin:12px 0">
        ${UI.stat('Model anchor', m.methods_used?.[0] === 'justified_pb'
          ? UI.num(bank?.fair_value_per_share, 2) : UI.num(dcf?.value_per_share, 2), '', 'INR per share')}
        ${UI.stat('Current price', UI.num(m.price, 2), '', 'INR per share')}
        ${UI.stat('Implied upside', UI.pct(m.upside_pct), '', 'model vs market')}
        ${UI.stat('Stance', UI.stanceChip(f.stance), '', `confidence ${UI.num(f.confidence * 100, 0)}%`)}
      </div>
      <div class="grid g2" style="margin-bottom:12px">
        ${UI.panel('Scenarios', scenarioTable || '<div class="empty">This company is valued with a sector-specific model; no DCF scenario grid applies.</div>')}
        ${UI.panel(bank ? 'Justified P/B (lender framework)' : 'DCF assumptions', bank ? `
          ${UI.kv([
            ['Justified P/B', UI.num(bank.justified_pb, 2)],
            ['Traded P/B', UI.num(bank.price_to_book, 2)],
            ['ROE assumed', (bank.assumptions.roe * 100).toFixed(1) + '%'],
            ['Cost of equity', (bank.assumptions.cost_of_equity * 100).toFixed(1) + '%'],
            ['Sustainable growth', (bank.assumptions.sustainable_growth * 100).toFixed(1) + '%'],
            ['DMV value', bank.ddm_value ? UI.num(bank.ddm_value, 2) : 'n/a'],
          ])}
          <div style="margin-top:10px">${UI.list(bank.notes.map(UI.esc))}</div>`
          : dcf ? `
          ${UI.kv(Object.entries(dcf.assumptions).map(([k, v]) => [
            k.replace(/_/g, ' '),
            typeof v === 'number' ? (v < 2 && v > -2 && k.includes('pct') ? UI.num(v * 100, 1) + '%'
              : UI.num(v, k === 'wacc' || k === 'terminal_growth' ? 3 : 2)) : String(v)]))}
          <div style="margin-top:10px">
            ${UI.banner(`Terminal value is <strong>${UI.num((dcf.terminal_share_of_value || 0) * 100, 0)}%</strong> of enterprise value.` +
              ((dcf.terminal_share_of_value || 0) > 0.75 ? ' The conclusion is dominated by the terminal assumption.' : ''), 'info')}
            ${UI.list((dcf.warnings || []).map(UI.esc), 'No model warnings')}
          </div>` : 'Not computable')}
      </div>
      ${dcf ? UI.panel('DCF forecast', UI.table(
        ['Year', 'Revenue', 'Growth', 'EBIT', 'NOPAT', 'FCFF', 'DF', 'PV'],
        dcf.forecast.map((r) => [r.year, UI.num(r.revenue, 0), UI.num(r.growth_pct, 1) + '%',
          UI.num(r.ebit, 0), UI.num(r.nopat, 0), UI.num(r.fcff, 0), UI.num(r.discount_factor, 3), UI.num(r.pv_fcff, 0)]),
        { tight: true }), { class: 'grid' }) : ''}
      ${dcf ? UI.panel('Sensitivity: WACC (rows) × terminal growth (columns)', UI.table(
        ['WACC', ...Object.keys(Object.values(dcf.sensitivity)[0] || {})],
        Object.entries(dcf.sensitivity).map(([wacc, row]) => [
          UI.esc(wacc), ...Object.values(row).map((v) => Number.isFinite(v) ? UI.num(v, 2) : 'n/a')]),
        { tight: true }), { class: 'grid', foot: 'All values are INR per share.' }) : ''}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Relative multiples', UI.table(['Metric', 'Company', 'Peer median', 'Verdict', 'Note'],
          multiples.map((r) => [UI.esc(r.metric), UI.num(r.company, 2), UI.num(r.peer_median, 2),
            UI.chip(r.verdict, r.verdict === 'CHEAP' ? 'green' : r.verdict === 'EXPENSIVE' ? 'red' : 'grey'),
            `<span class="name" style="white-space:normal">${UI.esc(r.note)}</span>`]), { tight: true }))}
        ${UI.panel('Limitations', UI.list((f.limitations || []).map(UI.esc)))}
      </div>`;

    if (scenarios.length) {
      Charts.bars(view.querySelector('#scenario-bars'),
        scenarios.map((s) => ({ label: s.name, value: s.value_per_share ? (s.value_per_share / m.price - 1) * 100 : 0 })),
        { height: 150, labelWidth: 70 });
    }
  },
};

PAGES.technical = {
  title: 'Technical Analysis',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Technical analysis — ${UI.esc(symbol)}`, '') + UI.loading('Loading price series…');
    const timeframe = params.get('tf') || '1d';
    const [chart, tech] = await Promise.all([
      API.chart(symbol, timeframe, timeframe === '1d' ? 400 : 600),
      API.technical(symbol, timeframe),
    ]);
    const ind = tech.indicators;
    view.innerHTML = UI.pageHead(`Technical analysis — ${UI.esc(symbol)}`,
      `${UI.esc(timeframe)} · ${chart.bars.length} bars · last ${UI.num(tech.price, 2)}`,
      `<button class="btn ${timeframe === '1d' ? 'primary' : ''}" data-tf="1d">Daily</button>
       <button class="btn ${timeframe === '15m' ? 'primary' : ''}" data-tf="15m">15m</button>
       <button class="btn ${timeframe === '60m' ? 'primary' : ''}" data-tf="60m">60m</button>`) + `
      ${chart.provenance.freshness === 'SYNTHETIC' ? UI.banner('<strong>Synthetic price series.</strong> Demonstrates the analytics, not real prices.', 'danger') : ''}
      ${UI.panel('Price', `
        <div style="position:relative">
          <canvas class="chart" id="price-chart"></canvas>
          <div id="chart-tooltip" class="panel" hidden style="position:absolute;pointer-events:none;padding:8px 10px;font-family:var(--mono);font-size:11px;background:#0d1117;border:1px solid var(--line-2);border-radius:3px;min-width:132px"></div>
        </div>`,
        { foot: 'EMA overlays · volume · crosshair readout. Stop-before-target assumption applies in all tests.' })}
      <div class="grid g4" style="margin:12px 0">
        ${UI.stat('RSI (14)', UI.num(ind.rsi14, 1), '',
          ind.rsi14 > 70 ? 'overbought' : ind.rsi14 < 30 ? 'oversold' : 'neutral')}
        ${UI.stat('MACD hist', UI.num(ind.macd_hist, 3), ind.macd_hist > 0 ? 'up' : 'down', `signal ${UI.num(ind.macd_signal, 2)}`)}
        ${UI.stat('ADX (14)', UI.num(ind.adx14, 1), '', ind.adx14 > 25 ? 'trending' : 'no trend')}
        ${UI.stat('ATR (14)', UI.num(ind.atr14, 2), '', `${UI.num(tech.price ? ind.atr14 / tech.price * 100 : 0, 2)}% of price`)}
      </div>
      <div class="grid g2">
        ${UI.panel('Levels', `
          ${UI.kv([
            ['Resistance', (tech.levels.resistance || []).map((v) => UI.num(v, 2)).join(' · ') || 'none'],
            ['Support', (tech.levels.support || []).map((v) => UI.num(v, 2)).join(' · ') || 'none'],
            ['Primary trend', UI.esc(tech.trend.primary)],
            ['Intermediate', UI.esc(tech.trend.intermediate)],
            ['Short term', UI.esc(tech.trend.short_term)],
            ['Divergence', UI.esc(tech.divergence.type + ' — ' + tech.divergence.detail)],
          ])}
          <div style="margin-top:10px">${UI.kv(Object.entries(tech.fibonacci).map(([k, v]) => [`Fib ${k}%`, UI.num(v, 2)]))}</div>`)}
        ${UI.panel('Indicators', UI.table(['Indicator', 'Value'], Object.entries(ind).map(([k, v]) => [UI.esc(k), UI.num(v, k === 'vol20' ? 3 : 2)]), { tight: true }), { })}
      </div>
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('RSI (120 bars)', `<canvas class="chart" id="rsi-chart"></canvas>`)}
        ${UI.panel('MACD (120 bars)', `<canvas class="chart" id="macd-chart"></canvas>`)}
      </div>`;

    view.querySelectorAll('[data-tf]').forEach((btn) => {
      btn.onclick = () => { location.hash = `#/technical/${symbol}?tf=${btn.dataset.tf}`; };
    });
    Charts.candlestick(view.querySelector('#price-chart'), chart.bars,
      { height: 380, tooltip: view.querySelector('#chart-tooltip') });
    Charts.line(view.querySelector('#rsi-chart'), tech.rsi_series.filter((r) => r.rsi != null).map((r) => ({ value: r.rsi })), { height: 130, color: '#3d8bfd' });
    Charts.line(view.querySelector('#macd-chart'), tech.macd_series.filter((r) => r.macd != null).map((r) => ({ value: r.macd })), { height: 130 });
  },
};

PAGES.reports = {
  title: 'Research Reports',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead('Research reports',
      'Generate and export the 25-section research report. Every figure carries its source and date.') + `
      <div class="grid g2">
        ${UI.panel('Generate', `
          <div class="form-row">
            <div class="field"><label>Symbol</label><input id="rep-symbol" value="${UI.esc(symbol)}" /></div>
          </div>
          <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
            ${['markdown', 'html', 'pdf', 'csv', 'xlsx', 'json'].map((f) =>
              `<a class="btn" id="exp-${f}" href="/api/research/${UI.esc(symbol)}/report?format=${f}" target="_blank">${f.toUpperCase()}</a>`).join('')}
          </div>
          <div style="margin-top:12px">${UI.banner('Exports are generated server-side into <code>var/reports/</code>. PDF and XLSX are written by dependency-free local writers.', 'info')}</div>
          <div style="margin-top:12px" id="rep-preview">${UI.loading('Building preview…')}</div>`)}
        ${UI.panel('What the report contains', UI.list([
          '1. Company overview · 2. Business model · 3. Industry analysis',
          '4. Financial performance · 5. Revenue growth · 6. Profitability',
          '7. Cash flow · 8. Balance sheet · 9. Management quality',
          '10. Corporate governance · 11. Promoter holding · 12. Institutional ownership',
          '13. Peer comparison · 14. Valuation · 15. Technical analysis',
          '16. News and sentiment · 17. Bull case · 18. Base case · 19. Bear case',
          '20. Risk factors · 21. Investment thesis · 22. Thesis invalidation',
          '23. Data limitations · 24. Source references · 25. Final classification',
        ]), { foot: 'Sections that cannot be supported by data are stated as gaps, never fabricated.' })}
      </div>`;

    try {
      const report = await API.research(symbol);
      const c = report.findings.research_committee?.metrics || {};
      view.querySelector('#rep-preview').innerHTML = `
        <div class="verdict ${VERDICT_TONE[report.classification] || ''}" style="margin-top:4px">
          <div class="v-class">${UI.esc(report.classification)}</div>
          <div class="v-reason">${UI.esc(c.thesis?.one_line || '')}</div>
          <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
            ${UI.qualityBadge(report.bundle.data_quality)}
            ${UI.chip(`${report.duration_ms} ms`, 'grey')}
            ${UI.chip(`${Object.keys(report.findings).length} agents`, 'grey')}
          </div>
        </div>`;
    } catch (err) {
      view.querySelector('#rep-preview').innerHTML = UI.errorBox(err.message);
    }
    view.querySelector('#rep-symbol').onchange = (ev) => {
      const s = ev.target.value.trim().toUpperCase();
      document.querySelectorAll('[id^="exp-"]').forEach((a) => {
        a.href = `/api/research/${s}/report?format=${a.id.replace('exp-', '')}`;
      });
      location.hash = `#/reports/${s}`;
    };
  },
};
