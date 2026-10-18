/**
 * Clock — Stopwatch tab: digital readout (click it for the analog dial), the
 * Lap No. / Split / Total table, and Lap·Reset / Start·Stop buttons.
 *
 * Elapsed time is stored as startedAt + accumulated, so the stopwatch keeps
 * running across reloads and while the window is closed (like MTStopwatch).
 */

import { h } from './dom.js';
import { getState, update } from './store.js';
import { formatStopwatch, lapExtrema } from './time.js';

const NS = 'http://www.w3.org/2000/svg';

function elapsed(sw, now = Date.now()) {
  return sw.accumulated + (sw.startedAt ? now - sw.startedAt : 0);
}

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/** 60-second dial with a 30-minute sub-dial, total and lap hands. */
function buildDial() {
  const s = svgEl('svg', { viewBox: '-100 -100 200 200', class: 'clk-dial', role: 'img', 'aria-label': 'Analog stopwatch' });
  for (let i = 0; i < 240; i++) {
    const major = i % 20 === 0, mid = i % 4 === 0;
    const a = (i / 240) * Math.PI * 2;
    const r1 = 94, r2 = major ? 84 : mid ? 87 : 90;
    s.append(svgEl('line', {
      x1: (Math.sin(a) * r1).toFixed(2), y1: (-Math.cos(a) * r1).toFixed(2),
      x2: (Math.sin(a) * r2).toFixed(2), y2: (-Math.cos(a) * r2).toFixed(2),
      class: major ? 'clk-tick-major' : mid ? 'clk-tick-mid' : 'clk-tick',
    }));
  }
  for (let n = 5; n <= 60; n += 5) {
    const a = (n / 60) * Math.PI * 2;
    const t = svgEl('text', { x: (Math.sin(a) * 72).toFixed(2), y: (-Math.cos(a) * 72 + 5).toFixed(2), class: 'clk-dial-num' });
    t.textContent = String(n);
    s.append(t);
  }
  const sub = svgEl('g', { transform: 'translate(0 -34)' });
  sub.append(svgEl('circle', { r: 20, class: 'clk-subdial' }));
  for (let i = 0; i < 30; i++) {
    const a = (i / 30) * Math.PI * 2, r2 = i % 5 === 0 ? 15 : 17;
    sub.append(svgEl('line', { x1: (Math.sin(a) * 19).toFixed(2), y1: (-Math.cos(a) * 19).toFixed(2), x2: (Math.sin(a) * r2).toFixed(2), y2: (-Math.cos(a) * r2).toFixed(2), class: 'clk-tick' }));
  }
  for (const n of [5, 10, 15, 20, 25, 30]) {
    const a = (n / 30) * Math.PI * 2;
    const t = svgEl('text', { x: (Math.sin(a) * 10.5).toFixed(2), y: (-Math.cos(a) * 10.5 + 2.2).toFixed(2), class: 'clk-subdial-num' });
    t.textContent = String(n);
    sub.append(t);
  }
  const subHand = svgEl('line', { x1: 0, y1: 3, x2: 0, y2: -17, class: 'clk-hand-sub' });
  sub.append(subHand, svgEl('circle', { r: 1.6, class: 'clk-hand-sub-pin' }));
  s.append(sub);
  const readout = svgEl('text', { x: 0, y: 40, class: 'clk-dial-readout' });
  s.append(readout);
  const lapHand = svgEl('line', { x1: 0, y1: 14, x2: 0, y2: -92, class: 'clk-hand-lap' });
  const mainHand = svgEl('line', { x1: 0, y1: 14, x2: 0, y2: -92, class: 'clk-hand-main' });
  s.append(lapHand, mainHand, svgEl('circle', { r: 3.4, class: 'clk-hand-pin' }), svgEl('circle', { r: 1.5, class: 'clk-hand-pin-hole' }));
  return { el: s, mainHand, lapHand, subHand, readout };
}

export function createStopwatch() {
  const el = h('div.clk-view.clk-stopwatch');
  const digits = h('button.clk-sw-digits', { type: 'button', title: 'View Analog Stopwatch', 'aria-live': 'off' });
  const dial = buildDial();
  const dialWrap = h('button.clk-sw-dial', { type: 'button', title: 'View Digital Stopwatch' }, dial.el);
  const table = h('div.clk-laps', { role: 'table', 'aria-label': 'Laps' },
    h('div.clk-lap-head', { role: 'row' }, h('span', { role: 'columnheader', text: 'Lap No.' }), h('span', { role: 'columnheader', text: 'Split' }), h('span', { role: 'columnheader', text: 'Total' })));
  const rows = h('div.clk-lap-rows', { role: 'rowgroup' });
  table.append(rows);
  const left = h('button.clk-pill.clk-pill-grey', { type: 'button' });
  const right = h('button.clk-pill', { type: 'button' });
  el.append(h('div.clk-sw-face', {}, digits, dialWrap), table, h('div.clk-bottom-bar', {}, left, right));

  let raf = 0;
  let currentRow = null;

  const toggleAnalog = () => update(s => { s.stopwatch.analog = !s.stopwatch.analog; });
  digits.addEventListener('click', toggleAnalog);
  dialWrap.addEventListener('click', toggleAnalog);

  left.addEventListener('click', () => update(s => {
    const sw = s.stopwatch;
    if (sw.startedAt) {
      const total = elapsed(sw);
      const prev = sw.laps.reduce((a, b) => a + b, 0);
      sw.laps.push(total - prev);
    } else {
      sw.accumulated = 0; sw.laps = [];
    }
  }));
  right.addEventListener('click', () => update(s => {
    const sw = s.stopwatch;
    if (sw.startedAt) { sw.accumulated = elapsed(sw); sw.startedAt = null; }
    else sw.startedAt = Date.now();
  }));

  function lapRow(n, split, total, cls = '') {
    return h(`div.clk-lap${cls}`, { role: 'row' },
      h('span', { role: 'cell', text: `Lap ${n}` }), h('span', { role: 'cell', text: formatStopwatch(split) }), h('span', { role: 'cell', text: formatStopwatch(total) }));
  }

  function render() {
    const sw = getState().stopwatch;
    const running = !!sw.startedAt;
    const total = elapsed(sw);
    const hasTime = total > 0;
    el.classList.toggle('clk-analog', !!sw.analog);
    left.textContent = running || !hasTime ? 'Lap' : 'Reset';
    left.disabled = !running && !hasTime;
    right.textContent = running ? 'Stop' : 'Start';
    right.classList.toggle('clk-pill-red', running);
    right.classList.toggle('clk-pill-green', !running);

    rows.replaceChildren();
    currentRow = null;
    const { fastest, slowest } = lapExtrema(sw.laps);
    const totals = [];
    sw.laps.reduce((acc, v, i) => (totals[i] = acc + v), 0);
    if (hasTime && (running || sw.laps.length)) {
      const done = sw.laps.reduce((a, b) => a + b, 0);
      currentRow = lapRow(sw.laps.length + 1, total - done, total);
      rows.append(currentRow);
    }
    for (let i = sw.laps.length - 1; i >= 0; i--) {
      const cls = i === fastest ? '.clk-lap-best' : i === slowest ? '.clk-lap-worst' : '';
      rows.append(lapRow(i + 1, sw.laps[i], totals[i], cls));
    }
    paint();
    cancelAnimationFrame(raf);
    if (running) loop();
  }

  function paint() {
    const sw = getState().stopwatch;
    const total = elapsed(sw);
    digits.textContent = formatStopwatch(total);
    const done = sw.laps.reduce((a, b) => a + b, 0);
    if (currentRow) {
      currentRow.children[1].textContent = formatStopwatch(total - done);
      currentRow.children[2].textContent = formatStopwatch(total);
    }
    if (sw.analog) {
      dial.mainHand.setAttribute('transform', `rotate(${((total / 1000) % 60) * 6})`);
      dial.lapHand.setAttribute('transform', `rotate(${(((total - done) / 1000) % 60) * 6})`);
      dial.lapHand.style.display = sw.laps.length ? '' : 'none';
      dial.subHand.setAttribute('transform', `rotate(${((total / 60000) % 30) * 12})`);
      dial.readout.textContent = formatStopwatch(total);
    }
  }

  function loop() {
    paint();
    raf = requestAnimationFrame(loop);
  }

  return {
    el,
    canAdd: false,
    render,
    mount: render,
    unmount() { cancelAnimationFrame(raf); },
    shortcut(key) {
      if (key === 'start') right.click();
      if (key === 'lap' && !left.disabled) left.click();
    },
  };
}
