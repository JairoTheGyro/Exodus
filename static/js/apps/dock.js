// The Dock: the Apple-like look's app launcher. A row of icons at the bottom
// of the screen for the main sections and every built-in app (from the app
// registry), with a dot under each one whose window is open. It works by
// pressing the same sidebar button a person would, so every section opens
// exactly as it always does, and anything hidden in Settings → Appearance →
// Sidebar (or by AI-Free mode) is left out.
import { APPS } from './registry.js';
import { LAUNCHER_FOR_LOOK, WORKSPACE_LOOK_EVENT, readWorkspaceLook } from './workspaceLook.js';

const SVG = (body) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

// Main sections, left to right. `button` is the element a person would click;
// `window` is the window it opens (ids from js/modalManager.js). Icons are
// Exodus's own line icons; where the sidebar button has one, that is used.
export const DOCK_SECTIONS = Object.freeze([
  { id: 'home', name: 'Home', button: 'home-sidebar-button', open: doc => doc.body.classList.contains('home-active'),
    icon: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>' },
  { id: 'chat', name: 'New chat', button: 'sidebar-new-chat-btn',
    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>' },
  { id: 'email', name: 'Email', button: 'email-section-title', window: 'email-lib-modal' },
  { id: 'calendar', name: 'Calendar', button: 'tool-calendar-btn', window: 'calendar-modal' },
  { id: 'notes', name: 'Notes', button: 'tool-notes-btn', window: 'notes-panel' },
  { id: 'library', name: 'Library', button: 'tool-library-btn', window: 'doclib-modal' },
  { id: 'tasks', name: 'Automations', button: 'tool-tasks-btn', window: 'tasks-modal' },
].map(Object.freeze));

export const DOCK_SETTINGS = Object.freeze({
  id: 'settings', name: 'Settings', button: 'user-bar-settings', window: 'settings-modal',
  icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
});

/** The Dock's entries: sections, then built-in apps, then Settings. */
export function dockItems(apps = APPS) {
  return [
    ...DOCK_SECTIONS.map(s => ({ ...s, group: 'sections' })),
    ...apps.map(app => ({ id: app.id, name: app.name, button: `tool-${app.id}-btn`, app: app.id, icon: app.icon, group: 'apps' })),
    { ...DOCK_SETTINGS, group: 'system' },
  ];
}

function isShown(el, win = globalThis) {
  if (!el || el.hidden || el.classList?.contains('hidden')) return false;
  if (el.style?.display === 'none') return false;
  try { return win.getComputedStyle(el).display !== 'none'; } catch (_) { return true; }
}

/** Is this entry's window open (or minimized)? */
export function isOpen(item, doc = globalThis.document, win = globalThis) {
  if (item.open) return !!item.open(doc);
  const el = item.window ? doc.getElementById(item.window)
    : item.app ? doc.querySelector(`[data-app-look-id="${item.app}"]`) : null;
  if (!el) return false;
  if (el.classList.contains('modal-minimized')) return true;
  return isShown(el, win);
}

function iconFor(item, doc) {
  if (item.icon) return SVG(item.icon);
  const svg = doc.getElementById(item.button)?.querySelector('svg');
  if (svg) {
    const copy = svg.cloneNode(true);
    for (const attr of ['width', 'height', 'style', 'class']) copy.removeAttribute(attr);
    copy.setAttribute('aria-hidden', 'true');
    return copy.outerHTML;
  }
  return SVG('<rect x="4" y="4" width="16" height="16" rx="3"/>');
}

/** Build the Dock's markup for the entries a person can use right now. */
export function renderDock(nav, { apps = APPS, doc = nav.ownerDocument || document, win = globalThis } = {}) {
  const list = doc.createElement('ul');
  list.className = 'app-dock-list';
  let lastGroup = null;
  for (const item of dockItems(apps)) {
    const target = doc.getElementById(item.button);
    if (!isShown(target, win)) continue;
    if (lastGroup && item.group !== lastGroup) {
      const sep = doc.createElement('li');
      sep.className = 'app-dock-separator';
      sep.setAttribute('aria-hidden', 'true');
      list.append(sep);
    }
    lastGroup = item.group;
    const li = doc.createElement('li');
    li.className = 'app-dock-item';
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'app-dock-button';
    button.dataset.dockItem = item.id;
    button.setAttribute('aria-label', item.name);
    button.innerHTML = `<span class="app-dock-icon">${iconFor(item, doc)}</span><span class="app-dock-label" aria-hidden="true"></span><span class="app-dock-dot" aria-hidden="true"></span>`;
    button.querySelector('.app-dock-label').textContent = item.name;
    li.append(button);
    list.append(li);
  }
  nav.replaceChildren(list);
  return list.children.length;
}

/** Mark the entries whose windows are open. */
export function updateRunning(nav, { apps = APPS, doc = nav.ownerDocument || document, win = globalThis } = {}) {
  const items = new Map(dockItems(apps).map(i => [i.id, i]));
  for (const button of nav.querySelectorAll('[data-dock-item]')) {
    const open = isOpen(items.get(button.dataset.dockItem), doc, win);
    button.classList.toggle('is-open', open);
    button.setAttribute('aria-label', open ? `${items.get(button.dataset.dockItem).name} (open)` : items.get(button.dataset.dockItem).name);
  }
}

/**
 * Create the Dock and keep it in step with the look, hidden sections and open
 * windows. It only shows while the Apple-like look is on and the Dock mode
 * isn't "off". Returns the <nav> element.
 */
export function mountDock({ apps = APPS, doc = globalThis.document, win = globalThis, storage } = {}) {
  let nav = doc.getElementById('app-dock');
  if (nav) return nav;
  nav = doc.createElement('nav');
  nav.id = 'app-dock';
  nav.className = 'app-dock';
  nav.setAttribute('aria-label', 'Dock');
  const hotspot = doc.createElement('div');
  hotspot.className = 'app-dock-hotspot';
  hotspot.setAttribute('aria-hidden', 'true');
  doc.body.append(hotspot, nav);

  const ids = new Set(dockItems(apps).map(i => i.button));
  const sync = () => {
    const { look, dock } = readWorkspaceLook(storage);
    const active = LAUNCHER_FOR_LOOK[look] === 'dock' && dock !== 'off';
    nav.hidden = !active;
    hotspot.hidden = !active || dock !== 'auto';
    if (!active) return;
    renderDock(nav, { apps, doc, win });
    updateRunning(nav, { apps, doc, win });
  };

  let queued = false;
  const later = () => {
    if (queued) return;
    queued = true;
    (win.requestAnimationFrame || setTimeout)(() => { queued = false; if (!nav.hidden) updateRunning(nav, { apps, doc, win }); });
  };

  nav.addEventListener('click', event => {
    const id = event.target.closest?.('[data-dock-item]')?.dataset.dockItem;
    const item = dockItems(apps).find(i => i.id === id);
    if (item) doc.getElementById(item.button)?.click();
    later();
  });

  // Auto-hide: shown while the pointer is at the bottom edge, over the Dock,
  // or while a Dock button has keyboard focus.
  let hideTimer = null;
  const reveal = () => { clearTimeout(hideTimer); nav.classList.add('is-revealed'); };
  const conceal = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => nav.classList.remove('is-revealed'), 500); };
  hotspot.addEventListener('pointerenter', reveal);
  nav.addEventListener('pointerenter', reveal);
  nav.addEventListener('pointerleave', conceal);
  nav.addEventListener('focusin', reveal);
  nav.addEventListener('focusout', conceal);

  // Windows open and close by toggling classes and styles on the page. A
  // sidebar button hidden or shown in Settings, or added after load (Home,
  // the built-in apps), changes which entries the Dock has.
  const selector = [...ids].map(id => `#${id}`).join(',');
  const touchesEntries = m => ids.has(m.target.id)
    || [...(m.addedNodes || []), ...(m.removedNodes || [])].some(n => n.nodeType === 1 && (n.matches?.(selector) || !!n.querySelector?.(selector)));
  new win.MutationObserver(mutations => {
    if (mutations.some(m => m.target !== nav && !nav.contains(m.target) && touchesEntries(m))) sync();
    else later();
  }).observe(doc.body, { subtree: true, attributes: true, childList: true, attributeFilter: ['class', 'style', 'hidden'] });
  // AI-Free mode is switched on <html> and hides the AI-only sections.
  new win.MutationObserver(sync).observe(doc.documentElement, { attributes: true, attributeFilter: ['data-workspace-mode'] });
  doc.addEventListener(WORKSPACE_LOOK_EVENT, sync);
  sync();
  return nav;
}
