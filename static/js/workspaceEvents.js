// One shared stream of invalidations. Existing APIs retain all permissions.
// This bus never carries note contents, subjects, credentials or owner names.
const listeners = new Map();
const topics = new Set(['notes','documents','calendar','inbox','profile','goals','focus','team','scratchpad','reconnect']);
let stream = null, started = false;

export function subscribe(topic, callback) {
  if (!topics.has(topic) || typeof callback !== 'function') throw new TypeError('Invalid workspace subscription');
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic).add(callback);
  return () => { listeners.get(topic)?.delete(callback); };
}

export function publish(topic, detail = {}) {
  if (!topics.has(topic)) return;
  for (const callback of listeners.get(topic) || []) {
    try { Promise.resolve(callback(detail)).catch(() => {}); } catch { /* One widget cannot break others. */ }
  }
}

function connect() {
  if (!started || stream || document.hidden || typeof EventSource === 'undefined') return;
  const current = new EventSource('/api/workspace/events');
  stream = current;
  current.addEventListener('ready', () => { if (stream === current) publish('reconnect'); });
  current.addEventListener('change', event => {
    if (stream !== current) return;
    try { publish(JSON.parse(event.data).topic); } catch { /* Ignore invalid transport data. */ }
  });
  // EventSource owns reconnect/backoff. ready triggers a full refresh, so
  // missed invalidations and app restarts never need a replayed data log.
}

function disconnect() { stream?.close(); stream = null; }
function visibility() { if (document.hidden) disconnect(); else { connect(); if (started) publish('reconnect'); } }
function online() { if (started) { disconnect(); connect(); } }
function focused() { if (started && !document.hidden) publish('reconnect'); }
function calendarChanged() { publish('calendar'); }

export function start() {
  if (started) return;
  started = true;
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('online', online);
  window.addEventListener('focus', focused);
  window.addEventListener('offline', disconnect);
  window.addEventListener('pagehide', disconnect);
  window.addEventListener('pageshow', connect);
  window.addEventListener('calendar-changed', calendarChanged);
  window.addEventListener('calendar-refresh', calendarChanged);
  connect();
}

export function stop() {
  started = false;
  disconnect();
  document.removeEventListener('visibilitychange', visibility);
  window.removeEventListener('online', online);
  window.removeEventListener('focus', focused);
  window.removeEventListener('offline', disconnect);
  window.removeEventListener('pagehide', disconnect);
  window.removeEventListener('pageshow', connect);
  window.removeEventListener('calendar-changed', calendarChanged);
  window.removeEventListener('calendar-refresh', calendarChanged);
}
