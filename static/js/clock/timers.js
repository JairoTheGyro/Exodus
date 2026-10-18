/**
 * Clock — Timers tab. Left: active timers and Recents. Right: the hr/min/sec
 * picker for a new timer, or the selected timer's radial countdown.
 * Several timers can run at once, as in Clock.app.
 */

import { h, ICONS, contextMenu, soundSelect } from './dom.js';
import { getState, update } from './store.js';
import { startTimer, timerRemaining } from './engine.js';
import { formatCountdown, durationLabel, splitDuration, TIMER_PRESETS } from './time.js';

const NS = 'http://www.w3.org/2000/svg';
const RING_R = 47;
const RING_LEN = 2 * Math.PI * RING_R;

function recentText(r) {
  const d = durationLabel(r.duration);
  return r.label ? `${r.label} (${d})` : d;
}

/** Big "00:20:00" picker; each segment is a spin button (arrows, wheel, digits). */
function durationPicker(seconds, onChange) {
  const v = splitDuration(seconds);
  const limits = { h: 23, m: 59, s: 59 };
  const names = { h: 'hours', m: 'minutes', s: 'seconds' };
  const segs = {};
  const typed = { h: '', m: '', s: '' };
  const total = () => v.h * 3600 + v.m * 60 + v.s;
  const paint = () => {
    for (const k of ['h', 'm', 's']) {
      segs[k].textContent = String(v[k]).padStart(2, '0');
      segs[k].setAttribute('aria-valuenow', String(v[k]));
      segs[k].setAttribute('aria-valuetext', `${v[k]} ${names[k]}`);
    }
  };
  const order = ['h', 'm', 's'];
  for (const k of order) {
    const seg = h('span.clk-pick-seg', { tabindex: '0', role: 'spinbutton', 'aria-label': names[k], 'aria-valuemin': '0', 'aria-valuemax': String(limits[k]) });
    const set = (n) => { v[k] = (n + limits[k] + 1) % (limits[k] + 1); paint(); onChange(total()); };
    seg.addEventListener('wheel', (e) => { e.preventDefault(); typed[k] = ''; set(v[k] + (e.deltaY < 0 ? 1 : -1)); }, { passive: false });
    seg.addEventListener('focus', () => { typed[k] = ''; });
    seg.addEventListener('keydown', (e) => {
      const i = order.indexOf(k);
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); typed[k] = ''; set(v[k] + (e.key === 'ArrowUp' ? 1 : -1)); }
      else if (e.key === 'ArrowRight' && i < 2) { e.preventDefault(); segs[order[i + 1]].focus(); }
      else if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); segs[order[i - 1]].focus(); }
      else if (e.key === 'Backspace') { e.preventDefault(); typed[k] = ''; v[k] = 0; paint(); onChange(total()); }
      else if (/^\d$/.test(e.key)) {
        e.preventDefault();
        typed[k] = (typed[k] + e.key).slice(-2);
        let n = Number(typed[k]);
        if (n > limits[k]) { n = Number(e.key); typed[k] = e.key; }
        v[k] = n; paint(); onChange(total());
        if (typed[k].length === 2 && i < 2) segs[order[i + 1]].focus();
      }
    });
    segs[k] = seg;
  }
  paint();
  const el = h('div.clk-picker', {},
    h('div.clk-pick-labels', {}, h('span', { text: 'hr' }), h('span', { text: 'min' }), h('span', { text: 'sec' })),
    h('div.clk-pick-box', {}, segs.h, h('span.clk-pick-colon', { text: ':' }), segs.m, h('span.clk-pick-colon', { text: ':' }), segs.s));
  return { el, total, set: (secs) => { Object.assign(v, splitDuration(secs)); paint(); }, focus: () => segs.m.focus() };
}

export function createTimers(ctx) {
  const el = h('div.clk-view.clk-timers');
  const side = h('div.clk-timer-side', { role: 'list' });
  const main = h('div.clk-timer-main');
  el.append(side, main);

  let selected = null;     // active timer id, or null for the picker
  let adding = false;      // picker forced open by "+"
  let raf = 0;
  let live = [];           // { id, nodes to refresh each frame }
  let pickerState = null;

  const startNew = (duration, label, sound) => {
    if (!duration) return;
    let id = null;
    update(s => { id = startTimer(s, { duration, label, sound }).id; });
    selected = id;
    adding = false;
    ctx.rerender();
  };

  function pauseResume(id) {
    update(s => {
      const t = s.timers.find(x => x.id === id);
      if (!t) return;
      if (t.pausedRemaining != null) { t.endsAt = Date.now() + t.pausedRemaining * 1000; t.pausedRemaining = null; }
      else { t.pausedRemaining = timerRemaining(t); t.endsAt = null; }
    });
  }

  function cancel(id) {
    update(s => { s.timers = s.timers.filter(x => x.id !== id); });
  }

  function circleBtn(kind, label, onClick) {
    return h(`button.clk-circle.clk-circle-${kind}`, {
      type: 'button', 'aria-label': label, title: label, html: kind === 'pause' ? ICONS.pause : ICONS.play,
      on: { click: (e) => { e.stopPropagation(); onClick(); } },
    });
  }

  function renderSide(s) {
    side.replaceChildren();
    live = [];
    for (const t of s.timers) {
      const paused = t.pausedRemaining != null;
      const time = h('div.clk-tcard-time');
      const card = h(`div.clk-tcard${t.id === selected && !adding ? '.clk-selected' : ''}`, { role: 'listitem', tabindex: '0' },
        h('div.clk-tcard-text', {}, time, h('div.clk-tcard-sub', { text: t.label ? `${t.label} (${durationLabel(t.duration)})` : durationLabel(t.duration) })),
        paused ? circleBtn('resume', 'Resume', () => pauseResume(t.id)) : circleBtn('pause', 'Pause', () => pauseResume(t.id)));
      card.addEventListener('click', () => { selected = t.id; adding = false; ctx.rerender(); });
      card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        contextMenu(e.clientX, e.clientY, [
          { label: paused ? 'Resume' : 'Pause', action: () => pauseResume(t.id) },
          { label: 'Cancel', danger: true, action: () => cancel(t.id) },
        ]);
      });
      side.append(card);
      live.push({ t, time });
    }
    if (s.recentTimers.length) {
      side.append(h('div.clk-side-header', { text: 'Recents' }));
      for (const r of s.recentTimers) {
        const del = h('button.clk-recent-del', { type: 'button', title: 'Delete', 'aria-label': 'Delete recent timer', html: ICONS.trash,
          on: { click: (e) => { e.stopPropagation(); update(st => { st.recentTimers = st.recentTimers.filter(x => x !== r && !(x.duration === r.duration && x.label === r.label)); }); } } });
        const row = h('div.clk-recent', { role: 'listitem', tabindex: '0', title: 'Start' },
          h('div.clk-tcard-text', {}, h('div.clk-recent-time', { text: formatCountdown(r.duration) }), h('div.clk-tcard-sub', { text: recentText(r) })),
          del,
          circleBtn('start', 'Start', () => startNew(r.duration, r.label, r.sound)));
        row.addEventListener('click', () => {
          if (pickerState) { pickerState.picker.set(r.duration); pickerState.label.value = r.label || ''; pickerState.duration = r.duration; }
          selected = null; adding = true; ctx.rerender();
          update(st => { st.lastTimer = { duration: r.duration, label: r.label || '', sound: r.sound || st.lastTimer.sound }; });
        });
        row.addEventListener('dblclick', () => startNew(r.duration, r.label, r.sound));
        side.append(row);
      }
    }
    if (!s.timers.length && !s.recentTimers.length) {
      side.append(h('div.clk-side-empty', {}, h('div.clk-empty-icon', { html: ICONS.timer }), h('div.clk-side-empty-title', { text: 'No Timers' }), h('div.clk-side-empty-sub', { text: 'Active timers will appear here' })));
    }
  }

  function renderPicker(s) {
    const last = s.lastTimer;
    const state = { duration: last.duration || 1200, sound: last.sound || 'chime' };
    const startBtn = h('button.clk-pill.clk-pill-green', { type: 'button', text: 'Start' });
    const picker = durationPicker(state.duration, (secs) => { state.duration = secs; startBtn.disabled = !secs; });
    const label = h('input.clk-input.clk-timer-label', { type: 'text', placeholder: 'Timer', value: last.label || '', maxlength: '60', 'aria-label': 'Label' });
    const sound = soundSelect(state.sound, v => { state.sound = v; });
    const cancelBtn = h('button.clk-pill.clk-pill-grey', { type: 'button', text: 'Cancel', disabled: !s.timers.length,
      on: { click: () => { adding = false; selected = s.timers[0]?.id || null; ctx.rerender(); } } });
    startBtn.disabled = !state.duration;
    startBtn.addEventListener('click', () => startNew(state.duration, label.value.trim(), state.sound));
    label.addEventListener('keydown', (e) => { if (e.key === 'Enter') startBtn.click(); });
    pickerState = { picker, label, get duration() { return state.duration; }, set duration(v) { state.duration = v; } };
    main.replaceChildren(
      h('div.clk-timer-center', {}, picker.el, h('div.clk-timer-fields', {}, label, sound)),
      h('div.clk-bottom-bar', {}, cancelBtn, startBtn));
  }

  function renderActive(t) {
    pickerState = null;
    const paused = t.pausedRemaining != null;
    const ring = document.createElementNS(NS, 'svg');
    ring.setAttribute('viewBox', '0 0 100 100');
    ring.setAttribute('class', 'clk-ring');
    ring.innerHTML = `<circle cx="50" cy="50" r="${RING_R}" class="clk-ring-track"/><circle cx="50" cy="50" r="${RING_R}" class="clk-ring-bar" transform="rotate(-90 50 50)" stroke-dasharray="${RING_LEN}"/>`;
    const bar = ring.lastChild;
    const endText = h('span');
    const remaining = h('div.clk-ring-time');
    const label = h('input.clk-input.clk-timer-label', { type: 'text', placeholder: 'Timer', value: t.label || '', maxlength: '60', 'aria-label': 'Label' });
    label.addEventListener('change', () => update(s => { const x = s.timers.find(y => y.id === t.id); if (x) x.label = label.value.trim(); }));
    const sound = soundSelect(t.sound, v => update(s => { const x = s.timers.find(y => y.id === t.id); if (x) x.sound = v; }));
    const ringWrap = h(`div.clk-ring-wrap${paused ? '.clk-paused' : ''}`, {}, ring,
      h('div.clk-ring-inner', {}, h('div.clk-ring-end', {}, h('span', { html: ICONS.bell }), endText), remaining, h('div.clk-timer-fields', {}, label, sound)));
    main.replaceChildren(
      h('div.clk-timer-center', {}, ringWrap),
      h('div.clk-bottom-bar', {},
        h('button.clk-pill.clk-pill-grey', { type: 'button', text: 'Cancel', on: { click: () => cancel(t.id) } }),
        h(`button.clk-pill${paused ? '.clk-pill-green' : '.clk-pill-accent'}`, { type: 'button', text: paused ? 'Resume' : 'Pause', on: { click: () => pauseResume(t.id) } })));
    live.push({ t, time: remaining, bar, endText });
  }

  function frame() {
    const now = Date.now();
    for (const item of live) {
      const rem = timerRemaining(item.t, now);
      item.time.textContent = formatCountdown(rem);
      if (item.bar) item.bar.setAttribute('stroke-dashoffset', String(RING_LEN * (1 - rem / item.t.duration)));
      if (item.endText) {
        const end = new Date(now + rem * 1000);
        item.endText.textContent = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(end);
      }
    }
    raf = requestAnimationFrame(frame);
  }

  function render() {
    const s = getState();
    if (selected && !s.timers.some(t => t.id === selected)) selected = null;
    if (!selected && !adding && s.timers.length) selected = s.timers[0].id;
    renderSide(s);
    const active = s.timers.find(t => t.id === selected);
    if (active && !adding) renderActive(active); else renderPicker(s);
    cancelAnimationFrame(raf);
    frame();
  }

  function presetsMenu(x, y) {
    contextMenu(x, y, TIMER_PRESETS.map(p => ({
      label: `${p.number} ${p.unit === 'HR' ? (p.number === 1 ? 'hour' : 'hours') : 'min'}`,
      action: () => startNew(p.seconds, '', getState().lastTimer.sound),
    })));
  }

  return {
    el,
    canAdd: true,
    addLabel: 'Add Timer',
    onAdd() { selected = null; adding = true; render(); pickerState?.picker.focus(); },
    onAddMenu: presetsMenu,
    render,
    mount: render,
    unmount() { cancelAnimationFrame(raf); },
  };
}
