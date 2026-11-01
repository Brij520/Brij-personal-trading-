/* Pages: Risk Management, Settings. */

PAGES.risk = {
  title: 'Risk Management',
  async render(view, params) {
    const symbol = (params.get('symbol') || State.symbol).toUpperCase();
    State.setSymbol(symbol);
    const [limits, status] = await Promise.all([API.riskLimits(), API.status().catch(() => State.status)]);
    const L = limits.limits;
    view.innerHTML = UI.pageHead('Risk management',
      'The only component with veto power. It cannot place an order, and no agent can override its rejection.') + `
      ${UI.banner('<strong>These are platform defaults, not your personal limits.</strong> Set capital explicitly before using any size output. Risk approval is a controls check — it is not advice and not authorisation.', 'info')}
      <div class="grid g-1-2">
        ${UI.panel('Limits in force', UI.kv([
          ['Risk per trade', UI.num(L.max_position_risk_pct, 2) + '% of capital'],
          ['Portfolio heat cap', UI.num(L.max_portfolio_heat_pct, 2) + '%'],
          ['Max single stock', UI.num(L.max_single_stock_pct, 2) + '%'],
          ['Max sector', UI.num(L.max_sector_pct, 2) + '%'],
          ['Daily loss limit', UI.num(L.daily_loss_limit_pct, 2) + '%'],
          ['Minimum reward:risk', UI.num(L.min_reward_risk, 2)],
        ]), { foot: 'Configurable through BTI_* environment variables.' })}
        ${UI.panel('Position size calculator', `
          <div class="form-row">
            <div class="field"><label>Capital (INR)</label><input id="ps-capital" type="number" value="500000" /></div>
            <div class="field"><label>Entry</label><input id="ps-entry" type="number" step="0.05" value="100" /></div>
            <div class="field"><label>Stop loss</label><input id="ps-stop" type="number" step="0.05" value="95" /></div>
            <div class="field"><label>Risk % of capital</label><input id="ps-risk" type="number" step="0.1" value="1" /></div>
            <div class="field"><label>Max position %</label><input id="ps-maxpos" type="number" step="1" value="20" /></div>
          </div>
          <button class="btn primary" id="ps-run" style="margin-top:10px;width:100%">Calculate</button>
          <div id="ps-out" style="margin-top:12px"></div>`) }
      </div>
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Validate a trade plan', `
          <div class="form-row">
            <div class="field"><label>Symbol</label><input id="v-symbol" value="${UI.esc(symbol)}" /></div>
            <div class="field"><label>Side</label><select id="v-side"><option>LONG</option><option>SHORT</option></select></div>
            <div class="field"><label>Entry</label><input id="v-entry" type="number" step="0.05" /></div>
            <div class="field"><label>Stop</label><input id="v-stop" type="number" step="0.05" /></div>
            <div class="field"><label>Target</label><input id="v-target" type="number" step="0.05" /></div>
            <div class="field"><label>Capital</label><input id="v-capital" type="number" value="500000" /></div>
            <div class="field"><label>Open risk %</label><input id="v-openrisk" type="number" value="0" step="0.1" /></div>
            <div class="field"><label>F&amp;O?</label><select id="v-fno"><option value="false">No</option><option value="true">Yes</option></select></div>
          </div>
          <button class="btn primary" id="v-run" style="margin-top:10px;width:100%">Run risk check</button>
          <div id="v-out" style="margin-top:12px"></div>`) }
        ${UI.panel('Sizing formulas', `
          <pre style="font-family:var(--mono);font-size:11px;color:var(--text-dim);white-space:pre-wrap;margin:0">
risk_amount   = capital × risk_pct / 100
risk_per_unit = |entry − stop|
quantity      = floor(risk_amount / risk_per_unit / lot) × lot
              capped by capital × max_position_pct / entry

ATR variant:
stop_distance = max(atr × multiple, entry × 0.005)
stop          = entry − stop_distance

Kelly (capped at 25%):
f* = p − (1 − p) / (avg_win / avg_loss)</pre>
          <div style="margin-top:10px">${UI.list([
            'A stop inside 0.8 × ATR is treated as noise and flagged.',
            'Reward-to-risk below the configured minimum is rejected outright, not warned.',
            'Adding a trade that breaches portfolio heat is rejected.',
          ])}</div>`, { foot: 'Rejections are final: overridable is always false.' })}
      </div>`;

    view.querySelector('#ps-run').onclick = async () => {
      const out = view.querySelector('#ps-out');
      try {
        const r = await API.positionSize({
          capital: Number(view.querySelector('#ps-capital').value),
          entry: Number(view.querySelector('#ps-entry').value),
          stop_loss: Number(view.querySelector('#ps-stop').value),
          risk_pct: Number(view.querySelector('#ps-risk').value),
          max_position_pct: Number(view.querySelector('#ps-maxpos').value),
        });
        out.innerHTML = `
          <div class="grid g2">
            ${UI.stat('Quantity', UI.num(r.quantity, 0), '', 'shares')}
            ${UI.stat('Position value', '₹' + UI.compact(r.position_value), '', `${UI.num(r.risk_pct_of_capital, 2)}% risked`)}
          </div>
          <div class="muted" style="font-size:11px;margin-top:8px">${UI.esc(r.formula)}</div>`;
      } catch (err) { out.innerHTML = UI.errorBox(err.message); }
    };

    view.querySelector('#v-run').onclick = async () => {
      const out = view.querySelector('#v-out');
      try {
        const r = await API.validate({
          symbol: view.querySelector('#v-symbol').value.trim().toUpperCase(),
          side: view.querySelector('#v-side').value,
          entry: Number(view.querySelector('#v-entry').value),
          stop_loss: Number(view.querySelector('#v-stop').value),
          target: Number(view.querySelector('#v-target').value),
          capital: Number(view.querySelector('#v-capital').value),
          open_risk_pct: Number(view.querySelector('#v-openrisk').value),
          is_fno: view.querySelector('#v-fno').value === 'true',
        });
        out.innerHTML = `
          <div class="verdict ${r.approved ? 'candidate' : 'avoid'}">
            <div class="v-class">${r.approved ? 'APPROVED (controls only)' : 'REJECTED'}</div>
            ${r.reasons.length ? `<div class="v-reason">${r.reasons.map(UI.esc).join('<br>')}</div>` : ''}
            ${r.warnings.length ? `<div class="v-reason" style="color:var(--amber)">${r.warnings.map(UI.esc).join('<br>')}</div>` : ''}
          </div>
          ${UI.kv([
            ['Reward : risk', UI.num(r.reward_risk, 2)],
            ['Quantity', UI.num(r.quantity, 0)],
            ['Position value', '₹' + UI.compact(r.position_value)],
            ['Risk amount', '₹' + UI.compact(r.risk_amount)],
            ['Risk % capital', UI.num(r.risk_pct_capital, 3) + '%'],
            ['Portfolio heat', UI.num(r.portfolio_heat_pct, 3) + '%'],
            ['Overridable', r.overridable ? 'yes' : 'no — final'],
          ])}
          <div class="muted" style="font-size:10.5px;margin-top:8px">${UI.esc(r.disclaimer)}</div>`;
      } catch (err) { out.innerHTML = UI.errorBox(err.message); }
    };
  },
};

PAGES.settings = {
  title: 'Settings',
  async render(view) {
    const status = await API.status();
    State.status = status;
    const s = status.safety;
    const flag = (label, value, dangerWhenTrue = true) => {
      const tone = value ? (dangerWhenTrue ? 'red' : 'green') : 'green';
      return `<div class="stat"><div class="label">${UI.esc(label)}</div>
        <div class="value"><span class="chip ${tone}">${value ? 'TRUE' : 'FALSE'}</span></div></div>`;
    };
    view.innerHTML = UI.pageHead('Settings & system',
      `${status.app} v${status.version} · ${status.environment} · owner ${status.owner}`) + `
      ${UI.banner(`<strong>Data mode: ${status.data_mode.toUpperCase()}.</strong> ${status.data_mode === 'demo'
        ? 'All market data is synthetic and generated deterministically. Real NSE/BSE endpoints are not reachable from this deployment.'
        : 'Live providers are configured; failures surface as errors rather than falling back silently.'}`, status.data_mode === 'demo' ? 'danger' : 'info')}
      <div class="grid g4" style="margin-bottom:12px">
        ${flag('RESEARCH_ONLY', s.research_only, false)}
        ${flag('PAPER_TRADING', s.paper_trading, false)}
        ${flag('LIVE_TRADING', s.live_trading)}
        ${flag('AUTO_EXECUTION', s.auto_execution)}
      </div>
      ${UI.panel('Safety kernel', `
        <p style="margin-top:0;font-size:12px;color:var(--text-dim)">
        The three dangerous flags are immutable properties in <code>backend/core/config.py</code>. They are not
        read from a database, an API call or a UI toggle, and any environment variable that tries to enable
        them raises <code>SafetyViolation</code> at startup.</p>
        ${UI.kv([
          ['Order placement', '<span class="chip red">disabled</span>'],
          ['Order modification', '<span class="chip red">disabled</span>'],
          ['Order cancellation', '<span class="chip red">disabled</span>'],
          ['GTT creation', '<span class="chip red">disabled</span>'],
          ['F&amp;O ordering', '<span class="chip red">disabled</span>'],
          ['Broker integrations', UI.esc(s.broker_integrations)],
          ['LLM provider', UI.esc(s.llm_provider) + (status.llm.provider === 'none' ? ' (deterministic rule engine)' : '')],
        ])}`)}
      <div class="grid g2" style="margin-top:12px">
        ${UI.panel('Coverage', UI.kv([
          ['Instruments', UI.num(status.coverage.instruments, 0)],
          ['Sectors', UI.num(status.coverage.sectors, 0)],
          ['Agents', UI.num(status.coverage.agents, 0)],
          ['Strategies', UI.num(status.coverage.strategies, 0)],
          ['Scanner conditions', UI.num(status.coverage.scanner_conditions, 0)],
        ]))}
        ${UI.panel('Providers', UI.table(['Provider', 'Mode', 'Healthy'], 
          (status.providers.providers || []).map((p) => [
            UI.esc(p.provider), p.is_synthetic ? UI.chip('SYNTHETIC', 'amber') : UI.chip('LIVE', 'green'),
            p.healthy ? UI.chip('ok', 'green') : UI.chip('unavailable', 'red'),
          ]), { tight: true }), { foot: 'Provider failover is always labelled in API responses.' })}
      </div>
      ${UI.panel('Configuration reference', UI.table(['Variable', 'Purpose', 'Default'], [
        ['BTI_DATA_MODE', 'demo | auto | live', 'demo'],
        ['BTI_MAX_POSITION_RISK_PCT', 'risk per trade', status.limits.max_position_risk_pct],
        ['BTI_MAX_PORTFOLIO_HEAT_PCT', 'aggregate open risk', status.limits.max_portfolio_heat_pct],
        ['BTI_MIN_REWARD_RISK', 'minimum R:R', status.limits.min_reward_risk],
        ['BTI_LLM_PROVIDER', 'none | openai | anthropic | gemini | ollama', 'none'],
        ['BTI_ZERODHA_API_KEY', 'read-only research credentials', 'unset'],
        ['BTI_DHAN_ACCESS_TOKEN', 'read-only research credentials', 'unset'],
      ], { tight: true }))}
      ${UI.banner('Secrets are read from the environment only. Nothing is stored in the repository, and no credential is ever sent to the browser.', 'info')}
      <div style="margin-top:12px;font-size:11px;color:var(--muted)">${UI.esc(status.disclaimer)}</div>`;
  },
};
