/**
 * Clock — Alarms tab: alarm cards with on/off switches and the Add / Edit
 * Alarm sheet (time, AM/PM, repeat days, label, sound, snooze).
 */

import { h, ICONS, openSheet, contextMenu, soundSelect, toggle } from './dom.js';
import { getState, update, uid } from './store.js';
import { scheduleAlarm } from './engine.js';
import { DEFAULT_SOUND } from './sound.js';
import { alarmTimeParts, alarmDetail, uses12Hour, WEEKDAY_LETTERS } from './time.js';

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const SNOOZE_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];

function askNotificationPermission() {
  try {
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => {});
  } catch (_) {}
}

/**
 * Time field with hour and minute segments, like the macOS date picker:
 * click a segment, then type digits or use the arrow keys.
 */
function timeField(state, twelve, onChange) {
  const hourSeg = h('span.clk-seg', { tabindex: '0', role: 'spinbutton', 'aria-label': 'Hour' });
  const minSeg = h('span.clk-seg', { tabindex: '0', role: 'spinbutton', 'aria-label': 'Minute' });
  const box = h('div.clk-timefield', {}, hourSeg, h('span.clk-seg-colon', { text: ':' }), minSeg);
  let typed = '';
  const paint = () => {
    const shown = twelve ? (state.hour % 12 || 12) : state.hour;
    hourSeg.textContent = twelve ? String(shown) : String(shown).padStart(2, '0');
    minSeg.textContent = String(state.minute).padStart(2, '0');
    hourSeg.setAttribute('aria-valuenow', String(state.hour));
    minSeg.setAttribute('aria-valuenow', String(state.minute));
  };
  const bump = (seg, delta) => {
    if (seg === hourSeg) state.hour = (state.hour + delta + 24) % 24;
    else state.minute = (state.minute + delta + 60) % 60;
    paint(); onChange();
  };
  const keys = (seg) => (e) => {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); typed = ''; bump(seg, e.key === 'ArrowUp' ? 1 : -1); return; }
    if (e.key === 'ArrowRight' && seg === hourSeg) { e.preventDefault(); minSeg.focus(); return; }
    if (e.key === 'ArrowLeft' && seg === minSeg) { e.preventDefault(); hourSeg.focus(); return; }
    if (twelve && seg === hourSeg && /^[ap]$/i.test(e.key)) {
      e.preventDefault();
      const pm = e.key.toLowerCase() === 'p';
      state.hour = (state.hour % 12) + (pm ? 12 : 0);
      paint(); onChange(); return;
    }
    if (!/^\d$/.test(e.key)) return;
    e.preventDefault();
    typed = (typed + e.key).slice(-2);
    let n = Number(typed);
    if (seg === hourSeg) {
      if (twelve) {
        if (n > 12 || n === 0) { n = Number(e.key) || 12; typed = e.key; }
        const pm = state.hour >= 12;
        state.hour = (n % 12) + (pm ? 12 : 0);
      } else {
        if (n > 23) { n = Number(e.key); typed = e.key; }
        state.hour = n;
      }
      if (typed.length === 2 || Number(typed) > (twelve ? 1 : 2)) { typed = ''; minSeg.focus(); }
    } else {
      if (n > 59) { n = Number(e.key); typed = e.key; }
      state.minute = n;
      if (typed.length === 2) typed = '';
    }
    paint(); onChange();
  };
  for (const seg of [hourSeg, minSeg]) {
    seg.addEventListener('keydown', keys(seg));
    seg.addEventListener('focus', () => { typed = ''; });
    seg.addEventListener('mousedown', (e) => { e.preventDefault(); seg.focus(); });
    seg.addEventListener('wheel', (e) => { e.preventDefault(); bump(seg, e.deltaY < 0 ? 1 : -1); }, { passive: false });
  }
  paint();
  return { el: box, paint, focus: () => hourSeg.focus() };
}

function openAlarmSheet(host, existing) {
  const now = new Date();
  const draft = existing ? { ...existing, days: [...(existing.days || [])] } : {
    id: uid('a'), hour: now.getHours(), minute: now.getMinutes(), days: [], label: '',
    sound: DEFAULT_SOUND, snooze: true, snoozeMinutes: 9, enabled: true,
  };
  const twelve = uses12Hour();
  let sheet = null;

  const am = h('button.clk-seg-btn', { type: 'button', text: 'AM' });
  const pm = h('button.clk-seg-btn', { type: 'button', text: 'PM' });
  const syncPeriod = () => { am.classList.toggle('clk-on', draft.hour < 12); pm.classList.toggle('clk-on', draft.hour >= 12); };
  const tf = timeField(draft, twelve, syncPeriod);
  am.addEventListener('click', () => { if (draft.hour >= 12) draft.hour -= 12; tf.paint(); syncPeriod(); });
  pm.addEventListener('click', () => { if (draft.hour < 12) draft.hour += 12; tf.paint(); syncPeriod(); });
  syncPeriod();

  const dayBtns = WEEKDAY_LETTERS.map((letter, d) => {
    const b = h('button.clk-day', { type: 'button', text: letter, title: DAY_NAMES[d], 'aria-label': DAY_NAMES[d], 'aria-pressed': String(draft.days.includes(d)) });
    b.classList.toggle('clk-on', draft.days.includes(d));
    b.addEventListener('click', () => {
      draft.days = draft.days.includes(d) ? draft.days.filter(x => x !== d) : [...draft.days, d].sort();
      b.classList.toggle('clk-on', draft.days.includes(d));
      b.setAttribute('aria-pressed', String(draft.days.includes(d)));
    });
    return b;
  });

  const label = h('input.clk-input', { type: 'text', placeholder: 'Alarm', value: draft.label || '', maxlength: '60', 'aria-label': 'Label' });
  const sound = soundSelect(draft.sound, v => { draft.sound = v; });
  const snoozeBox = h('input', { type: 'checkbox', checked: draft.snooze !== false });
  const snoozeSel = h('select.clk-select.clk-select-sm', { 'aria-label': 'Snooze Duration' });
  for (const n of SNOOZE_CHOICES) snoozeSel.append(new Option(`${n} min`, String(n), false, n === (draft.snoozeMinutes || 9)));
  const syncSnooze = () => { snoozeSel.disabled = !snoozeBox.checked; };
  snoozeBox.addEventListener('change', syncSnooze);
  syncSnooze();

  const save = () => {
    draft.label = label.value.trim();
    draft.snooze = snoozeBox.checked;
    draft.snoozeMinutes = Number(snoozeSel.value) || 9;
    draft.enabled = true;
    draft.snoozeUntil = null;
    scheduleAlarm(draft);
    update(s => {
      const i = s.alarms.findIndex(a => a.id === draft.id);
      if (i >= 0) s.alarms[i] = draft; else s.alarms.push(draft);
    });
    askNotificationPermission();
    sheet.close();
  };
  label.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });

  const row = (title, ...control) => h('div.clk-form-row', {}, h('div.clk-form-label', { text: title }), h('div.clk-form-control', {}, ...control));
  const content = h('form.clk-alarm-sheet', { on: { submit: (e) => { e.preventDefault(); save(); } } },
    h('div.clk-alarm-time', {}, tf.el, twelve ? h('div.clk-seg-group', {}, am, pm) : null),
    row('Repeat:', h('div.clk-days', {}, ...dayBtns)),
    h('div.clk-form-gap'),
    row('Label:', label),
    row('Sound:', sound),
    row('', h('label.clk-check', {}, snoozeBox, h('span', { text: 'Snooze' }))),
    row('Snooze Duration:', snoozeSel),
    h('div.clk-sheet-actions', {},
      existing ? h('button.clk-btn.clk-danger-text', { type: 'button', text: 'Delete Alarm', on: { click: () => { update(s => { s.alarms = s.alarms.filter(a => a.id !== draft.id); }); sheet.close(); } } }) : null,
      h('span.clk-spacer'),
      h('button.clk-btn', { type: 'button', text: 'Cancel', on: { click: () => sheet.close() } }),
      h('button.clk-btn.clk-accent.clk-primary', { type: 'submit', text: 'Save' })));
  sheet = openSheet(host, content);
  requestAnimationFrame(() => tf.focus());
}

export function createAlarms(ctx) {
  const el = h('div.clk-view.clk-alarms');
  const grid = h('div.clk-alarm-grid', { role: 'list' });
  const empty = h('div.clk-empty', {}, h('div.clk-empty-icon.clk-empty-alarm', { html: ICONS.alarm }), h('div.clk-empty-title', { text: 'No Alarms' }));
  el.append(grid, empty);
  const twelve = uses12Hour();

  function render() {
    const alarms = [...getState().alarms].sort((a, b) => (a.hour * 60 + a.minute) - (b.hour * 60 + b.minute));
    grid.replaceChildren();
    for (const a of alarms) {
      const parts = alarmTimeParts(a.hour, a.minute, twelve);
      const sw = toggle(a.enabled, (on) => update(s => {
        const x = s.alarms.find(y => y.id === a.id);
        if (!x) return;
        x.enabled = on;
        x.snoozeUntil = null;
        scheduleAlarm(x);
      }), `${parts.time} ${parts.period} alarm`);
      const snoozing = a.enabled && a.snoozeUntil && a.snoozeUntil > Date.now();
      const card = h(`div.clk-alarm${a.enabled ? '' : '.clk-off'}`, { role: 'listitem', tabindex: '0', title: 'Edit alarm' },
        h('div.clk-alarm-main', {},
          h('div.clk-alarm-clock', {}, h('span.clk-alarm-hm', { text: parts.time }), parts.period ? h('span.clk-alarm-ampm', { text: parts.period }) : null),
          h('div.clk-alarm-detail', { text: alarmDetail(a) + (snoozing ? ' • Snoozed' : '') })),
        sw);
      card.addEventListener('click', () => openAlarmSheet(ctx.host, a));
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') openAlarmSheet(ctx.host, a);
        if (e.key === 'Delete' || e.key === 'Backspace') update(s => { s.alarms = s.alarms.filter(x => x.id !== a.id); });
      });
      card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        contextMenu(e.clientX, e.clientY, [
          { label: 'Edit alarm…', action: () => openAlarmSheet(ctx.host, a) },
          { label: 'Delete alarm', danger: true, action: () => update(s => { s.alarms = s.alarms.filter(x => x.id !== a.id); }) },
        ]);
      });
      grid.append(card);
    }
    empty.hidden = alarms.length > 0;
    grid.hidden = alarms.length === 0;
  }

  return {
    el,
    canAdd: true,
    addLabel: 'Add Alarm',
    onAdd: () => openAlarmSheet(ctx.host, null),
    render,
    mount: render,
    unmount() {},
  };
}
