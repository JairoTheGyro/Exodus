/**
 * Clock — a recreation of the macOS Clock app as an Exodus tool window:
 * World Clock, Alarms, Stopwatch and Timers.
 *
 * Loaded lazily through panels.js (`loadPanel('clock')`). The window uses the
 * shared tool-window plumbing (modalManager for minimize/dock/restore,
 * windowDrag for move/resize/edge-dock) and only theme tokens for colour, so it
 * follows whichever Exodus theme is active. Saved state: ./clock/store.js.
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { h, ICONS, closeTopSheet, openSheet, ensureClockCss } from './clock/dom.js';
import { getState, update, subscribe, hasPendingWork } from './clock/store.js';
import { startEngine } from './clock/engine.js';
import { createWorldClock } from './clock/worldClock.js';
import { createAlarms } from './clock/alarms.js';
import { createStopwatch } from './clock/stopwatch.js';
import { createTimers } from './clock/timers.js';

const MODAL_ID = 'clock-modal';
const TABS = [
  { id: 'world', label: 'World Clock', make: createWorldClock },
  { id: 'alarms', label: 'Alarms', make: createAlarms },
  { id: 'stopwatch', label: 'Stopwatch', make: createStopwatch },
  { id: 'timers', label: 'Timers', make: createTimers },
];
// Same rail/sidebar wiring every other tool window uses for its dock badge.
const SIDEBAR_BTN_ID = 'tool-clock-btn';
const RAIL_BTN_ID = 'rail-clock';
const DOCK_ICON = 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2';

let modal = null;
let content = null;
let body = null;
let tabButtons = {};
let addBtn = null;
let views = {};
let current = null;
let open = false;
let unsubscribe = null;

function alertSheet(title, message) {
  let sheet = null;
  sheet = openSheet(content, h('div.clk-message', {},
    h('div.clk-sheet-title', { text: title }),
    h('p', { text: message }),
    h('div.clk-sheet-actions', {}, h('span.clk-spacer'), h('button.clk-btn.clk-accent.clk-primary', { type: 'button', text: 'OK', on: { click: () => sheet.close() } }))));
}

function selectTab(id, { persist = true } = {}) {
  const tab = TABS.find(t => t.id === id) || TABS[0];
  if (current === tab.id && body.firstChild === views[tab.id]?.el) return;
  if (current && views[current]) views[current].unmount();
  current = tab.id;
  for (const t of TABS) {
    const on = t.id === tab.id;
    tabButtons[t.id].classList.toggle('clk-on', on);
    tabButtons[t.id].setAttribute('aria-selected', String(on));
    tabButtons[t.id].tabIndex = on ? 0 : -1;
  }
  const view = views[tab.id];
  body.replaceChildren(view.el);
  addBtn.hidden = !view.canAdd;
  addBtn.title = view.addLabel || 'Add';
  addBtn.setAttribute('aria-label', view.addLabel || 'Add');
  view.mount();
  if (persist && getState().tab !== tab.id) update(s => { s.tab = tab.id; });
}

function stepTab(delta) {
  const i = TABS.findIndex(t => t.id === current);
  selectTab(TABS[(i + delta + TABS.length) % TABS.length].id);
}

function onKeydown(e) {
  if (!open || !modal || modal.classList.contains('hidden')) return;
  // A Clock sheet closes before the window does (ui.js closes the hovered
  // window on Escape, so this listens on window, ahead of it).
  if (e.key === 'Escape' && closeTopSheet(content)) {
    e.preventDefault();
    e.stopImmediatePropagation();
    return;
  }
  if (!modal.contains(document.activeElement) && document.activeElement !== document.body) return;
  const t = e.target;
  const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable || t.getAttribute?.('role') === 'spinbutton');
  // ⌘→ / ⌘← cycle tabs (MTATabBarController key commands); Ctrl on Windows/Linux.
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && (e.key === 'ArrowRight' || e.key === 'ArrowLeft') && !typing) {
    e.preventDefault();
    stepTab(e.key === 'ArrowRight' ? 1 : -1);
  }
}

function registerWindow() {
  Modals.register(MODAL_ID, {
    railBtnId: document.getElementById(RAIL_BTN_ID) ? RAIL_BTN_ID : undefined,
    sidebarBtnId: SIDEBAR_BTN_ID,
    label: 'Clock',
    icon: DOCK_ICON,
    closeFn: doClose,
    restoreFn: () => {
      open = true;
      views[current]?.unmount();
      views[current]?.mount();
    },
  });
}

function buildModal() {
  ensureClockCss();
  modal = h(`div#${MODAL_ID}.modal`, { style: { display: 'none' } });
  const tablist = h('div.clk-tabs', { role: 'tablist', 'aria-label': 'Clock sections' });
  for (const t of TABS) {
    const b = h('button.clk-tab', { type: 'button', role: 'tab', text: t.label, on: { click: () => selectTab(t.id) } });
    b.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        stepTab(e.key === 'ArrowRight' ? 1 : -1);
        tabButtons[current].focus();
      }
    });
    tabButtons[t.id] = b;
    tablist.append(b);
  }
  addBtn = h('button.clk-add', { type: 'button', html: ICONS.plus, on: { click: () => views[current]?.onAdd?.() } });
  addBtn.addEventListener('contextmenu', (e) => {
    const view = views[current];
    if (!view?.onAddMenu) return;
    e.preventDefault();
    view.onAddMenu(e.clientX, e.clientY);
  });
  const closeBtn = h('button.close-btn', { type: 'button', title: 'Close', 'aria-label': 'Close Clock', text: '✖', on: { click: closeClock } });
  const header = h('div.modal-header.clk-header', {},
    h('h4', { html: `${ICONS.clock}<span>Clock</span>` }),
    tablist,
    addBtn,
    closeBtn);
  body = h('div.clk-body');
  content = h('div.modal-content.clk-content', { role: 'region', 'aria-label': 'Clock' }, header, body);
  modal.append(content);
  document.body.append(modal);
  // Register before the app.js observer sees the new .modal, so it skips its
  // legacy "_" button and the modalManager chip/minimize flow is used instead.
  registerWindow();
  Modals.injectMinimizeButton(modal, MODAL_ID);
  makeWindowDraggable(modal, { content, header });

  const ctx = {
    host: content,
    rerender: () => views[current]?.render(),
    alert: alertSheet,
  };
  for (const t of TABS) views[t.id] = t.make(ctx);
  // window capture runs before ui.js's document-level Escape handler.
  window.addEventListener('keydown', onKeydown, true);
}

export function openClock(tab) {
  startEngine();
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    open = true;
    if (tab) selectTab(tab);
    return;
  }
  if (!modal) buildModal();
  if (!Modals.isRegistered(MODAL_ID)) registerWindow();
  open = true;
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';
  current = null;
  selectTab(tab || getState().tab || 'world', { persist: false });
  unsubscribe?.();
  unsubscribe = subscribe(() => { if (open) views[current]?.render(); });
}

function doClose() {
  open = false;
  unsubscribe?.();
  unsubscribe = null;
  if (current && views[current]) views[current].unmount();
  if (content) content.querySelectorAll(':scope > .clk-sheet-backdrop').forEach(n => n.remove());
  if (modal) {
    modal.style.display = 'none';
    modal.classList.add('hidden');
  }
}

export function closeClock() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else doClose();
}

export function isClockOpen() {
  return open && !Modals.isMinimized(MODAL_ID);
}

/** Sidebar/rail click: closed → open, open → close, minimized → restore. */
export function toggleClock() {
  if (Modals.isMinimized(MODAL_ID)) { Modals.restore(MODAL_ID); open = true; return; }
  if (isClockOpen()) closeClock(); else openClock();
}

/** Start ringing saved alarms/timers without opening the window. */
export function startClockBackground() {
  if (hasPendingWork()) startEngine();
}

export default { openClock, closeClock, isClockOpen, toggleClock, startClockBackground };
