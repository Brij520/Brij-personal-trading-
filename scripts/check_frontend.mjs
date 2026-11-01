#!/usr/bin/env node
/**
 * Frontend smoke test without a browser.
 *
 * Loads the real frontend modules into a minimal DOM shim and executes every
 * page's render() against a live API server. Catches reference errors, bad
 * property access and template failures that a syntax check cannot.
 *
 * Usage: node scripts/check_frontend.mjs [baseUrl]
 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const BASE = process.argv[2] || 'http://127.0.0.1:8000';
const ROOT = path.resolve(import.meta.dirname, '..');
const FILES = [
  'js/api.js', 'js/charts.js', 'js/components.js', 'js/pages_market.js',
  'js/pages_research.js', 'js/pages_trading.js', 'js/pages_journal.js',
  'js/pages_system.js',
];

/* ------------------------------------------------------------------ DOM shim */
function makeElement(tag = 'div') {
  const el = {
    tagName: String(tag).toUpperCase(),
    children: [],
    _html: '',
    dataset: {},
    style: { cssText: '' },
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    hidden: false,
    value: '',
    checked: false,
    clientWidth: 900,
    files: [],
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._html; },
    set textContent(v) { this._html = String(v); },
    appendChild(child) { this.children.push(child); return child; },
    removeChild() {},
    remove() {},
    insertAdjacentHTML(_pos, html) { this._html += String(html); },
    addEventListener() {},
    removeEventListener() {},
    scrollIntoView() {},
    focus() {}, blur() {},
    click() {},
    querySelector(sel) {
      this._selMap = this._selMap || new Map();
      if (!this._selMap.has(sel)) {
        this._selMap.set(sel, makeElement(sel.includes('canvas') ? 'canvas' : 'div'));
      }
      return this._selMap.get(sel);
    },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 400 }; },
    getContext() { return ctx2d(); },
    setAttribute() {}, getAttribute() { return null; },
  };
  el.parentElement = { clientWidth: 900 };
  return el;
}

function ctx2d() {
  const noop = () => {};
  return new Proxy({}, {
    get(target, prop) {
      if (prop === 'createLinearGradient') return () => ({ addColorStop: noop });
      if (prop === 'measureText') return () => ({ width: 40 });
      if (prop === 'getImageData') return () => ({ data: [] });
      if (prop === 'canvas') return makeElement('canvas');
      return noop;
    },
    set() { return true; },
  });
}

const storage = new Map();
const document = {
  body: makeElement('body'),
  documentElement: makeElement('html'),
  getElementById: () => makeElement(),
  createElement: (tag) => makeElement(tag),
  querySelector: () => makeElement(),
  querySelectorAll: () => [],
  addEventListener() {},
  dispatchEvent() {},
};

const sandbox = {
  console,
  document,
  window: {
    devicePixelRatio: 1,
    addEventListener() {},
    localStorage: {
      getItem: (k) => storage.get(k) ?? null,
      setItem: (k, v) => storage.set(k, v),
    },
    location: { hash: '#/dashboard' },
  },
  localStorage: {
    getItem: (k) => storage.get(k) ?? null,
    setItem: (k, v) => storage.set(k, v),
  },
  performance: { now: () => Date.now() },
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval,
  requestAnimationFrame: (fn) => setTimeout(fn, 0),
  CSS: { escape: (s) => String(s).replace(/[^\w-]/g, '_') },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
  Event: class {},
  fetch: (url, opts) => fetch(url.startsWith('http') ? url : BASE + url, opts),
  location: { hash: '#/dashboard' },
  PAGES: {},
  State: undefined,
  window_localStorage: null,
};
sandbox.window.PAGES = sandbox.PAGES;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const file of FILES) {
  const code = fs.readFileSync(path.join(ROOT, 'frontend', file), 'utf8');
  try {
    vm.runInContext(code, sandbox, { filename: file });
  } catch (err) {
    console.error(`✗ failed to evaluate ${file}: ${err.message}`);
    process.exit(1);
  }
}

/* Collect html from an element and every sub-element created by querySelector,
   so second-stage renders (after await) are visible to the assertions. */
function fullHtml(el) {
  let out = el._html || '';
  if (el._selMap) for (const child of el._selMap.values()) out += fullHtml(child);
  return out;
}

/* ------------------------------------------------------------------- runner */
const pages = [
  ['dashboard', ''], ['market', ''], ['watchlist', ''], ['screener', ''],
  ['research', 'TCS'], ['fundamentals', 'TCS'], ['valuation', 'HDFCBANK'],
  ['technical', 'RELIANCE'], ['reports', 'RELIANCE'],
  ['swing', 'RELIANCE'], ['intraday', 'RELIANCE'], ['options', 'RELIANCE'],
  ['backtest', 'TCS'], ['portfolio', ''], ['journal', ''],
  ['learning', ''], ['risk', ''], ['settings', ''],
];

let failures = 0;
for (const [key, symbol] of pages) {
  const page = sandbox.PAGES[key];
  if (!page) { console.log(`✗ ${key}: page not registered`); failures++; continue; }
  const view = makeElement('main');
  const params = new URLSearchParams(symbol ? `symbol=${symbol}` : '');
  try {
    await page.render(view, params);
    const html = fullHtml(view);
    const bad = /undefined|\[object Object\]|NaN/.test(html);
    if (!html || html.length < 40) {
      console.log(`✗ ${key}: empty render (${html.length} chars)`); failures++;
    } else if (bad) {
      const sample = html.match(/.{0,40}(undefined|\[object Object\]|NaN).{0,40}/)?.[0];
      console.log(`✗ ${key}: suspicious output → ${sample}`);
      failures++;
    } else {
      const empties = (html.match(/class="empty"/g) || []).length;
      const suffix = empties ? `  (${empties} empty state${empties > 1 ? 's' : ''})` : '';
      console.log(`✓ ${key.padEnd(14)} ${String(html.length).padStart(6)} chars${suffix}`);
      if (process.env.DUMP) {
        // DUMP=1 writes the rendered HTML so a human can read what the page says.
        const dir = process.env.DUMP_DIR || '/tmp/bti-pages';
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(`${dir}/${key}.html`, `<!doctype html><meta charset="utf-8">${html}`);
      }
    }
  } catch (err) {
    console.log(`✗ ${key}: ${err.message}`);
    if (process.env.VERBOSE) console.error(err.stack);
    failures++;
  }
}

console.log(failures === 0 ? '\nAll pages rendered.' : `\n${failures} page(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
