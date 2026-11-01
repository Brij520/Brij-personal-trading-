/* Shared rendering helpers: formatting, panels, tables, chips, toasts. */

const UI = (() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const num = (v, d = 2) => {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  };
  const compact = (v) => {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    const n = Math.abs(Number(v));
    if (n >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
    if (n >= 1e5) return (v / 1e5).toFixed(2) + ' L';
    if (n >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return num(v, 2);
  };
  const pct = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`;
  const cls = (v) => (v === null || v === undefined) ? '' : (Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : '');
  const date = (v) => String(v || '').slice(0, 10);

  const chip = (text, tone = 'grey') => `<span class="chip ${tone}">${esc(text)}</span>`;
  const stanceChip = (stance) => {
    const map = { BULLISH: 'green', BEARISH: 'red', NEUTRAL: 'amber', INSUFFICIENT_DATA: 'grey' };
    return chip(String(stance || '—').replace(/_/g, ' '), map[stance] || 'grey');
  };
  const classChip = (c) => {
    const map = {
      'STRONG RESEARCH CANDIDATE': 'green', 'RESEARCH CANDIDATE': 'green',
      'WATCHLIST': 'amber', 'AVOID': 'red', 'INSUFFICIENT DATA': 'grey', 'NO TRADE': 'grey',
    };
    return chip(c, map[c] || 'grey');
  };

  const panel = (title, body, opts = {}) => `
    <section class="panel ${opts.class || ''}">
      ${title ? `<div class="panel-head"><h3>${esc(title)}</h3>${opts.actions || ''}</div>` : ''}
      <div class="panel-body ${opts.tight ? 'tight' : ''}">${body}</div>
      ${opts.foot ? `<div class="panel-foot">${opts.foot}</div>` : ''}
    </section>`;

  const stat = (label, value, delta, note) => `
    <div class="stat">
      <div class="label">${esc(label)}</div>
      <div class="value ${typeof delta === 'string' ? delta : ''}">${value}</div>
      ${note ? `<div class="note">${esc(note)}</div>` : ''}
    </div>`;

  const table = (headers, rows, opts = {}) => {
    const head = headers.map((h) => `<th>${esc(h)}</th>`).join('');
    const body = rows.length
      ? rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${headers.length}"><div class="empty">${esc(opts.empty || 'No rows')}</div></td></tr>`;
    return `<div class="table-scroll"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  };

  const kv = (pairs) => `<dl class="kv">${pairs
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;

  const list = (items, empty = 'None recorded') => items && items.length
    ? `<ul class="list">${items.map((i) => `<li><span class="li-dot">·</span><span>${i}</span></li>`).join('')}</ul>`
    : `<div class="empty">${esc(empty)}</div>`;

  const loading = (msg = 'Loading…') => `<div class="loading"><span class="spinner"></span> ${esc(msg)}</div>`;
  const errorBox = (msg) => `<div class="error-box"><strong>Request failed.</strong> ${esc(msg)}</div>`;
  const banner = (text, tone = '') => `<div class="banner ${tone}">${text}</div>`;
  const bar = (value, max = 100, tone = '') => {
    const w = Math.max(0, Math.min(100, (Number(value) / max) * 100));
    return `<div class="mini-bar"><div class="bar-track"><div class="bar-fill ${tone}" style="width:${w}%"></div></div>
      <span class="num" style="font-size:11px">${num(value, 0)}</span></div>`;
  };

  const toast = (message, tone = '') => {
    let host = document.getElementById('toasts');
    if (!host) {
      host = document.createElement('div');
      host.id = 'toasts';
      host.style.cssText = 'position:fixed;right:16px;bottom:34px;display:flex;flex-direction:column;gap:8px;z-index:100';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `banner ${tone}`;
    el.style.cssText = 'background:#151b24;border:1px solid #2a3543;border-left:3px solid '
      + (tone === 'danger' ? '#ea3943' : '#f0b90b') + ';min-width:240px;box-shadow:0 8px 24px rgba(0,0,0,.5)';
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  };

  const pageHead = (title, sub, actions = '') => `
    <div class="page-head">
      <div><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ''}</div>
      <div class="page-actions">${actions}</div>
    </div>`;

  const provenance = (p) => {
    if (!p) return '';
    const synthetic = p.freshness === 'SYNTHETIC' || p.is_synthetic;
    const bits = [
      p.source ? `src ${esc(p.source)}` : '',
      p.exchange ? esc(p.exchange) : '',
      p.freshness ? esc(p.freshness) : '',
      p.verification ? esc(String(p.verification).replace(/_/g, ' ')) : '',
    ].filter(Boolean).join(' · ');
    return `<span class="chip ${synthetic ? 'amber' : 'grey'}" title="data provenance">${bits}</span>`;
  };

  const qualityBadge = (q) => {
    if (!q) return '';
    const tone = q.score >= 85 ? 'green' : q.score >= 70 ? 'blue' : q.score >= 50 ? 'amber' : 'red';
    return `<span class="chip ${tone}">data quality ${q.score}/100 · ${esc(q.band)}</span>`;
  };

  return {
    esc, num, compact, pct, cls, date, chip, stanceChip, classChip, panel, stat, table, kv,
    list, loading, errorBox, banner, bar, toast, pageHead, provenance, qualityBadge,
  };
})();

/* Very small state container so pages can share the selected symbol. */
const State = {
  symbol: localStorage.getItem('bti.symbol') || 'RELIANCE',
  status: null,
  overview: null,
  setSymbol(symbol) {
    this.symbol = String(symbol).toUpperCase();
    localStorage.setItem('bti.symbol', this.symbol);
    document.dispatchEvent(new CustomEvent('symbol-changed', { detail: this.symbol }));
  },
};
