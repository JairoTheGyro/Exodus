// Workspace look: how the whole Exodus interface looks (fonts, corners,
// shadows, window buttons) and which launcher it uses. Independent of the
// colour theme, so any theme works with any look. Built-in app windows keep
// their own, separate choice (js/apps/looks.js, Settings → App look).
//
// <html data-ui-look="apple"> switches css/91-look-apple.css on. The inline
// script at the top of index.html sets it before the first paint, so there is
// no flash; this module keeps it in sync afterwards.

export const WORKSPACE_LOOKS = Object.freeze({
  exodus: 'Exodus',
  apple: 'Apple-like',
});
export const DEFAULT_WORKSPACE_LOOK = 'exodus';
// The launcher each look uses. Windows- and Material-like looks will add a
// Start menu and an app drawer here.
export const LAUNCHER_FOR_LOOK = Object.freeze({ exodus: null, apple: 'dock' });
export const DOCK_MODES = Object.freeze({
  auto: 'Show when the pointer reaches the bottom',
  always: 'Always show',
  off: 'Hide',
});
export const DEFAULT_DOCK_MODE = 'auto';
export const WORKSPACE_LOOK_KEY = 'exodus-workspace-look-v1';
export const WORKSPACE_LOOK_EVENT = 'exodus:workspace-look-changed';

export function readWorkspaceLook(storage = globalThis.localStorage) {
  let raw = null;
  try { raw = JSON.parse(storage?.getItem(WORKSPACE_LOOK_KEY) || 'null'); } catch (_) {}
  const look = raw && Object.hasOwn(WORKSPACE_LOOKS, raw.look) ? raw.look : DEFAULT_WORKSPACE_LOOK;
  const dock = raw && Object.hasOwn(DOCK_MODES, raw.dock) ? raw.dock : DEFAULT_DOCK_MODE;
  return { look, dock };
}

/** Put the saved look on <html>; returns it. */
export function applyWorkspaceLook({ storage, doc = globalThis.document } = {}) {
  const prefs = readWorkspaceLook(storage);
  const root = doc?.documentElement;
  if (root) {
    if (prefs.look === DEFAULT_WORKSPACE_LOOK) delete root.dataset.uiLook;
    else root.dataset.uiLook = prefs.look;
    root.dataset.dockMode = prefs.dock;
  }
  return prefs;
}

/** Save a change to the look and/or the Dock mode, then apply it everywhere. */
export function setWorkspaceLook(change, { storage = globalThis.localStorage, doc = globalThis.document } = {}) {
  const next = { ...readWorkspaceLook(storage) };
  if (change.look !== undefined) {
    if (!Object.hasOwn(WORKSPACE_LOOKS, change.look)) throw new TypeError(`Unknown look "${change.look}"`);
    next.look = change.look;
  }
  if (change.dock !== undefined) {
    if (!Object.hasOwn(DOCK_MODES, change.dock)) throw new TypeError(`Unknown Dock mode "${change.dock}"`);
    next.dock = change.dock;
  }
  try { storage?.setItem(WORKSPACE_LOOK_KEY, JSON.stringify(next)); } catch (_) {}
  applyWorkspaceLook({ storage, doc });
  doc?.dispatchEvent?.(new CustomEvent(WORKSPACE_LOOK_EVENT, { detail: next }));
  return next;
}

/**
 * The Apple-like look swaps only the default monospace interface font for the
 * system font. A font chosen on purpose in Themes (sans, serif, OpenDyslexic
 * or a custom one) stays. theme.js sets --font-family on <html>.
 */
export function syncFontFlag(doc = globalThis.document) {
  const root = doc?.documentElement;
  if (!root) return null;
  const family = root.style.getPropertyValue('--font-family').trim();
  const flag = !family || family.startsWith("'Fira Code'") ? 'mono' : 'chosen';
  if (root.dataset.uiFont !== flag) root.dataset.uiFont = flag;
  return flag;
}

let following = false;
/** Follow changes made in another tab and font changes. Safe to call more than once. */
export function followWorkspaceLook({ storage, doc = globalThis.document } = {}) {
  if (following) return;
  following = true;
  syncFontFlag(doc);
  if (doc?.documentElement && globalThis.MutationObserver) {
    new MutationObserver(() => syncFontFlag(doc)).observe(doc.documentElement, { attributes: true, attributeFilter: ['style'] });
  }
  globalThis.addEventListener?.('storage', e => {
    if (e.key !== WORKSPACE_LOOK_KEY) return;
    const prefs = applyWorkspaceLook({ storage, doc });
    doc?.dispatchEvent?.(new CustomEvent(WORKSPACE_LOOK_EVENT, { detail: prefs }));
  });
}
