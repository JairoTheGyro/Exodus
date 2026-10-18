/**
 * Clock — saved state (world clocks, alarms, timers, stopwatch, last tab).
 *
 * Lives in this browser's localStorage under one key, like the calendar cache.
 * Running timers and the stopwatch are stored as wall-clock timestamps, so they
 * keep counting across reloads and while the Clock window is closed.
 */

export const STORE_KEY = 'odysseus-clock-v1';
const MAX_RECENT_TIMERS = 20;
const listeners = new Set();

function defaults() {
  return {
    tab: 'world',
    worldClocks: [
      { id: 'w-cupertino', city: 'Cupertino', country: 'U.S.A.', tz: 'America/Los_Angeles', lat: 37.32, lon: -122.03 },
      { id: 'w-newyork', city: 'New York', country: 'U.S.A.', tz: 'America/New_York', lat: 40.71, lon: -74.01 },
    ],
    alarms: [],
    timers: [],          // active: { id, duration, label, sound, endsAt, pausedRemaining }
    recentTimers: [],    // { duration, label, sound }
    lastTimer: { duration: 1200, label: '', sound: 'chime' },
    stopwatch: { startedAt: null, accumulated: 0, laps: [], analog: false },
  };
}

let state = null;

function read() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return defaults();
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return defaults();
    const base = defaults();
    return {
      ...base, ...saved,
      stopwatch: { ...base.stopwatch, ...(saved.stopwatch || {}) },
      lastTimer: { ...base.lastTimer, ...(saved.lastTimer || {}) },
      worldClocks: Array.isArray(saved.worldClocks) ? saved.worldClocks : base.worldClocks,
      alarms: Array.isArray(saved.alarms) ? saved.alarms : [],
      timers: Array.isArray(saved.timers) ? saved.timers : [],
      recentTimers: Array.isArray(saved.recentTimers) ? saved.recentTimers : [],
    };
  } catch (_) {
    return defaults();
  }
}

export function getState() {
  if (!state) state = read();
  return state;
}

/** Apply `fn(state)` then persist and notify subscribers. */
export function update(fn) {
  const s = getState();
  fn(s);
  try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (_) {}
  listeners.forEach(cb => { try { cb(s); } catch (e) { console.warn('clock listener failed', e); } });
  return s;
}

export function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Pick up changes another Exodus tab saved. */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== STORE_KEY) return;
    state = read();
    listeners.forEach(cb => { try { cb(state); } catch (_) {} });
  });
}

export const uid = (prefix) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

/** Remember a started timer at the top of Recents (no duplicates). */
export function pushRecentTimer(s, { duration, label, sound }) {
  const key = `${duration}|${(label || '').trim()}`;
  s.recentTimers = [
    { duration, label: (label || '').trim(), sound },
    ...s.recentTimers.filter(r => `${r.duration}|${(r.label || '').trim()}` !== key),
  ].slice(0, MAX_RECENT_TIMERS);
}

/** True when something should keep ticking in the background. */
export function hasPendingWork(s = getState()) {
  return s.alarms.some(a => a.enabled) || s.timers.some(t => t.endsAt);
}
