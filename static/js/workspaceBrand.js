// Exodus: the workspace's own name and logo (set by an admin in Settings →
// System → Workspace name and logo, stored by routes/workspace_brand_routes.py).
//
// The name replaces the product name "Exodus" in the app's own text: the tab
// title, the sidebar, Home, the welcome screen, Settings and the sign-in page.
// It never touches what people wrote (chats, documents, notes, email), form
// fields, or anything marked data-keep-product-name (the License Tracker's legal
// credit). The logo replaces the Exodus mark everywhere js/settings/brand.js
// draws it. With nothing customised this module changes nothing.

export const DEFAULT_NAME = 'Exodus';
export const BRAND_EVENT = 'exodus:workspace-brand-changed';
const CACHE_KEY = 'exodus-workspace-brand-v1';
const PRODUCT = /\bExodus\b/g;
const TEXT_ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt'];
// App areas whose text is the app's own wording, not people's content.
const SCOPES = ['#sidebar', '#workspace-home', '#welcome-screen', '#settings-modal', '[data-workspace-brand-scope]'];
const SKIP = 'script, style, textarea, input, select, [contenteditable=""], [contenteditable="true"], [data-keep-product-name]';
// Resolved next to this module so a sub-path install (e.g. /exodus/) works.
function apiPath(suffix = '') {
  try { return new URL(`../../api/workspace/brand${suffix}`, import.meta.url).pathname; }
  catch (_) { return `/api/workspace/brand${suffix}`; }
}

let brand = readCache();
const originalText = new WeakMap();
const originalAttrs = new WeakMap();
const observed = new WeakSet();
let titleObserver = null;
// Text watchers start only once a custom name has been used in this page, so
// an uncustomised Exodus does no extra work.
let textActive = false;

function readCache() {
  try {
    const saved = JSON.parse(globalThis.localStorage?.getItem(CACHE_KEY) || 'null');
    if (saved && typeof saved === 'object') return saved;
  } catch (_) {}
  return null;
}

function writeCache(value) {
  try { globalThis.localStorage?.setItem(CACHE_KEY, JSON.stringify(value)); } catch (_) {}
}

/** The name to show for the product. */
export function workspaceName() {
  const name = typeof brand?.name === 'string' ? brand.name.trim() : '';
  return name || DEFAULT_NAME;
}

/** Same-origin URL of the custom logo, or null to keep the Exodus mark. */
export function workspaceLogoUrl() {
  if (!brand?.has_logo) return null;
  return `${apiPath('/logo')}?v=${encodeURIComponent(String(brand.version || 0))}`;
}

/** Replace the product name in a piece of the app's own wording. */
export function brandText(text) {
  const name = workspaceName();
  return name === DEFAULT_NAME || typeof text !== 'string' ? text : text.replace(PRODUCT, name);
}

function skipped(node) {
  const element = node.nodeType === 1 ? node : node.parentElement;
  return !element || !!element.closest(SKIP);
}

function rewriteText(node) {
  if (skipped(node)) return;
  let original = originalText.get(node);
  // A node the app re-rendered (or that never contained the name) starts over.
  if (original === undefined || node.data !== original.shown) {
    if (!PRODUCT.test(node.data)) { PRODUCT.lastIndex = 0; return; }
    PRODUCT.lastIndex = 0;
    original = { source: node.data, shown: node.data };
  }
  const shown = brandText(original.source);
  original.shown = shown;
  originalText.set(node, original);
  if (node.data !== shown) node.data = shown;
}

function rewriteAttributes(element) {
  if (skipped(element)) return;
  let saved = originalAttrs.get(element);
  for (const attr of TEXT_ATTRIBUTES) {
    const value = element.getAttribute(attr);
    if (value == null) continue;
    const entry = saved?.[attr];
    let source = value;
    if (entry && value === entry.shown) source = entry.source;
    else if (!PRODUCT.test(value)) { PRODUCT.lastIndex = 0; continue; }
    PRODUCT.lastIndex = 0;
    const shown = brandText(source);
    saved = saved || {};
    saved[attr] = { source, shown };
    if (value !== shown) element.setAttribute(attr, shown);
  }
  if (saved) originalAttrs.set(element, saved);
}

function rewriteTree(root) {
  if (root.nodeType === 3) return rewriteText(root);
  if (root.nodeType !== 1) return;
  rewriteAttributes(root);
  const doc = root.ownerDocument;
  const walker = doc.createTreeWalker(root, 4 | 1);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === 3) rewriteText(node);
    else rewriteAttributes(node);
  }
}

function observe(root) {
  if (observed.has(root) || typeof MutationObserver === 'undefined') return;
  observed.add(root);
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') rewriteText(record.target);
      else if (record.type === 'attributes') rewriteAttributes(record.target);
      else for (const node of record.addedNodes) rewriteTree(node);
    }
  }).observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: TEXT_ATTRIBUTES });
}

function brandTitle(doc) {
  const title = doc.querySelector('title');
  if (!title) return;
  rewriteText(title.firstChild || title.appendChild(doc.createTextNode(doc.title)));
  if (!titleObserver && typeof MutationObserver !== 'undefined') {
    titleObserver = new MutationObserver(() => { if (title.firstChild) rewriteText(title.firstChild); });
    titleObserver.observe(title, { childList: true, characterData: true, subtree: true });
  }
}

// The name under the home-screen icon on iPhones (Android reads the manifest).
function brandHomeScreenName(doc) {
  const meta = doc.querySelector('meta[name="apple-mobile-web-app-title"]');
  if (meta) meta.setAttribute('content', workspaceName().slice(0, 30));
}

function brandManifest(doc) {
  brandHomeScreenName(doc);
  const link = doc.querySelector('link[rel="manifest"]');
  if (!link || link.dataset.routeManifest === 'true' || typeof Blob === 'undefined') return;
  if (!link.dataset.defaultHref) link.dataset.defaultHref = link.getAttribute('href') || '';
  const name = workspaceName();
  const logo = workspaceLogoUrl();
  if (name === DEFAULT_NAME && !logo) {
    if (link.dataset.defaultHref) link.setAttribute('href', link.dataset.defaultHref);
    return;
  }
  const origin = doc.location?.origin || '';
  const manifest = {
    name, short_name: name.slice(0, 12), start_url: '/', scope: '/', display: 'standalone',
    background_color: '#0e0e10', theme_color: '#0e0e10',
    icons: logo ? [{ src: origin + logo, sizes: '512x512', type: 'image/png', purpose: 'any' }]
      : [{ src: `${origin}/static/icons/exodus.png`, sizes: '512x512', type: 'image/png', purpose: 'any' }],
  };
  link.setAttribute('href', URL.createObjectURL(new Blob([JSON.stringify(manifest)], { type: 'application/manifest+json' })));
}

/** Apply the current name to the page; safe to call repeatedly. */
export function applyWorkspaceBrand(doc = document) {
  brandTitle(doc);
  if (workspaceName() !== DEFAULT_NAME) textActive = true;
  if (textActive) for (const selector of SCOPES) {
    for (const root of doc.querySelectorAll(selector)) {
      rewriteTree(root);
      observe(root);
    }
  }
  brandManifest(doc);
}

function setBrand(next, doc) {
  const changed = JSON.stringify(next) !== JSON.stringify(brand);
  brand = next;
  writeCache(next);
  if (changed) {
    applyWorkspaceBrand(doc);
    doc.dispatchEvent(new CustomEvent(BRAND_EVENT, { detail: { name: workspaceName(), logo: workspaceLogoUrl() } }));
  }
}

/** Fetch the saved brand and apply it (and remember it for the next load). */
export async function refreshWorkspaceBrand({ doc = document, fetchImpl = globalThis.fetch } = {}) {
  try {
    const response = await fetchImpl(apiPath(), { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) return brand;
    const data = await response.json();
    setBrand({ name: data.custom_name ? data.name : '', has_logo: !!data.has_logo, version: data.version || 0 }, doc);
  } catch (_) {
    // Offline or not reachable: keep the remembered brand.
  }
  return brand;
}

let started = false;
/** Apply the remembered brand at once, then refresh it from the server. */
export function startWorkspaceBrand(doc = document) {
  if (started) return;
  started = true;
  const run = () => { applyWorkspaceBrand(doc); refreshWorkspaceBrand({ doc }); };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', run, { once: true });
  else run();
  // Home and Settings content are created after load: pick up new areas, at
  // most once per frame, and only while a custom name is in use.
  if (typeof MutationObserver !== 'undefined' && doc.body) {
    let queued = false;
    new MutationObserver(() => {
      if (!textActive || queued) return;
      queued = true;
      (globalThis.requestAnimationFrame || setTimeout)(() => {
        queued = false;
        for (const selector of SCOPES) {
          for (const root of doc.querySelectorAll(selector)) {
            if (!observed.has(root)) { rewriteTree(root); observe(root); }
          }
        }
      });
    }).observe(doc.body, { childList: true, subtree: true });
  }
}

// ── Admin side (Settings) ───────────────────────────────────────────────

async function send(suffix, init) {
  const response = await fetch(apiPath(suffix), { credentials: 'same-origin', ...init });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || (response.status === 403 ? 'Admin access is required.' : 'Could not save.'));
  setBrand({ name: data.custom_name ? data.name : '', has_logo: !!data.has_logo, version: data.version || 0 }, document);
  return data;
}

export function saveWorkspaceName(name) {
  return send('', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
}

export function uploadWorkspaceLogo(file) {
  const body = new FormData();
  body.append('file', file);
  return send('/logo', { method: 'POST', body });
}

export function removeWorkspaceLogo() {
  return send('/logo', { method: 'DELETE' });
}
