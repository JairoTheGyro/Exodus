// Builds the Tools-menu entry for every registered app and wires it to open
// the app's window. Called once by app.js; the registry is the only list.
import { APPS } from './registry.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

export function menuEntry(app, doc = document) {
  const label = `${app.name} — ${app.description}`;
  const item = doc.createElement('div');
  item.className = 'list-item';
  item.id = `tool-${app.id}-btn`;
  item.title = label;
  item.setAttribute('aria-label', label);
  item.dataset.app = app.id;
  const svg = doc.createElementNS(SVG_NS, 'svg');
  for (const [k, v] of Object.entries({
    width: '14', height: '14', viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    style: 'flex-shrink:0;opacity:0.5;', 'aria-hidden': 'true',
  })) svg.setAttribute(k, v);
  svg.innerHTML = app.icon;
  const name = doc.createElement('span');
  name.className = 'grow';
  name.textContent = app.name;
  item.append(svg, name);
  return item;
}

/**
 * Add each app to the Tools menu and start any background work it has
 * pending. `loadPanel(id)` resolves to the app module (js/panels.js).
 */
export function installApps({ loadPanel, toast, doc = document, apps = APPS, schedule = idle } = {}) {
  const installed = [];
  for (const app of apps) {
    let entry = doc.getElementById(`tool-${app.id}-btn`);
    if (!entry) {
      const anchor = doc.getElementById(app.menuAfter);
      if (!anchor) continue;
      entry = menuEntry(app, doc);
      anchor.after(entry);
    }
    entry.addEventListener('click', async () => {
      try {
        const mod = await loadPanel(app.id);
        mod[app.toggle]();
      } catch (e) {
        console.error(`${app.name} failed to load`, e);
        toast?.(`${app.name} could not load. Check your connection and try again.`);
      }
    });
    if (app.background) {
      let pending = false;
      try { pending = app.background.pending(); } catch (_) {}
      if (pending) {
        schedule(() => loadPanel(app.id)
          .then(mod => mod[app.background.start]())
          .catch(e => console.warn(`${app.name} background start failed`, e)));
      }
    }
    installed.push(app.id);
  }
  return installed;
}

function idle(fn) {
  if (typeof requestIdleCallback === 'function') requestIdleCallback(fn, { timeout: 4000 });
  else setTimeout(fn, 1500);
}
