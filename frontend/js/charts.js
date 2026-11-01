/* Canvas charting: candlesticks with volume, EMA overlays, crosshair readout,
   line/spark charts and option payoff diagrams. No external libraries. */

const Charts = (() => {
  const COL = {
    grid: '#1b2430', axis: '#6b7889', text: '#9aa7b8',
    up: '#16c784', down: '#ea3943', ema20: '#3d8bfd', ema50: '#f0b90b', ema200: '#a78bfa',
    crosshair: '#4a5768', accent: '#f0b90b',
  };

  function setupCanvas(canvas, height) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.parentElement.clientWidth || canvas.clientWidth || 600;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.height = height + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
  }

  function niceTicks(min, max, count = 5) {
    const span = max - min || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const steps = [1, 2, 2.5, 5, 10];
    let step = mag;
    for (const s of steps) { if (raw <= s * mag) { step = s * mag; break; } }
    const start = Math.ceil(min / step) * step;
    const out = [];
    for (let v = start; v <= max; v += step) out.push(v);
    return out;
  }

  function fmt(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  /* ------------------------------------------------------------ candlestick */
  function candlestick(canvas, bars, options = {}) {
    const height = options.height || 340;
    const { ctx, width } = setupCanvas(canvas, height);
    if (!bars || !bars.length) {
      ctx.fillStyle = COL.axis; ctx.font = '12px sans-serif';
      ctx.fillText('no data', 12, 24); return;
    }
    const padL = 8, padR = 62, padT = 12, padB = 22;
    const volH = Math.round((height - padT - padB) * 0.18);
    const priceH = height - padT - padB - volH - 10;
    const plotW = width - padL - padR;

    let lo = Infinity, hi = -Infinity, vmax = 0;
    for (const b of bars) {
      lo = Math.min(lo, b.low); hi = Math.max(hi, b.high);
      vmax = Math.max(vmax, b.volume || 0);
    }
    const overlays = ['ema20', 'ema50', 'ema200'];
    for (const key of overlays) {
      for (const b of bars) if (b[key] != null) { lo = Math.min(lo, b[key]); hi = Math.max(hi, b[key]); }
    }
    const pad = (hi - lo) * 0.06 || 1;
    lo -= pad; hi += pad;
    const x = (i) => padL + (i + 0.5) * (plotW / bars.length);
    const y = (p) => padT + (hi - p) / (hi - lo) * priceH;
    const step = plotW / bars.length;
    const bodyW = Math.max(1, Math.min(step * 0.68, 11));

    // grid + price axis
    ctx.font = '10px ui-monospace, monospace';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    for (const tick of niceTicks(lo, hi, 5)) {
      const py = y(tick);
      if (py < padT || py > padT + priceH) continue;
      ctx.strokeStyle = COL.grid; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, py + 0.5); ctx.lineTo(padL + plotW, py + 0.5); ctx.stroke();
      ctx.fillStyle = COL.axis;
      ctx.fillText(fmt(tick, tick < 100 ? 2 : 0), padL + plotW + 6, py);
    }

    // candles
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const up = b.close >= b.open;
      ctx.strokeStyle = up ? COL.up : COL.down;
      ctx.fillStyle = up ? COL.up : COL.down;
      const cx = x(i);
      ctx.beginPath();
      ctx.moveTo(cx, y(b.high)); ctx.lineTo(cx, y(b.low));
      ctx.lineWidth = 1; ctx.stroke();
      const top = y(Math.max(b.open, b.close));
      const bot = y(Math.min(b.open, b.close));
      ctx.fillRect(cx - bodyW / 2, top, bodyW, Math.max(1, bot - top));
    }

    // volume
    const volTop = padT + priceH + 10;
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const h = vmax ? (b.volume / vmax) * volH : 0;
      ctx.fillStyle = b.close >= b.open ? 'rgba(22,199,132,.35)' : 'rgba(234,57,67,.35)';
      ctx.fillRect(x(i) - bodyW / 2, volTop + volH - h, bodyW, h);
    }

    // overlays
    for (const key of overlays) {
      ctx.strokeStyle = COL[key]; ctx.lineWidth = 1.4;
      ctx.beginPath(); let started = false;
      for (let i = 0; i < bars.length; i++) {
        const v = bars[i][key];
        if (v == null) continue;
        if (!started) { ctx.moveTo(x(i), y(v)); started = true; } else ctx.lineTo(x(i), y(v));
      }
      ctx.stroke();
    }

    // time axis
    ctx.fillStyle = COL.axis; ctx.textAlign = 'center';
    const labels = Math.min(6, bars.length);
    for (let k = 0; k < labels; k++) {
      const idx = Math.floor(k * (bars.length - 1) / Math.max(1, labels - 1));
      const d = String(bars[idx].time).slice(0, 10);
      ctx.fillText(d, x(idx), height - 8);
    }

    // legend
    ctx.textAlign = 'left';
    let lx = padL + 4;
    const legend = [['EMA20', COL.ema20], ['EMA50', COL.ema50], ['EMA200', COL.ema200]];
    for (const [name, color] of legend) {
      ctx.fillStyle = color; ctx.fillRect(lx, padT + 2, 8, 2);
      ctx.fillStyle = COL.text; ctx.fillText(name, lx + 12, padT + 4);
      lx += 58;
    }

    // crosshair interaction
    const tooltip = options.tooltip;
    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const idx = Math.max(0, Math.min(bars.length - 1, Math.floor((mx - padL) / step)));
      const b = bars[idx];
      if (tooltip) {
        tooltip.innerHTML = `
          <div class="tt-date">${String(b.time).replace('T', ' ').slice(0, 16)}</div>
          <div class="tt-row"><span>O</span><b>${fmt(b.open)}</b></div>
          <div class="tt-row"><span>H</span><b>${fmt(b.high)}</b></div>
          <div class="tt-row"><span>L</span><b>${fmt(b.low)}</b></div>
          <div class="tt-row"><span>C</span><b>${fmt(b.close)}</b></div>
          <div class="tt-row"><span>V</span><b>${Number(b.volume).toLocaleString('en-IN')}</b></div>`;
        tooltip.hidden = false;
        const left = Math.min(rect.width - 150, mx + 14);
        tooltip.style.left = left + 'px';
        tooltip.style.top = '12px';
      }
    };
    canvas.onmouseleave = () => { if (tooltip) tooltip.hidden = true; };
  }

  /* --------------------------------------------------------------- line */
  function line(canvas, series, options = {}) {
    const height = options.height || 150;
    const { ctx, width } = setupCanvas(canvas, height);
    if (!series || series.length < 2) {
      ctx.fillStyle = COL.axis; ctx.font = '11px sans-serif';
      ctx.fillText('no data', 10, 20); return;
    }
    const padL = 4, padR = 46, padT = 8, padB = 16;
    const values = series.map((p) => p.value);
    let lo = Math.min(...values), hi = Math.max(...values);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const x = (i) => padL + i * (plotW / (series.length - 1));
    const y = (v) => padT + (hi - v) / (hi - lo) * plotH;

    const colour = options.color
      || (values[values.length - 1] >= values[0] ? COL.up : COL.down);

    if (options.fill !== false) {
      const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
      grad.addColorStop(0, colour + '38');
      grad.addColorStop(1, colour + '00');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(x(0), padT + plotH);
      series.forEach((p, i) => ctx.lineTo(x(i), y(p.value)));
      ctx.lineTo(x(series.length - 1), padT + plotH);
      ctx.closePath(); ctx.fill();
    }
    ctx.strokeStyle = colour; ctx.lineWidth = 1.5;
    ctx.beginPath();
    series.forEach((p, i) => (i ? ctx.lineTo(x(i), y(p.value)) : ctx.moveTo(x(i), y(p.value))));
    ctx.stroke();

    ctx.fillStyle = COL.axis; ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'left';
    ctx.fillText(fmt(hi, 1), padL + plotW + 4, padT + 4);
    ctx.fillText(fmt(lo, 1), padL + plotW + 4, padT + plotH);
    if (options.zeroLine && lo < 0 && hi > 0) {
      ctx.strokeStyle = COL.grid; ctx.beginPath();
      ctx.moveTo(padL, y(0)); ctx.lineTo(padL + plotW, y(0)); ctx.stroke();
    }
  }

  /* ---------------------------------------------------------- payoff chart */
  function payoff(canvas, points, options = {}) {
    const height = options.height || 230;
    const { ctx, width } = setupCanvas(canvas, height);
    if (!points || points.length < 2) return;
    const padL = 8, padR = 62, padT = 12, padB = 22;
    const values = points.map((p) => p.pnl);
    let lo = Math.min(...values, 0), hi = Math.max(...values, 0);
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    const plotW = width - padL - padR, plotH = height - padT - padB;
    const xs = points.map((p) => p.spot);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const x = (v) => padL + (v - xmin) / (xmax - xmin) * plotW;
    const y = (v) => padT + (hi - v) / (hi - lo) * plotH;

    ctx.font = '10px ui-monospace, monospace';
    for (const tick of niceTicks(lo, hi, 4)) {
      const py = y(tick);
      ctx.strokeStyle = COL.grid; ctx.beginPath();
      ctx.moveTo(padL, py + .5); ctx.lineTo(padL + plotW, py + .5); ctx.stroke();
      ctx.fillStyle = COL.axis; ctx.fillText(fmt(tick, 0), padL + plotW + 5, py + 3);
    }
    // zero line
    ctx.strokeStyle = '#3a4757'; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(padL, y(0)); ctx.lineTo(padL + plotW, y(0)); ctx.stroke();
    ctx.setLineDash([]);

    const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, 'rgba(22,199,132,.18)');
    grad.addColorStop(1, 'rgba(22,199,132,0)');
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.moveTo(x(xs[0]), y(0));
    points.forEach((p) => ctx.lineTo(x(p.spot), y(p.pnl)));
    ctx.lineTo(x(xs[xs.length - 1]), y(0)); ctx.closePath(); ctx.fill();

    ctx.strokeStyle = COL.accent; ctx.lineWidth = 1.7;
    ctx.beginPath();
    points.forEach((p, i) => (i ? ctx.lineTo(x(p.spot), y(p.pnl)) : ctx.moveTo(x(p.spot), y(p.pnl))));
    ctx.stroke();

    if (options.spot) {
      ctx.strokeStyle = '#4a5768'; ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(x(options.spot), padT); ctx.lineTo(x(options.spot), padT + plotH); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = COL.axis; ctx.fillText('spot', x(options.spot) + 3, padT + 8);
    }
    for (const be of options.breakevens || []) {
      if (be < xmin || be > xmax) continue;
      ctx.strokeStyle = 'rgba(240,185,11,.45)';
      ctx.beginPath(); ctx.moveTo(x(be), padT); ctx.lineTo(x(be), padT + plotH); ctx.stroke();
    }
    ctx.fillStyle = COL.axis; ctx.textAlign = 'center';
    ctx.fillText(fmt(xmin, 0), padL + 18, height - 6);
    ctx.fillText(fmt(xmax, 0), padL + plotW - 18, height - 6);
  }

  /* ---------------------------------------------------------- horizontal bars */
  function bars(canvas, rows, options = {}) {
    const height = options.height || 220;
    const { ctx, width } = setupCanvas(canvas, height);
    if (!rows || !rows.length) return;
    const labelW = options.labelWidth || 118;
    const rowH = Math.min(24, (height - 12) / rows.length);
    const plotW = width - labelW - 60;
    const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value))) || 1;
    const zeroX = labelW + plotW / 2;
    ctx.font = '10.5px ui-monospace, monospace';
    rows.forEach((row, i) => {
      const cy = 8 + i * rowH + rowH / 2;
      const w = (Math.abs(row.value) / maxAbs) * (plotW / 2 - 4);
      ctx.fillStyle = COL.text; ctx.textAlign = 'right';
      ctx.fillText(String(row.label).slice(0, 18), labelW - 8, cy + 3);
      ctx.fillStyle = row.value >= 0 ? COL.up : COL.down;
      if (row.value >= 0) ctx.fillRect(zeroX, cy - 5, w, 10);
      else ctx.fillRect(zeroX - w, cy - 5, w, 10);
      ctx.fillStyle = COL.textDim || '#9aa7b8'; ctx.textAlign = 'left';
      ctx.fillText(`${row.value >= 0 ? '+' : ''}${fmt(row.value, 2)}%`, labelW + plotW + 6, cy + 3);
    });
    ctx.strokeStyle = COL.grid;
    ctx.beginPath(); ctx.moveTo(zeroX, 4); ctx.lineTo(zeroX, 8 + rows.length * rowH); ctx.stroke();
  }

  return { candlestick, line, payoff, bars, fmt };
})();
