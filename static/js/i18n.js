// Exodus translations. English is the source language: catalogs map the exact
// English wording to a translation (static/locales/<lang>.json), so anything not
// translated yet simply stays English. The app's own text is translated where
// it appears (the sign-in card, Home and Settings for wave 1), including text
// rendered later; people's own content and form fields are never touched.
//
// Each person's choice is saved with their account (/api/prefs/language) and
// in this browser; before sign-in the browser's saved choice or language is used.
import { BRAND_EVENT, brandText, workspaceName, DEFAULT_NAME } from './workspaceBrand.js';

export const LANGUAGES = Object.freeze({ en: 'English', 'es-419': 'Español (Latinoamérica)' });
export const DEFAULT_LANGUAGE = 'en';
export const LANGUAGE_EVENT = 'exodus:language-changed';
const STORAGE_KEY = 'exodus-language';
const TEXT_ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt'];
// Wave 1: sign-in ([data-i18n-scope]), Home and Settings.
const SCOPES = ['#workspace-home', '#settings-modal', '[data-i18n-scope]'];
// Dropdown choices are the app's wording and are translated; their values never change.
const SKIP = 'script, style, textarea, input, code, pre, [contenteditable=""], [contenteditable="true"], [data-i18n-skip]';

let language = detectLanguage();
let catalog = null;          // { messages: Map, patterns: [{ regex, names, target }] }
let catalogLanguage = null;
const nodeState = new WeakMap();
const attrState = new WeakMap();
const observed = new WeakSet();
let active = false;          // becomes true once a non-English language is used

function supported(lang) { return Object.hasOwn(LANGUAGES, lang || '') ? lang : null; }

function detectLanguage() {
  let saved = null;
  try { saved = supported(globalThis.localStorage?.getItem(STORAGE_KEY)); } catch (_) {}
  if (saved) return saved;
  const browser = [...(globalThis.navigator?.languages || []), globalThis.navigator?.language].filter(Boolean);
  return browser.some(l => /^es\b/i.test(l)) ? 'es-419' : DEFAULT_LANGUAGE;
}

/** Fill a <select> with the available languages (each named in itself). */
export function fillLanguageSelect(select) {
  if (!select) return;
  if (!select.options.length) {
    for (const [code, label] of Object.entries(LANGUAGES)) {
      const option = document.createElement('option');
      option.value = code;
      option.textContent = label;
      option.lang = code;
      select.append(option);
    }
  }
  select.value = currentLanguage();
}

/** The chosen language code, e.g. 'en' or 'es-419'. */
export function currentLanguage() { return language; }

/** Locale for Intl/toLocale* calls; undefined keeps the browser default for English. */
export function currentLocale() { return language === DEFAULT_LANGUAGE ? undefined : language; }

function catalogUrl(lang) {
  try { return new URL(`../locales/${lang}.json`, import.meta.url).pathname; }
  catch (_) { return `/static/locales/${lang}.json`; }
}

export function compileCatalog(data) {
  const messages = new Map(Object.entries(data?.messages || {}));
  const patterns = (data?.patterns || []).map(([source, target]) => {
    const names = [];
    const regex = new RegExp('^' + source.split(/(\{[a-z_]+\})/i).map(part => {
      const m = /^\{([a-z_]+)\}$/i.exec(part);
      if (m) { names.push(m[1]); return '(.+?)'; }
      return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('') + '$');
    return { regex, names, target };
  });
  return { messages, patterns };
}

async function loadCatalog(lang, fetchImpl = globalThis.fetch) {
  if (lang === DEFAULT_LANGUAGE) { catalog = null; catalogLanguage = lang; return; }
  if (catalogLanguage === lang && catalog) return;
  try {
    const response = await fetchImpl(catalogUrl(lang), { cache: 'no-cache' });
    catalog = response.ok ? compileCatalog(await response.json()) : null;
  } catch (_) {
    catalog = null;
  }
  catalogLanguage = lang;
}

// The workspace may have its own name; catalogs are written with "Exodus".
function toSource(text) {
  const name = workspaceName();
  return name === DEFAULT_NAME ? text : text.split(name).join(DEFAULT_NAME);
}

function interpolate(template, vars) {
  return template.replace(/\{([a-z_]+)\}/gi, (whole, key) => (vars && key in vars ? String(vars[key]) : whole));
}

/** Translate a piece of the app's own English wording (exact text, or a pattern). */
export function t(english, vars) {
  if (typeof english !== 'string') return english;
  let out = english;
  if (catalog && language !== DEFAULT_LANGUAGE) {
    const exact = catalog.messages.get(english);
    if (exact) out = exact;
    else {
      for (const p of catalog.patterns) {
        const m = p.regex.exec(english);
        if (m) { out = interpolate(p.target, Object.fromEntries(p.names.map((n, i) => [n, translateFragment(m[i + 1])]))); break; }
      }
    }
  }
  return interpolate(out, vars);
}

// Pattern values (e.g. a greeting's name) are shown as they are, except words
// that are themselves translatable ("morning" in "Good {part}").
function translateFragment(value) {
  return catalog?.messages.get(value) || value;
}

function render(source) {
  const parts = /^(\s*)([\s\S]*?)(\s*)$/.exec(source);
  const core = parts[2];
  if (!core) return source;
  return parts[1] + brandText(t(core)) + parts[3];
}

function isOwnOutput(current, shown) {
  if (current === shown) return true;
  // Same text apart from the product/workspace name.
  const plain = text => toSource(text).replace(/\bExodus\b/g, '\u0000');
  return shown != null && plain(current) === plain(shown);
}

function skipped(node) {
  const element = node.nodeType === 1 ? node : node.parentElement;
  return !element || !!element.closest(SKIP);
}

function translateText(node) {
  if (skipped(node) || !/[A-Za-zÀ-ÿ]/.test(node.data)) return;
  let state = nodeState.get(node);
  // Our own output may since have had the workspace name swapped in; that is
  // still ours, so keep the English source.
  if (!state || !isOwnOutput(node.data, state.shown)) state = { source: toSource(node.data), shown: node.data };
  const shown = render(state.source);
  state.shown = shown;
  nodeState.set(node, state);
  if (node.data !== shown) node.data = shown;
}

function translateAttributes(element) {
  if (skipped(element)) return;
  let saved = attrState.get(element);
  for (const attr of TEXT_ATTRIBUTES) {
    const value = element.getAttribute(attr);
    if (value == null || !/[A-Za-z]/.test(value)) continue;
    const entry = saved?.[attr];
    const source = entry && isOwnOutput(value, entry.shown) ? entry.source : toSource(value);
    const shown = render(source);
    saved = saved || {};
    saved[attr] = { source, shown };
    if (value !== shown) element.setAttribute(attr, shown);
  }
  if (saved) attrState.set(element, saved);
}

function translateTree(root) {
  if (root.nodeType === 3) return translateText(root);
  if (root.nodeType !== 1 || skipped(root)) return;
  translateAttributes(root);
  const walker = root.ownerDocument.createTreeWalker(root, 4 | 1);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === 3) translateText(node);
    else translateAttributes(node);
  }
}

function observe(root) {
  if (observed.has(root) || typeof MutationObserver === 'undefined') return;
  observed.add(root);
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') translateText(record.target);
      else if (record.type === 'attributes') translateAttributes(record.target);
      else for (const node of record.addedNodes) translateTree(node);
    }
  }).observe(root, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: TEXT_ATTRIBUTES });
}

let titleObserver = null;
function translateTitle(doc) {
  const title = doc.querySelector('title');
  if (!title?.firstChild) return;
  translateText(title.firstChild);
  if (!titleObserver && typeof MutationObserver !== 'undefined') {
    titleObserver = new MutationObserver(() => { if (title.firstChild) translateText(title.firstChild); });
    titleObserver.observe(title, { childList: true, characterData: true, subtree: true });
  }
}

/** Translate the app's own text on the page; safe to call repeatedly. */
export function applyTranslations(doc = document) {
  doc.documentElement.lang = language;
  globalThis.__exodusLocale = currentLocale();
  if (language !== DEFAULT_LANGUAGE) active = true;
  if (!active) return;
  translateTitle(doc);
  for (const selector of SCOPES) {
    for (const root of doc.querySelectorAll(selector)) { translateTree(root); observe(root); }
  }
}

/** Choose a language: saved in this browser and (when signed in) the account. */
export async function setLanguage(lang, { doc = document, fetchImpl = globalThis.fetch, saveToAccount = true } = {}) {
  const next = supported(lang) || DEFAULT_LANGUAGE;
  try { globalThis.localStorage?.setItem(STORAGE_KEY, next); } catch (_) {}
  const changed = next !== language;
  language = next;
  await loadCatalog(next, fetchImpl);
  applyTranslations(doc);
  if (changed) doc.dispatchEvent(new CustomEvent(LANGUAGE_EVENT, { detail: { language: next } }));
  if (saveToAccount && doc.getElementById('settings-modal')) {
    fetchImpl('/api/prefs/language', {
      method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: next }),
    }).catch(() => {});
  }
  return next;
}

let started = false;
/** Apply the remembered language now; then follow the account's saved choice. */
export async function startTranslations({ doc = document, fetchImpl = globalThis.fetch } = {}) {
  if (started) return;
  started = true;
  doc.documentElement.lang = language;
  globalThis.__exodusLocale = currentLocale();
  await loadCatalog(language, fetchImpl);
  const run = () => applyTranslations(doc);
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', run, { once: true }); else run();
  doc.addEventListener(BRAND_EVENT, run);
  // New Home/Settings areas appear after load: pick them up once per frame.
  if (typeof MutationObserver !== 'undefined' && doc.body) {
    let queued = false;
    new MutationObserver(() => {
      if (!active || queued) return;
      queued = true;
      (globalThis.requestAnimationFrame || setTimeout)(() => {
        queued = false;
        for (const selector of SCOPES) {
          for (const root of doc.querySelectorAll(selector)) if (!observed.has(root)) { translateTree(root); observe(root); }
        }
      });
    }).observe(doc.body, { childList: true, subtree: true });
  }
  // Signed-in pages follow the account's choice (never fetched on sign-in).
  if (doc.getElementById('settings-modal')) {
    try {
      const response = await fetchImpl('/api/prefs/language', { credentials: 'same-origin', cache: 'no-store' });
      const saved = response.ok ? supported((await response.json())?.value) : null;
      if (saved && saved !== language) await setLanguage(saved, { doc, fetchImpl, saveToAccount: false });
    } catch (_) {}
  }
}
