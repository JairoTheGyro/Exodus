// Exodus built-in apps. Adding an app means one entry here plus the app's own
// folder (see docs/APP_RECREATION.md). The launcher builds each Tools-menu
// entry from this list, js/panels.js lazy-loads `load`, and js/apps/looks.js
// styles the window the app opens. Nothing here runs on import.

const CLOCK_STORE_KEY = 'odysseus-clock-v1';

// Saved alarms and running timers must ring even when the Clock window was
// never opened this session. Reads only the stored state, not the module.
function clockHasPendingWork(storage = globalThis.localStorage) {
  try {
    const saved = JSON.parse(storage?.getItem(CLOCK_STORE_KEY) || 'null');
    return !!saved && ((saved.alarms || []).some(a => a && a.enabled) || (saved.timers || []).some(t => t && t.endsAt));
  } catch (_) {
    return false;
  }
}

export const APPS = Object.freeze([
  Object.freeze({
    id: 'clock',
    name: 'Clock',
    description: 'world clock, alarms, stopwatch and timers',
    menuAfter: 'tool-calendar-btn',
    icon: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    // No import-time side effects: the alarm/timer ticker only starts when
    // openClock() or startClockBackground() is called.
    load: () => import('../clock.js'),
    toggle: 'toggleClock',
    background: Object.freeze({ pending: clockHasPendingWork, start: 'startClockBackground' }),
  }),
  Object.freeze({
    id: 'calculator',
    name: 'Calculator',
    description: 'basic, scientific and programmer, with unit conversion',
    menuAfter: 'tool-skills-btn',
    icon: '<rect x="5" y="2" width="14" height="20" rx="2"/><rect x="8" y="5" width="8" height="4" rx="0.5"/><path d="M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 17h.01M12 17h.01M15.5 17h.01"/>',
    // No import-time side effects: its window and keyboard listeners are
    // created on the first openCalculator() call.
    load: () => import('../calculator/index.js'),
    toggle: 'toggleCalculator',
  }),
]);

export function appById(id) {
  return APPS.find(app => app.id === id) || null;
}

/** Lazy loaders for js/panels.js, keyed by app id. */
export function appLoaders() {
  return Object.fromEntries(APPS.map(app => [app.id, app.load]));
}
