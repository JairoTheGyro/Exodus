/**
 * Clock — background engine. Rings alarms and finishes timers while Exodus is
 * open in this browser, whether or not the Clock window is showing.
 *
 * Browsers only run this while an Exodus tab is open; there is no OS-level
 * wake-up like Clock.app's. An alarm that came due while every tab was closed
 * rings on return only if it is less than MISSED_GRACE_MS late.
 */

import { getState, update, uid, pushRecentTimer } from './store.js';
import { nextAlarmDate, alarmTimeParts, uses12Hour, formatCountdown } from './time.js';
import { loop } from './sound.js';
import { topPortalZ } from '../toolWindowZOrder.js';
import { h, ensureClockCss } from './dom.js';

const MISSED_GRACE_MS = 5 * 60000;
const RING_LIMIT_MS = 3 * 60000;
const CLAIM_KEY = 'odysseus-clock-rang';
let started = false;

/**
 * First Exodus tab to see an alert due claims it, so two open tabs do not
 * both ring. Best effort: localStorage has no atomic compare-and-set.
 */
function claimAlert(key) {
  try {
    const now = Date.now();
    const seen = JSON.parse(localStorage.getItem(CLAIM_KEY) || '{}');
    if (seen[key]) return false;
    for (const k of Object.keys(seen)) if (now - seen[k] > 3600000) delete seen[k];
    seen[key] = now;
    localStorage.setItem(CLAIM_KEY, JSON.stringify(seen));
    return true;
  } catch (_) {
    return true;
  }
}

/** Recompute when each enabled alarm rings next. */
export function scheduleAlarm(alarm, from = new Date()) {
  const next = alarm.enabled ? nextAlarmDate(alarm, from) : null;
  alarm.nextAt = next ? next.getTime() : null;
  if (!alarm.enabled) alarm.snoozeUntil = null;
  return alarm;
}

export function startTimer(s, { duration, label = '', sound = 'chime' }) {
  const t = { id: uid('t'), duration, label, sound, endsAt: Date.now() + duration * 1000, pausedRemaining: null };
  s.timers.unshift(t);
  pushRecentTimer(s, { duration, label, sound });
  s.lastTimer = { duration, label, sound };
  return t;
}

export function timerRemaining(t, now = Date.now()) {
  if (t.pausedRemaining != null) return t.pausedRemaining;
  return Math.max(0, (t.endsAt - now) / 1000);
}

function tick() {
  const now = Date.now();
  const s = getState();
  const dueAlarms = [];
  const dueTimers = [];
  for (const a of s.alarms) {
    if (!a.enabled) continue;
    const at = a.snoozeUntil || a.nextAt;
    if (!at || now < at) continue;
    dueAlarms.push({ alarm: a, late: now - at, key: `a:${a.id}:${at}` });
  }
  for (const t of s.timers) {
    if (t.pausedRemaining == null && t.endsAt && now >= t.endsAt) dueTimers.push({ timer: t, late: now - t.endsAt, key: `t:${t.id}:${t.endsAt}` });
  }
  if (!dueAlarms.length && !dueTimers.length) return;
  update(st => {
    for (const { alarm } of dueAlarms) {
      const a = st.alarms.find(x => x.id === alarm.id);
      if (!a) continue;
      a.snoozeUntil = null;
      if (!a.days?.length) a.enabled = false;
      scheduleAlarm(a, new Date(now + 1000));
    }
    const ids = new Set(dueTimers.map(d => d.timer.id));
    st.timers = st.timers.filter(t => !ids.has(t.id));
  });
  for (const { alarm, late, key } of dueAlarms) if (late < MISSED_GRACE_MS && claimAlert(key)) ringAlarm(alarm);
  for (const { timer, late, key } of dueTimers) if (late < MISSED_GRACE_MS && claimAlert(key)) ringTimer(timer);
}

// ── Alert windows ────────────────────────────────────────────────────────

function notify(title, body) {
  try {
    if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
      new Notification(title, { body, tag: `clock-${title}` });
    }
  } catch (_) {}
}

function showAlert({ title, subtitle, sound, buttons }) {
  ensureClockCss();
  const stopSound = sound && sound !== 'none' ? loop(sound) : () => {};
  const limit = setTimeout(stopSound, RING_LIMIT_MS);
  const host = document.getElementById('clk-alerts') || document.body.appendChild(h('div#clk-alerts.clk-alerts'));
  host.style.zIndex = String(topPortalZ() + 5);
  const card = h('div.clk-alert', { role: 'alertdialog', 'aria-label': title },
    h('div.clk-alert-icon', { html: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>' }),
    h('div.clk-alert-text', {}, h('div.clk-alert-title', { text: title }), subtitle ? h('div.clk-alert-sub', { text: subtitle }) : null),
    h('div.clk-alert-actions'));
  const dismiss = () => { clearTimeout(limit); stopSound(); card.remove(); if (!host.children.length) host.remove(); };
  buttons.forEach((b, i) => card.lastChild.append(h(`button.clk-btn${i === buttons.length - 1 ? '.clk-accent' : ''}`, {
    type: 'button', text: b.label, on: { click: () => { dismiss(); b.action?.(); } },
  })));
  host.append(card);
  card.querySelector('.clk-accent')?.focus();
}

function ringAlarm(alarm) {
  const parts = alarmTimeParts(alarm.hour, alarm.minute, uses12Hour());
  const title = (alarm.label || '').trim() || 'Alarm';
  const time = `${parts.time}${parts.period ? ' ' + parts.period : ''}`;
  notify(title, time);
  const buttons = [];
  if (alarm.snooze !== false) {
    buttons.push({
      label: 'Snooze', action: () => update(st => {
        const a = st.alarms.find(x => x.id === alarm.id);
        if (!a) return;
        a.enabled = true;
        a.snoozeUntil = Date.now() + (a.snoozeMinutes || 9) * 60000;
      }),
    });
  }
  buttons.push({ label: 'Stop' });
  showAlert({ title, subtitle: time, sound: alarm.sound, buttons });
}

function ringTimer(timer) {
  const title = (timer.label || '').trim() || 'Timer Done';
  notify(title, formatCountdown(timer.duration));
  showAlert({
    title,
    subtitle: (timer.label || '').trim() ? 'Timer Done' : formatCountdown(timer.duration),
    sound: timer.sound,
    buttons: [
      { label: 'Repeat', action: () => update(st => { startTimer(st, timer); }) },
      { label: 'Stop' },
    ],
  });
}

/** Start the once-per-page ticker. Safe to call repeatedly. */
export function startEngine() {
  if (started) return;
  started = true;
  update(s => { s.alarms.forEach(a => { if (a.enabled && !a.nextAt && !a.snoozeUntil) scheduleAlarm(a); }); });
  setInterval(tick, 500);
  document.addEventListener('visibilitychange', tick);
  tick();
}
