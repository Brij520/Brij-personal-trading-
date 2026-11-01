/* Pages: Swing Trading, Intraday Research, Options Intelligence, Backtesting Lab. */

PAGES.swing = {
  title: 'Swing Trading',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Swing research — ${UI.esc(symbol)}`,
      'Four to eight week setups. Every plan is submitted to the risk agent; none is an order.') + UI.loading('Scanning strategies…');
    const f = await API.agent('swing_trading', symbol);
    const m = f.metrics || {};
    const candidates = m.candidates || [];

    const rows = candidates.map((c) => {
      const r = c.risk_check || {};
      return [
        UI.esc(c.strategy),
        UI.num(c.entry, 2), UI.num(c.stop_loss, 2), UI.num(c.target, 2),
        UI.num(r.reward_risk, 2),
        UI.num(c.stop_in_atr, 2) + ' ATR',
        r.approved ? UI.chip('RISK APPROVED', 'green') : UI.chip('REJECTED', 'red'),
        UI.num(r.quantity, 0),
        UI.num(r.risk_pct_capital, 2) + '%',
        `<span class="name" style="white-space:normal">${UI.esc((r.reasons || []).join(' ') || (r.warnings || []).join(' '))}</span>`,
      ];
    });

    view.innerHTML = UI.pageHead(`Swing research — ${UI.esc(symbol)}`,
      UI.esc(f.headline),
      `<a class="btn" href="#/risk/${UI.esc(symbol)}">Risk calculator</a>
       <a class="btn" href="#/backtest/${UI.esc(symbol)}">Backtest this strategy</a>`) + `
      ${f.stance === 'INSUFFICIENT_DATA' ? UI.banner('No setup fired in the last five sessions. A filtered scan finding nothing is a valid result, not a failure.', 'info') : ''}
      ${UI.banner('Research output only. The platform holds no order capability, and risk approval is a controls check, not authorisation.', 'info')}
      ${UI.panel('Candidates', UI.table(
        ['Strategy', 'Entry', 'Stop', 'Target', 'R:R', 'Stop size', 'Risk check', 'Qty', 'Risk %', 'Notes'],
        rows, { empty: 'No strategy signalled in the last 5 sessions' }), { tight: true,
        foot: `Reference capital ₹${UI.compact(m.capital_assumed)}. Position sizes use platform defaults, not your account.` })}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Structure', UI.kv([
          ['Last price', UI.num(m.price, 2)],
          ['ATR (14)', UI.num(m.atr14, 2)],
          ['Support', (m.support || []).map((v) => UI.num(v, 2)).join(' · ') || 'none'],
          ['Resistance', (m.resistance || []).map((v) => UI.num(v, 2)).join(' · ') || 'none'],
          ['Approved setups', UI.num(m.approved_count, 0)],
        ]))}
        ${UI.panel('Limitations', UI.list((f.limitations || []).map(UI.esc)))}
      </div>
      ${candidates.length ? UI.panel('Setup detail', candidates.map((c) => `
        <details style="padding:6px 0;border-bottom:1px solid var(--line)">
          <summary style="cursor:pointer;font-size:12px;color:var(--accent)">${UI.esc(c.strategy)}</summary>
          <div style="margin-top:8px">${UI.kv([
            ['Entry plan', UI.esc(c.entry_note)],
            ['Invalidation', UI.esc(c.invalidation)],
            ['Regime where it works', UI.esc(c.regime)],
            ['Holding horizon', UI.esc(c.holding_period)],
            ['Risk warnings', UI.esc((c.risk_check.warnings || []).join('; ') || 'none')],
          ])}</div>
        </details>`).join('')) : ''}`;
  },
};

PAGES.intraday = {
  title: 'Intraday Research',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Intraday research — ${UI.esc(symbol)}`, 'Paper mode only.') + UI.loading('Loading 5-minute session…');
    const f = await API.agent('intraday', symbol);
    const m = f.metrics || {};
    view.innerHTML = UI.pageHead(`Intraday research — ${UI.esc(symbol)}`,
      `Session ${UI.esc(m.session || '')} · paper mode`,
      `<a class="btn" href="#/technical/${UI.esc(symbol)}?tf=15m">15m chart</a>`) + `
      ${UI.banner('<strong>Paper mode.</strong> Live intraday trading is disabled. This output describes a session structure that has already aged; it is not an entry trigger.', 'danger')}
      <div class="grid g4" style="margin:12px 0">
        ${UI.stat('Last', UI.num(m.last_price, 2), '', `open ${UI.num(m.session_open, 2)}`)}
        ${UI.stat('VWAP', UI.num(m.vwap, 2), '', m.last_price > m.vwap ? 'price above' : 'price below')}
        ${UI.stat('Opening range', `${UI.num(m.opening_range?.low, 2)}–${UI.num(m.opening_range?.high, 2)}`, '', 'first 15 minutes')}
        ${UI.stat('Position in range', UI.num(m.position_in_range_pct, 0) + '%', '', `RSI(5m) ${UI.num(m.rsi_5m, 1)}`)}
      </div>
      ${UI.panel('Session observations', UI.list((m.notes || []).map(UI.esc)))}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Risk assessment', UI.list((f.risks || []).map(UI.esc)))}
        ${UI.panel('Limitations', UI.list((f.limitations || []).map(UI.esc)))}
      </div>`;
  },
};

PAGES.options = {
  title: 'Options Intelligence',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    view.innerHTML = UI.pageHead(`Options intelligence — ${UI.esc(symbol)}`, '') + UI.loading('Loading option chain…');
    let f;
    try { f = await API.options(symbol); } catch (err) {
      view.innerHTML = UI.pageHead('Options intelligence', '') + UI.errorBox(err.message); return;
    }
    const m = f.metrics || {};
    if (!m.chain) {
      view.innerHTML = UI.pageHead(`Options intelligence — ${UI.esc(symbol)}`, '') +
        UI.banner(UI.esc(f.headline), 'info') + UI.panel('Limitations', UI.list((f.limitations || []).map(UI.esc)));
      return;
    }
    const chainRows = m.chain.map((r) => [
      UI.compact(r.call_oi), UI.compact(r.call_change_oi), UI.num(r.call_iv, 1), UI.num(r.call_ltp, 2),
      UI.num(r.call_delta, 3), UI.num(r.call_gamma, 5), UI.num(r.call_theta, 2), UI.num(r.call_vega, 2),
      `<strong style="color:var(--accent)">${UI.num(r.strike, 2)}</strong>`,
      UI.num(r.put_delta, 3), UI.num(r.put_gamma, 5), UI.num(r.put_theta, 2), UI.num(r.put_vega, 2),
      UI.num(r.put_ltp, 2), UI.num(r.put_iv, 1), UI.compact(r.put_change_oi), UI.compact(r.put_oi),
    ]);

    view.innerHTML = UI.pageHead(`Options intelligence — ${UI.esc(symbol)}`,
      `Expiry ${UI.esc(m.expiry)} · spot ${UI.num(m.spot, 2)} · lot ${m.lot_size}`,
      `<a class="btn" href="#/research/${UI.esc(symbol)}">Full research</a>`) + `
      ${UI.banner('<strong>F&amp;O ordering is disabled in this build (FNO_ENABLED = FALSE).</strong> These structures are research illustrations and cannot be executed here. Anything with a short leg carries large or unlimited tail risk.', 'danger')}
      <div class="grid g4" style="margin:12px 0">
        ${UI.stat('PCR (OI)', UI.num(m.pcr, 2), '', m.pcr > 1.2 ? 'put heavy' : m.pcr < 0.7 ? 'call heavy' : 'balanced')}
        ${UI.stat('Max pain', UI.num(m.max_pain, 0), '', `${UI.pct((m.max_pain / m.spot - 1) * 100)} vs spot`)}
        ${UI.stat('ATM IV', UI.num(m.atm_iv_pct, 1) + '%', '', `skew ${UI.num(m.iv_skew_points, 1)} pts`)}
        ${UI.stat('Expected move', '±' + UI.num(m.expected_move_points, 0), '', `${UI.num(m.expected_move_pct, 2)}% to expiry`)}
      </div>
      ${UI.panel('Option chain', UI.table(
        ['Call OI', 'ΔOI', 'IV', 'LTP', 'δ', 'γ', 'θ', 'ν', 'Strike', 'δ', 'γ', 'θ', 'ν', 'LTP', 'IV', 'ΔOI', 'Put OI'],
        chainRows), { tight: true, foot: 'Greeks per unit. Demo chains use Black-Scholes on a synthetic surface — the maths is real, the market is not.' })}
      ${UI.panel('Strategy comparison', `
        <div class="tabs" id="strat-tabs">
          ${(m.strategies || []).map((s, i) => `<button data-idx="${i}" class="${i === 0 ? 'active' : ''}">${UI.esc(s.name)}</button>`).join('')}
        </div>
        <div class="grid g-1-2">
          <div id="strat-detail"></div>
          <div><canvas class="chart" id="payoff-chart"></canvas>
            <div class="payoff-legend" style="margin-top:8px">
              <span>— payoff at expiry</span><span>--- spot</span><span style="color:var(--accent)">| breakeven</span>
            </div>
          </div>
        </div>`)}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Observations', UI.list((m.notes || []).map(UI.esc)))}
        ${UI.panel('Limitations', UI.list((f.limitations || []).map(UI.esc)))}
      </div>`;

    const detail = view.querySelector('#strat-detail');
    const drawStrategy = (idx) => {
      const s = m.strategies[idx];
      detail.innerHTML = `<p style="margin-top:0;font-size:12px;color:var(--text-dim)">${UI.esc(s.note)}</p>
        ${UI.kv([
          ['Net premium', UI.num(s.net_premium, 2)],
          ['Max profit', typeof s.max_profit === 'number' ? UI.num(s.max_profit, 2) : UI.esc(s.max_profit)],
          ['Max loss', typeof s.max_loss === 'number' ? UI.num(s.max_loss, 2) : UI.esc(s.max_loss)],
          ['Breakevens', (s.breakevens || []).map((b) => UI.num(b, 2)).join(' · ') || 'n/a'],
          ['Lot size', s.lot_size],
        ])}
        <div style="margin-top:8px">${UI.list(s.legs.map((l) => `${l.action} ${l.quantity} × ${UI.num(l.strike, 0)} ${l.kind} @ ${UI.num(l.premium, 2)}`))}</div>`;
      Charts.payoff(view.querySelector('#payoff-chart'), s.payoff_curve,
        { height: 260, spot: m.spot, breakevens: s.breakevens });
    };
    view.querySelectorAll('#strat-tabs button').forEach((btn) => {
      btn.onclick = () => {
        view.querySelectorAll('#strat-tabs button').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        drawStrategy(Number(btn.dataset.idx));
      };
    });
    drawStrategy(0);
  },
};

PAGES.backtest = {
  title: 'Backtesting Lab',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    const [strategies, universe] = await Promise.all([API.strategies(), API.universe()]);
    view.innerHTML = UI.pageHead('Backtesting lab',
      'Event-driven simulation with Indian cost structure, explicit slippage and an out-of-sample check.',
      '') + `
      ${UI.banner('A strategy is not profitable because a backtest says so. Costs, slippage, regime dependence and out-of-sample degradation are all reported below.', 'info')}
      <div class="grid g-1-2">
        ${UI.panel('Configuration', `
          <div class="form-row">
            <div class="field"><label>Symbol</label>
              <select id="bt-symbol">${universe.instruments.map((i) =>
                `<option ${i.symbol === symbol ? 'selected' : ''}>${i.symbol}</option>`).join('')}</select></div>
            <div class="field"><label>Strategy</label>
              <select id="bt-strategy">${strategies.strategies.map((s) =>
                `<option value="${s.key}">${UI.esc(s.name)}</option>`).join('')}</select></div>
            <div class="field"><label>Lookback (bars)</label><input id="bt-lookback" type="number" value="1500" min="300" max="3000" /></div>
            <div class="field"><label>Capital</label><input id="bt-capital" type="number" value="1000000" /></div>
            <div class="field"><label>Risk / trade %</label><input id="bt-risk" type="number" value="1" step="0.1" /></div>
            <div class="field"><label>Slippage (bps)</label><input id="bt-slip" type="number" value="5" /></div>
          </div>
          <button class="btn primary" id="bt-run" style="margin-top:12px;width:100%">Run backtest</button>
          <div id="bt-strategy-info" class="muted" style="margin-top:10px;font-size:11px"></div>`,
          { foot: 'Signal on bar t, fill at the open of bar t+1. Stop assumed to fill before target when both are touched.' })}
        ${UI.panel('Results', `<div id="bt-out">${UI.loading('Run a backtest to populate')}</div>`, { tight: true })}
      </div>`;

    const select = view.querySelector('#bt-strategy');
    const info = view.querySelector('#bt-strategy-info');
    const showInfo = () => {
      const s = strategies.strategies.find((x) => x.key === select.value) || strategies.strategies[0];
      if (!s) return;
      info.innerHTML = `<strong style="color:var(--text)">${UI.esc(s.family)}</strong> — ${UI.esc(s.description)}
        <br><span class="muted">Regime: ${UI.esc(s.regime)}</span>
        <br><span class="muted">Invalidation: ${UI.esc(s.invalidation)}</span>`;
    };
    select.onchange = showInfo;
    showInfo();

    view.querySelector('#bt-run').onclick = async () => {
      const out = view.querySelector('#bt-out');
      out.innerHTML = UI.loading('Simulating trades…');
      try {
        const payload = {
          symbol: view.querySelector('#bt-symbol').value,
          strategy: select.value,
          lookback: Number(view.querySelector('#bt-lookback').value),
          initial_capital: Number(view.querySelector('#bt-capital').value),
          risk_per_trade_pct: Number(view.querySelector('#bt-risk').value),
          slippage_bps: Number(view.querySelector('#bt-slip').value),
          timeframe: '1d',
        };
        const r = await API.backtest(payload);
        const met = r.metrics || {};
        const wf = r.walk_forward;
        const oos = r.out_of_sample;
        out.innerHTML = `
          <div class="panel-body" style="padding-bottom:0">
            <div class="grid g4" style="padding:0 0 12px">
              ${UI.stat('Total return', UI.pct(met.total_return_pct), UI.cls(met.total_return_pct), `CAGR ${UI.pct(met.cagr_pct)}`)}
              ${UI.stat('Max drawdown', UI.pct(met.max_drawdown_pct), 'down', `exposure ${UI.num(met.exposure_pct, 1)}%`)}
              ${UI.stat('Sharpe', UI.num(met.sharpe, 2), '', `Sortino ${UI.num(met.sortino, 2)}`)}
              ${UI.stat('Trades', UI.num(met.trades, 0), '', `win rate ${UI.num(met.win_rate_pct, 1)}%`)}
            </div>
            <div class="grid g4" style="padding:0 0 12px">
              ${UI.stat('Profit factor', UI.num(met.profit_factor, 2), '', `expectancy ₹${UI.compact(met.expectancy_per_trade)}`)}
              ${UI.stat('Avg R', UI.num(met.avg_r_multiple, 2), UI.cls(met.avg_r_multiple), 'per closed trade')}
              ${UI.stat('Costs', '₹' + UI.compact(met.total_costs), '', `${UI.num(met.cost_drag_pct_of_capital, 2)}% of capital`)}
              ${UI.stat('Final equity', '₹' + UI.compact(met.final_equity), '', `start ₹${UI.compact(payload.initial_capital)}`)}
            </div>
            <canvas class="chart" id="bt-equity"></canvas>
          </div>
          ${wf && wf.available ? `<div class="panel-body" style="border-top:1px solid var(--line)">
            <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:6px">Walk-forward stability</h4>
            ${UI.kv([
              ['Verdict', `<span class="chip ${wf.stability.verdict === 'consistent' ? 'green' : wf.stability.verdict === 'mixed' ? 'amber' : 'red'}">${UI.esc(wf.stability.verdict)}</span>`],
              ['Positive folds', `${wf.stability.positive_folds}/${wf.stability.total_folds}`],
              ['Sharpe range', `${UI.num(wf.stability.sharpe_range[0], 2)} – ${UI.num(wf.stability.sharpe_range[1], 2)}`],
            ])}
          </div>` : ''}
          ${oos ? `<div class="panel-body" style="border-top:1px solid var(--line)">
            <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:6px">Out-of-sample</h4>
            ${UI.kv([
              ['In-sample Sharpe', UI.num(oos.train.metrics.sharpe, 2)],
              ['Out-of-sample Sharpe', UI.num(oos.test.metrics.sharpe, 2)],
              ['Degradation', UI.num(oos.sharpe_degradation, 2)],
            ])}
            <div class="muted" style="font-size:11px;margin-top:6px">${UI.esc(oos.note)}</div>
          </div>` : ''}
          ${UI.table(['Entry', 'Exit', 'Qty', 'In', 'Out', 'P&L', 'R', 'Reason'],
            (r.trades || []).slice(-25).reverse().map((t) => [
              UI.date(t.entry_date), UI.date(t.exit_date), UI.num(t.quantity, 0),
              UI.num(t.entry_price, 2), UI.num(t.exit_price, 2),
              `<span class="${UI.cls(t.pnl)}">${UI.num(t.pnl, 0)}</span>`,
              UI.num(t.r_multiple, 2), UI.chip(t.exit_reason, t.exit_reason === 'target' ? 'green' : t.exit_reason === 'stop' ? 'red' : 'grey'),
            ]), { empty: 'No trades generated' })}
          <div class="panel-foot">${UI.esc(r.disclaimer || '')}<br>Data: ${UI.esc(r.assumptions.data_source)} (${UI.esc(r.assumptions.data_freshness)}). ${r.assumptions.is_synthetic_data ? 'SYNTHETIC DATA — results are not evidence of a real edge.' : ''}</div>`;
        Charts.line(view.querySelector('#bt-equity'),
          (r.equity_curve || []).map((p) => ({ value: p.equity })), { height: 200 });
      } catch (err) { out.innerHTML = UI.errorBox(err.message); }
    };
  },
};
