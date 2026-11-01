/* Thin API client. Every call goes through here so error handling, timing and
   the "no order routing" invariant are enforced in one place. */

const API = (() => {
  const base = '';
  let lastLatency = null;

  async function request(path, options = {}) {
    const started = performance.now();
    const response = await fetch(base + path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const elapsed = Math.round(performance.now() - started);
    lastLatency = elapsed;
    const sb = document.getElementById('sb-latency');
    if (sb) sb.textContent = `${elapsed} ms · ${path.split('?')[0]}`;

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        detail = payload.message || payload.detail || detail;
        if (typeof detail === 'object') detail = JSON.stringify(detail);
      } catch (_) { /* keep status text */ }
      throw new Error(detail);
    }
    return response.json();
  }

  const get = (path) => request(path);
  const post = (path, body) =>
    request(path, { method: 'POST', body: JSON.stringify(body || {}) });
  const del = (path) => request(path, { method: 'DELETE' });

  return {
    get, post, del,
    latency: () => lastLatency,
    status: () => get('/api/system/status'),
    overview: () => get('/api/market/overview'),
    search: (q) => get(`/api/universe/search?q=${encodeURIComponent(q)}&limit=12`),
    universe: () => get('/api/universe'),
    quote: (s) => get(`/api/stocks/${s}/quote`),
    chart: (s, timeframe = '1d', bars = 400) =>
      get(`/api/stocks/${s}/chart?timeframe=${timeframe}&bars=${bars}`),
    fundamentals: (s) => get(`/api/stocks/${s}/fundamentals`),
    technical: (s, timeframe = '1d') =>
      get(`/api/stocks/${s}/technical?timeframe=${timeframe}`),
    valuation: (s) => get(`/api/stocks/${s}/valuation`),
    news: (s) => get(`/api/stocks/${s}/news`),
    options: (s) => get(`/api/stocks/${s}/options`),
    payoff: (legs, spot, lotSize) =>
      post('/api/options/payoff', { legs, spot, lot_size: lotSize || 1 }),
    research: (s, lookback = 750) => post(`/api/research/${s}`, { symbol: s, lookback }),
    agent: (name, s) => post(`/api/agents/${name}/run?symbol=${s}`),
    riskLimits: () => get('/api/risk/limits'),
    positionSize: (payload) => post('/api/risk/position-size', payload),
    validate: (payload) => post('/api/risk/validate', payload),
    strategies: () => get('/api/backtest/strategies'),
    backtest: (payload) => post('/api/backtest/run', payload),
    compare: (payload) => post('/api/backtest/compare', payload),
    screenerDefs: () => get('/api/screener/definitions'),
    screener: (scans, sector, limit = 30) =>
      get(`/api/screener?scans=${encodeURIComponent(scans.join(','))}`
          + (sector ? `&sector=${encodeURIComponent(sector)}` : '')
          + `&limit=${limit}`),
    trades: (status) => get(`/api/journal/trades${status ? `?status=${status}` : ''}`),
    addTrade: (payload) => post('/api/journal/trades', payload),
    closeTrade: (id, payload) => post(`/api/journal/trades/${id}/close`, payload),
    journalPerformance: () => get('/api/journal/performance'),
    review: (period) => get(`/api/journal/review?period=${period}`),
    notes: () => get('/api/journal/notes'),
    addNote: (payload) => post('/api/journal/notes', payload),
    holdings: () => get('/api/portfolio/holdings'),
    importHoldings: (holdings) => post('/api/portfolio/import', { holdings }),
    portfolioAnalysis: () => get('/api/portfolio/analysis'),
    snapshots: () => get('/api/portfolio/snapshots'),
    takeSnapshot: () => post('/api/portfolio/snapshot'),
  };
})();
