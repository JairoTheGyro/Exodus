// Look hooks for built-in apps. An app window carries data-look="<look>";
// js/apps/looks.css maps each look to a few shared settings (font, button
// shape, control and card rounding, title-bar spacing) that the app's own CSS
// reads with its native values as the fallback. Which look applies: the app's
// own choice, else the workspace-wide choice, else DEFAULT_LOOK.

export const LOOKS = Object.freeze({
  apple: 'Apple-like',
  exodus: 'Exodus',
});
export const DEFAULT_LOOK = 'apple';
export const LOOK_STORAGE_KEY = 'exodus-app-looks-v1';
export const LOOK_EVENT = 'exodus:app-look-changed';
const CSS_HREF = '/static/js/apps/looks.css';

export function readLookPrefs(storage = globalThis.localStorage) {
  try {
    const raw = JSON.parse(storage?.getItem(LOOK_STORAGE_KEY) || 'null');
    if (raw && typeof raw === 'object') {
      return { workspace: typeof raw.workspace === 'string' ? raw.workspace : null, apps: raw.apps && typeof raw.apps === 'object' ? { ...raw.apps } : {} };
    }
  } catch (_) {}
  return { workspace: null, apps: {} };
}

export function resolveLook(appId, prefs = readLookPrefs()) {
  for (const look of [prefs.apps?.[appId], prefs.workspace]) {
    if (look && Object.hasOwn(LOOKS, look)) return look;
  }
  return DEFAULT_LOOK;
}

let following = false;
// Another tab changed the choice: follow it. Registered on first use, not import.
function followOtherTabs() {
  if (following) return;
  following = true;
  globalThis.addEventListener?.('storage', e => { if (e.key === LOOK_STORAGE_KEY) refreshLooks(); });
}

function ensureLookCss(doc) {
  if (doc.querySelector('link[data-app-looks-css]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS_HREF;
  link.dataset.appLooksCss = '1';
  doc.head.append(link);
}

/** Mark an app window with its resolved look; call when the window is built. */
export function applyLook(el, appId, { storage, doc = el.ownerDocument || document } = {}) {
  ensureLookCss(doc);
  followOtherTabs();
  el.dataset.appLookId = appId;
  el.dataset.look = resolveLook(appId, readLookPrefs(storage));
  return el.dataset.look;
}

/**
 * Choose a look for one app (`app`) or for every app (`app` omitted). Pass
 * `look: null` to clear that choice. Open windows update immediately.
 */
export function setLook({ app = null, look }, { storage = globalThis.localStorage, doc = globalThis.document } = {}) {
  if (look !== null && !Object.hasOwn(LOOKS, look)) throw new TypeError(`Unknown look "${look}"`);
  const prefs = readLookPrefs(storage);
  if (app) { if (look) prefs.apps[app] = look; else delete prefs.apps[app]; }
  else prefs.workspace = look;
  try { storage?.setItem(LOOK_STORAGE_KEY, JSON.stringify(prefs)); } catch (_) {}
  refreshLooks({ storage, doc });
  doc?.dispatchEvent?.(new CustomEvent(LOOK_EVENT, { detail: { app, look } }));
  return prefs;
}

export function refreshLooks({ storage, doc = globalThis.document } = {}) {
  const prefs = readLookPrefs(storage);
  for (const el of doc?.querySelectorAll?.('[data-app-look-id]') || []) {
    el.dataset.look = resolveLook(el.dataset.appLookId, prefs);
  }
}

