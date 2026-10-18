/**
 * Clock — World Clock tab: world map with the live day/night terminator and
 * city pins, analog clock cards underneath, and the "Choose a City" sheet.
 */

import { h, ICONS, openSheet, contextMenu } from './dom.js';
import { getState, update, uid } from './store.js';
import { CITIES } from './cities.js';
import { LAND_PATH } from './worldLand.js';
import {
  terminator, formatZoneTime, relativeDay, offsetLabel, zonedClock, sunTimes, isDaylight,
} from './time.js';

const MAX_CLOCKS = 24;
// Visible latitude band, matching Clock's crop (polar caps trimmed).
const LAT_TOP = 84, LAT_BOTTOM = -62;
const VIEW = { x: 0, y: 90 - LAT_TOP, w: 360, h: LAT_TOP - LAT_BOTTOM };
const NS = 'http://www.w3.org/2000/svg';

const project = (lat, lon) => ({ x: lon + 180, y: 90 - lat });

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function nightPath(date) {
  const { points, darkPole } = terminator(date, 2);
  const pts = points.map(([lon, lat]) => project(lat, lon));
  const edge = darkPole === 'south' ? 180 : 0;
  let d = `M0 ${edge}`;
  for (const p of pts) d += `L${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
  return `${d}L360 ${edge}Z`;
}

function terminatorLine(date) {
  return terminator(date, 2).points.map(([lon, lat], i) => {
    const p = project(lat, lon);
    return `${i ? 'L' : 'M'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
  }).join('');
}

/** Analog face: white by day, black by night, accent second hand. */
function buildFace() {
  const s = svgEl('svg', { viewBox: '-50 -50 100 100', class: 'clk-face', 'aria-hidden': 'true' });
  s.append(svgEl('circle', { r: 48, class: 'clk-face-dial' }));
  for (let i = 1; i <= 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    const t = svgEl('text', { x: (Math.sin(a) * 37).toFixed(2), y: (-Math.cos(a) * 37 + 4.6).toFixed(2), class: 'clk-face-num' });
    t.textContent = String(i);
    s.append(t);
  }
  const hand = (cls, len, w, tail) => svgEl('line', { x1: 0, y1: tail, x2: 0, y2: -len, class: cls, 'stroke-width': w, 'stroke-linecap': 'round' });
  s.append(hand('clk-face-hour', 22, 3.4, 0), hand('clk-face-min', 34, 2.6, 0), hand('clk-face-sec', 38, 0.9, 8));
  s.append(svgEl('circle', { r: 2.2, class: 'clk-face-pin' }), svgEl('circle', { r: 1, class: 'clk-face-pin-sec' }));
  return s;
}

function setFace(face, tz, lat, lon, now) {
  const { h: hr, m, s } = zonedClock(tz, now);
  const [hh, mm, ss] = face.querySelectorAll('line');
  hh.setAttribute('transform', `rotate(${((hr % 12) + m / 60) * 30})`);
  mm.setAttribute('transform', `rotate(${(m + s / 60) * 6})`);
  ss.setAttribute('transform', `rotate(${Math.floor(s) * 6})`);
  face.classList.toggle('clk-face-night', !isDaylight(lat, lon, now));
}

export function createWorldClock(ctx) {
  const el = h('div.clk-view.clk-world');
  const mapWrap = h('div.clk-map');
  const map = svgEl('svg', { viewBox: `${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`, preserveAspectRatio: 'xMidYMid slice', class: 'clk-map-svg', 'aria-hidden': 'true' });
  map.append(svgEl('rect', { x: 0, y: 0, width: 360, height: 180, class: 'clk-map-ocean' }));
  map.append(svgEl('path', { d: LAND_PATH, class: 'clk-map-land' }));
  for (let lon = 30; lon < 360; lon += 30) map.append(svgEl('line', { x1: lon, y1: 0, x2: lon, y2: 180, class: 'clk-map-zone' }));
  const night = svgEl('path', { class: 'clk-map-night' });
  const line = svgEl('path', { class: 'clk-map-terminator' });
  map.append(night, line);
  const pins = h('div.clk-map-pins');
  mapWrap.append(map, pins);
  const cards = h('div.clk-cards', { role: 'list' });
  const empty = h('div.clk-empty.clk-world-empty', {}, h('div.clk-empty-icon', { html: ICONS.globe }), h('div.clk-empty-title', { text: 'No World Clocks' }));
  el.append(mapWrap, cards, empty);

  let faces = [];
  let pinEls = [];
  let timer = null;
  let ro = null;
  let lastMinute = -1;

  function placePins() {
    const r = mapWrap.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const scale = Math.max(r.width / VIEW.w, r.height / VIEW.h);
    const ox = (r.width - VIEW.w * scale) / 2, oy = (r.height - VIEW.h * scale) / 2;
    for (const { pin, lat, lon } of pinEls) {
      const p = project(lat, lon);
      pin.style.left = `${ox + (p.x - VIEW.x) * scale}px`;
      pin.style.top = `${oy + (p.y - VIEW.y) * scale}px`;
    }
  }

  function render() {
    const { worldClocks } = getState();
    const now = new Date();
    cards.replaceChildren();
    pins.replaceChildren();
    faces = [];
    pinEls = [];
    for (const c of worldClocks) {
      const face = buildFace();
      const title = h('div.clk-card-title');
      const sub = h('div.clk-card-sub');
      const sun = h('div.clk-card-sun');
      const remove = h('button.clk-card-remove', { type: 'button', title: 'Delete clock', 'aria-label': `Delete ${c.city}`, html: ICONS.close, on: { click: (e) => { e.stopPropagation(); removeClock(c.id); } } });
      const card = h('div.clk-card', { role: 'listitem', tabindex: '0' }, remove, face, title, sub, sun);
      card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        contextMenu(e.clientX, e.clientY, [{ label: 'Delete clock', danger: true, action: () => removeClock(c.id) }]);
      });
      card.addEventListener('keydown', (e) => { if (e.key === 'Delete' || e.key === 'Backspace') removeClock(c.id); });
      cards.append(card);
      const pinName = h('span.clk-pin-name', { text: c.city });
      const pinTime = h('span.clk-pin-time');
      const pin = h('div.clk-pin', {}, h('span.clk-pin-dot'), h('span.clk-pin-label', {}, pinName, pinTime));
      pins.append(pin);
      pinEls.push({ pin, lat: c.lat, lon: c.lon, pinTime });
      faces.push({ c, face, title, sub, sun, pinTime });
    }
    const none = !worldClocks.length;
    empty.hidden = !none;
    cards.hidden = none;
    lastMinute = -1;
    tick(now);
    placePins();
  }

  function tick(now = new Date()) {
    for (const f of faces) setFace(f.face, f.c.tz, f.c.lat, f.c.lon, now);
    const minute = Math.floor(now.getTime() / 60000);
    if (minute === lastMinute) return;
    lastMinute = minute;
    night.setAttribute('d', nightPath(now));
    line.setAttribute('d', terminatorLine(now));
    for (const f of faces) {
      const time = formatZoneTime(f.c.tz, now);
      f.title.textContent = `${f.c.city}, ${time}`;
      f.sub.textContent = `${relativeDay(f.c.tz, now)}, ${offsetLabel(f.c.tz, now)}`;
      f.pinTime.textContent = time;
      const { sunrise, sunset } = sunTimes(f.c.lat, f.c.lon, f.c.tz, now);
      f.sun.innerHTML = '';
      if (sunrise && sunset) {
        f.sun.append(
          h('span', { title: 'Sunrise', html: ICONS.sunrise }), h('span', { text: formatZoneTime(f.c.tz, sunrise) }),
          h('span.clk-sun-gap'),
          h('span', { title: 'Sunset', html: ICONS.sunset }), h('span', { text: formatZoneTime(f.c.tz, sunset) }),
        );
      }
    }
  }

  function removeClock(id) {
    update(s => { s.worldClocks = s.worldClocks.filter(c => c.id !== id); });
  }

  function addCity(row) {
    const [city, country, tz, lat, lon] = row;
    if (getState().worldClocks.length >= MAX_CLOCKS) {
      ctx.alert('Too many world clocks', 'Please delete a world clock before adding a new one.');
      return false;
    }
    update(s => { s.worldClocks.push({ id: uid('w'), city, country, tz, lat, lon }); });
    return true;
  }

  function chooseCity() {
    const input = h('input.clk-search-input', { type: 'search', placeholder: 'Search', 'aria-label': 'Search cities', autocomplete: 'off', spellcheck: false });
    const list = h('div.clk-city-list', { role: 'listbox' });
    let sheet = null;
    let active = 0;
    let rows = [];
    const draw = () => {
      const q = input.value.trim().toLowerCase();
      rows = q ? CITIES.filter(r => `${r[0]}, ${r[1]}`.toLowerCase().includes(q)) : CITIES;
      active = Math.min(active, Math.max(0, rows.length - 1));
      list.replaceChildren(...(rows.length ? rows.slice(0, 400).map((r, i) => h(`button.clk-city${i === active ? '.clk-active' : ''}`, {
        type: 'button', role: 'option', text: `${r[0]}, ${r[1]}`,
        on: { click: () => { if (addCity(r)) sheet.close(); } },
      })) : [h('div.clk-city-none', { text: 'No Results Found' })]));
    };
    input.addEventListener('input', () => { active = 0; draw(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = Math.max(0, Math.min(rows.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)));
        draw();
        list.children[active]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && rows[active]) {
        if (addCity(rows[active])) sheet.close();
      }
    });
    const content = h('div.clk-city-sheet', {},
      h('div.clk-city-head', {},
        h('button.clk-round-btn', { type: 'button', 'aria-label': 'Cancel', html: ICONS.close, on: { click: () => sheet.close() } }),
        h('div.clk-sheet-title', { text: 'Choose a City' })),
      h('label.clk-search', {}, h('span', { html: ICONS.search }), input),
      list);
    draw();
    sheet = openSheet(ctx.host, content, { className: 'clk-sheet-tall' });
    input.focus();
  }

  return {
    el,
    canAdd: true,
    addLabel: 'Add Clock',
    onAdd: chooseCity,
    render,
    mount() {
      render();
      timer = setInterval(() => tick(), 1000);
      ro = new ResizeObserver(placePins);
      ro.observe(mapWrap);
    },
    unmount() {
      clearInterval(timer);
      ro?.disconnect();
    },
  };
}
