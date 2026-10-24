// Settings → Appearance → App look: choose how built-in app windows look,
// for every app at once or for one app. Rows come from the app registry, so a
// newly registered app appears here without touching this file. The choice is
// stored by js/apps/looks.js and applied to open windows immediately.
import { APPS } from '../apps/registry.js';
import { LOOKS, DEFAULT_LOOK, LOOK_EVENT, LOOK_STORAGE_KEY, readLookPrefs, setLook } from '../apps/looks.js';

const SAME_AS_ALL = '';

function option(doc, value, label, selected) {
  const el = doc.createElement('option');
  el.value = value;
  el.textContent = label;
  if (selected) el.selected = true;
  return el;
}

function row(doc, { scope, name, hint, icon, options, value }) {
  const label = doc.createElement('label');
  label.className = 'vis-row app-look-row';
  const iconWrap = doc.createElement('span');
  iconWrap.className = 'vis-icon';
  // Icons are fixed SVG bodies from the app registry (never user input).
  iconWrap.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg>`;
  const text = doc.createElement('span');
  text.className = 'vis-label';
  text.textContent = hint ? `${name} ` : name;
  if (hint) {
    const small = doc.createElement('span');
    small.className = 'vis-hint';
    small.textContent = hint;
    text.append(small);
  }
  const select = doc.createElement('select');
  select.className = 'theme-fd-select app-look-select';
  select.dataset.appLookScope = scope;
  select.setAttribute('aria-label', `Look for ${scope === 'all' ? 'all apps' : name}`);
  for (const [v, l] of options) select.append(option(doc, v, l, v === value));
  label.append(iconWrap, text, select);
  return label;
}

const ALL_APPS_ICON = '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>';

/**
 * Render the picker into `container` (replacing its contents). Safe to call
 * again; it re-reads the saved choice each time.
 */
export function renderAppLookPicker(container, { apps = APPS, storage = globalThis.localStorage, doc = container.ownerDocument || document } = {}) {
  const prefs = readLookPrefs(storage);
  const lookOptions = Object.entries(LOOKS);
  const workspace = Object.hasOwn(LOOKS, prefs.workspace || '') ? prefs.workspace : DEFAULT_LOOK;
  const rows = [row(doc, {
    scope: 'all', name: 'All apps', hint: 'Default for every built-in app', icon: ALL_APPS_ICON,
    options: lookOptions, value: workspace,
  })];
  for (const app of apps) {
    const own = Object.hasOwn(LOOKS, prefs.apps?.[app.id] || '') ? prefs.apps[app.id] : SAME_AS_ALL;
    rows.push(row(doc, {
      scope: app.id, name: app.name, icon: app.icon, value: own,
      options: [[SAME_AS_ALL, `Default (${LOOKS[workspace]})`], ...lookOptions],
    }));
  }
  container.replaceChildren(...rows);
  return rows.length;
}

/**
 * Render once and keep in sync: changing a dropdown saves the look; a change
 * made elsewhere (another tab, or code calling setLook) re-renders.
 */
export function mountAppLookPicker(container, { apps = APPS, storage = globalThis.localStorage, doc = container.ownerDocument || document } = {}) {
  renderAppLookPicker(container, { apps, storage, doc });
  if (container.dataset.appLookBound) return;
  container.dataset.appLookBound = '1';
  let saving = false;
  container.addEventListener('change', event => {
    const select = event.target;
    if (!select?.classList?.contains('app-look-select')) return;
    const scope = select.dataset.appLookScope;
    saving = true;
    try {
      setLook({ app: scope === 'all' ? null : scope, look: select.value || null }, { storage, doc });
    } finally {
      saving = false;
    }
    // Only the per-app "Default (…)" labels can change after a choice here.
    if (scope === 'all') renderAppLookPicker(container, { apps, storage, doc });
  });
  const rerender = () => { if (!saving) renderAppLookPicker(container, { apps, storage, doc }); };
  doc.addEventListener?.(LOOK_EVENT, rerender);
  globalThis.addEventListener?.('storage', e => { if (e.key === LOOK_STORAGE_KEY) rerender(); });
}
