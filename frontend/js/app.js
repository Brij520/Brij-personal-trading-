/* Terminal shell: hash router, navigation, global search, market ticker. */

const NAV = [
  { group: 'Overview', items: [
    { key: 'dashboard', label: 'Dashboard', icon: '◈' },
    { key: 'market', label: 'Market Overview', icon: '≣' },
    { key: 'watchlist', label: 'Watchlist', icon: '★' },
  ]},
  { group: 'Research', items: [
    { key: 'research', label: 'AI Research Terminal', icon: '⌘' },
    { key: 'fundamentals', label: 'Fundamental Analysis', icon: '▤' },
    { key: 'valuation', label: 'Valuation', icon: '∑' },
    { key: 'technical', label: 'Technical Analysis', icon: '◱' },
    { key: 'screener', label: 'Stock Screener', icon: '⌕' },
    { key: 'reports', label: 'Research Reports', icon: '▦' },
  ]},
  { group: 'Trading', items: [
    { key: 'swing', label: 'Swing Trading', icon: '↗' },
    { key: 'intraday', label: 'Intraday Research', icon: '⏱' },
    { key: 'options', label: 'Options Intelligence', icon: '⇄' },
    { key: 'backtest', label: 'Backtesting Lab', icon: '⧉' },
  ]},
  { group: 'Capital', items: [
    { key: 'portfolio', label: 'Portfolio Manager', icon: '▣' },
    { key: 'journal', label: 'Trading Journal', icon: '✎' },
    { key: 'risk', label: 'Risk Management', icon: '⚠' },
    { key: 'learning', label: 'Learning Centre', icon: '◇' },
    { key: 'settings', label: 'Settings', icon: '⚙' },
  ]},
];

const PAGES = {};

function renderRail() {
  const rail = document.getElementById('rail');
  rail.innerHTML = NAV.map((group) => `
    <div class="rail-group">${group.group}</div>
    ${group.items.map((item) =>
      `<a href="#/${item.key}" data-page="${item.key}">
         <span class="ri">${item.icon}</span><span>${item.label}</span>
       </a>`).join('')}`).join('');
}

function setActive(key) {
  document.querySelectorAll('#rail a').forEach((a) => {
    a.classList.toggle('active', a.dataset.page === key);
  });
}

async function renderRoute() {
  const raw = location.hash.replace('#/', '') || 'dashboard';
  const [path, query] = raw.split('?');
  const [pageKey, pathSymbol] = path.split('/');
  if (pathSymbol) State.setSymbol(pathSymbol);
  const page = PAGES[pageKey] || PAGES.dashboard;
  setActive(PAGES[pageKey] ? pageKey : 'dashboard');
  const view = document.getElementById('view');
  view.innerHTML = UI.loading('Loading ' + pageKey + '…');
  try {
    await page.render(view, new URLSearchParams(query || ''));
  } catch (err) {
    view.innerHTML = UI.pageHead(page.title || pageKey, '') + UI.errorBox(err.message);
  }
  view.scrollTop = 0;
}

/* ------------------------------------------------------------- global search */
function wireSearch() {
  const input = document.getElementById('global-search');
  const box = document.getElementById('search-results');
  let timer = null;

  const open = (items) => {
    if (!items.length) { box.hidden = true; return; }
    box.innerHTML = items.map((it, i) => `
      <div class="search-item${i === 0 ? ' active' : ''}" data-symbol="${UI.esc(it.symbol)}">
        <div><div class="si-sym">${UI.esc(it.symbol)}</div>
        <div class="si-name">${UI.esc(it.name)}</div></div>
        <div class="si-name">${UI.esc(it.sector)}</div>
      </div>`).join('');
    box.hidden = false;
    box.querySelectorAll('.search-item').forEach((el) => {
      el.onclick = () => {
        State.setSymbol(el.dataset.symbol);
        box.hidden = true;
        input.value = '';
        location.hash = `#/research/${el.dataset.symbol}`;
      };
    });
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 1) { box.hidden = true; return; }
    timer = setTimeout(async () => {
      try { open((await API.search(q)).results); } catch (_) { box.hidden = true; }
    }, 160);
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      const first = box.querySelector('.search-item');
      if (first) first.click();
      else if (input.value.trim()) {
        const s = input.value.trim().toUpperCase();
        State.setSymbol(s);
        box.hidden = true;
        location.hash = `#/research/${s}`;
      }
    }
    if (ev.key === 'Escape') { box.hidden = true; input.blur(); }
  });
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('.search-wrap')) box.hidden = true;
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === '/' && ev.target.tagName !== 'INPUT' && ev.target.tagName !== 'TEXTAREA') {
      ev.preventDefault(); input.focus();
    }
  });
}

/* ------------------------------------------------------------------ ticker */
async function loadTicker() {
  const host = document.getElementById('ticker');
  try {
    const data = await API.overview();
    State.overview = data;
    host.innerHTML = data.indices
      .filter((i) => !i.error)
      .map((i) => `
        <span class="ticker-item">
          <span class="tk-name">${UI.esc(i.name)}</span>
          <span class="tk-val num">${UI.num(i.last, 2)}</span>
          <span class="${UI.cls(i.change_pct)} num">${UI.pct(i.change_pct)}</span>
        </span>`).join('');
  } catch (err) {
    host.innerHTML = `<span class="ticker-loading">market snapshot unavailable — ${UI.esc(err.message)}</span>`;
  }
}

/* ------------------------------------------------------------------ status */
async function loadStatus() {
  try {
    const status = await API.status();
    State.status = status;
    const pills = document.getElementById('status-pills');
    const safety = status.safety;
    pills.innerHTML = [
      `<span class="pill ${status.data_mode === 'demo' ? 'warn' : 'ok'}">DATA · ${status.data_mode.toUpperCase()}</span>`,
      `<span class="pill ${status.data_mode === 'demo' ? 'warn' : 'ok'}">${safety.live_trading ? 'LIVE' : 'RESEARCH ONLY'}</span>`,
      `<span class="pill ok">PAPER</span>`,
      `<span class="pill danger">F&amp;O OFF</span>`,
    ].join('');
    document.getElementById('sb-mode').textContent =
      `data mode: ${status.data_mode} · ${status.providers.universe_size} instruments · ${status.coverage.agents} agents`;
    document.getElementById('sb-safety').textContent =
      `research-only=${safety.research_only} · live=${safety.live_trading} · auto-exec=${safety.auto_execution} · orders disabled`;
    return status;
  } catch (err) {
    UI.toast('System status unavailable: ' + err.message, 'danger');
  }
}

/* -------------------------------------------------------------------- boot */
window.addEventListener('DOMContentLoaded', async () => {
  renderRail();
  wireSearch();
  document.addEventListener('symbol-changed', () => {
    const route = location.hash.replace('#/', '').split('?')[0];
    if (route.includes('/')) renderRoute();
  });
  await loadStatus();
  loadTicker();
  setInterval(loadTicker, 120000);
  window.addEventListener('hashchange', renderRoute);
  renderRoute();
});

window.addEventListener('resize', () => {
  const route = location.hash.replace('#/', '') || 'dashboard';
  if (PAGES.dashboard && document.querySelector('canvas.chart')) {
    clearTimeout(window.__resizeTimer);
    window.__resizeTimer = setTimeout(() => renderRoute(), 200);
  }
});
