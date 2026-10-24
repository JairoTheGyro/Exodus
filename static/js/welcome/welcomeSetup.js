// Exodus welcome setup: a short guided first run for new accounts (invited
// family and friends). Every step is optional and can be changed later in
// Settings. It opens once, for accounts that haven't chosen their workspace
// yet, and can be run again from Settings → Account.
import { mountLanguagePicker } from '../settings/languagePicker.js';
import { mountAppLookPicker } from '../settings/appLooks.js';
import { mountPhoneAlerts } from '../settings/phoneAlerts.js';
import { mountAiChoice } from '../settings/aiChoice.js';
import { workspaceName } from '../workspaceBrand.js';

export const PREF_KEY = 'exodus-welcome';
export const STEPS = Object.freeze(['hello', 'workspace', 'look', 'connect', 'phone', 'done']);

const jsonInit = (method, body) => ({
  method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

/**
 * Should the welcome open by itself? Only for accounts that haven't chosen
 * their workspace (new accounts) and haven't finished or skipped it before.
 */
export async function shouldShowWelcome(fetchImpl = globalThis.fetch) {
  try {
    const [home, pref] = await Promise.all([
      fetchImpl('/api/home/profile', { credentials: 'same-origin' }).then(r => (r.ok ? r.json() : null)),
      fetchImpl(`/api/prefs/${PREF_KEY}`, { credentials: 'same-origin' }).then(r => (r.ok ? r.json() : null)),
    ]);
    if (!home || !pref) return false; // signed out or server trouble: never block the app
    if (pref.value && pref.value.done) return false;
    return !home.profile?.mode;
  } catch (_) {
    return false;
  }
}

function el(doc, tag, props = {}, ...children) {
  const node = doc.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'className') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

/**
 * Open the welcome window. Options are for tests: `fetchImpl`, `openSettings`
 * (tab) and `reload()`. Resolves when it closes.
 */
export function openWelcome({
  doc = document,
  fetchImpl = globalThis.fetch,
  openSettings = async tab => (await import('../settings.js?v=20260912writingstyle3')).default.open(tab),
  reload = () => { window.location.href = '/'; },
  owner = '',
} = {}) {
  doc.getElementById('exodus-welcome')?.remove();
  let step = 0;
  let chosenMode = null;
  let resolveClosed;
  const closed = new Promise(resolve => { resolveClosed = resolve; });

  const name = workspaceName();
  const overlay = el(doc, 'div', { id: 'exodus-welcome', className: 'exodus-welcome', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'exodus-welcome-title', 'data-i18n-scope': '' });
  const panel = el(doc, 'div', { className: 'exodus-welcome-panel' });
  const progress = el(doc, 'ol', { className: 'exodus-welcome-progress', 'aria-label': 'Setup steps' });
  const body = el(doc, 'div', { className: 'exodus-welcome-body' });
  const back = el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { welcome: 'back' }, text: 'Back' });
  const skip = el(doc, 'button', { type: 'button', className: 'admin-btn-sm exodus-welcome-skip', dataset: { welcome: 'skip' }, text: 'Skip setup' });
  const next = el(doc, 'button', { type: 'button', className: 'admin-btn-add', dataset: { welcome: 'next' }, text: 'Next' });
  const footer = el(doc, 'div', { className: 'exodus-welcome-footer' }, skip, el(doc, 'span', { className: 'exodus-welcome-spacer' }), back, next);
  panel.append(progress, body, footer);
  overlay.append(panel);

  const labels = { hello: 'Language', workspace: 'Your AI', look: 'Look', connect: 'Email and calendar', phone: 'Phone alerts', done: 'Done' };
  for (const id of STEPS) progress.append(el(doc, 'li', { dataset: { step: id }, text: labels[id] }));

  async function markDone(skipped) {
    try {
      await fetchImpl(`/api/prefs/${PREF_KEY}`, jsonInit('PUT', { value: { done: true, skipped: !!skipped, at: new Date().toISOString() } }));
    } catch (_) { /* a failed save just means it may show again */ }
  }

  async function close({ skipped = false } = {}) {
    await markDone(skipped);
    overlay.remove();
    doc.removeEventListener('keydown', onKey, true);
    resolveClosed({ skipped, mode: chosenMode });
    // A new workspace choice changes what the whole app shows.
    if (chosenMode) reload();
  }

  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close({ skipped: true }); }
  }

  function render() {
    const id = STEPS[step];
    body.replaceChildren();
    progress.querySelectorAll('li').forEach((li, i) => {
      li.classList.toggle('active', i === step);
      li.classList.toggle('complete', i < step);
      if (i === step) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
    back.hidden = step === 0;
    skip.hidden = id === 'done';
    next.textContent = id === 'done' ? 'Start using it' : 'Next';
    body.dataset.step = id;

    if (id === 'hello') {
      const select = el(doc, 'select', { id: 'exodus-welcome-language', className: 'theme-fd-select app-look-select', 'aria-label': 'Language' });
      body.append(
        el(doc, 'h2', { id: 'exodus-welcome-title', text: `Welcome to ${name}` }),
        el(doc, 'p', { text: owner ? `Hi ${owner}! A few quick choices get your workspace ready. Each one is optional, and you can change it later in Settings.` : 'A few quick choices get your workspace ready. Each one is optional, and you can change it later in Settings.' }),
        el(doc, 'label', { className: 'exodus-welcome-field', for: select.id }, el(doc, 'span', { text: 'Language' }), select),
      );
      mountLanguagePicker(select);
    } else if (id === 'workspace') {
      // Exodus "Your AI": shared AI, your own cloud account, or no AI.
      const rows = el(doc, 'div', { className: 'exodus-welcome-ai' });
      body.append(el(doc, 'h2', { id: 'exodus-welcome-title', text: 'Where should your AI come from?' }), rows,
        el(doc, 'p', { className: 'exodus-welcome-muted', text: 'This only affects your account. You can switch any time.' }));
      mountAiChoice(rows, {
        compact: true,
        api: (url, init) => fetchImpl(url, { credentials: 'same-origin', ...init }),
        openSettings: async tab => { await close(); await openSettings(tab); },
        onChanged: (data, previous) => {
          if (!previous || !!previous.ai_free !== !!data.ai_free) chosenMode = data.ai_free ? 'ai-free' : 'full';
        },
      });
    } else if (id === 'look') {
      const rows = el(doc, 'div', { className: 'exodus-welcome-looks' });
      body.append(el(doc, 'h2', { id: 'exodus-welcome-title', text: 'Pick a look' }),
        el(doc, 'p', { text: 'Choose how the built-in apps look. More colours and themes are in Settings → Appearance.' }), rows);
      mountAppLookPicker(rows, { doc });
    } else if (id === 'connect') {
      const open = (label, tab) => {
        const button = el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { welcomeOpen: tab }, text: label });
        button.addEventListener('click', async () => { await close(); await openSettings(tab); });
        return button;
      };
      body.append(el(doc, 'h2', { id: 'exodus-welcome-title', text: 'Bring in your email and calendar' }),
        el(doc, 'p', { text: 'Connect your email account, or a calendar you already use, so everything is in one place. You can also do this later.' }),
        el(doc, 'div', { className: 'exodus-welcome-actions' }, open('Connect email', 'email'), open('Connect a calendar', 'integrations')));
    } else if (id === 'phone') {
      const rows = el(doc, 'div', { className: 'exodus-welcome-phone' });
      body.append(el(doc, 'h2', { id: 'exodus-welcome-title', text: 'Get alerts on your phone' }), rows);
      mountPhoneAlerts(rows, { api: (url, init) => fetchImpl(url, { credentials: 'same-origin', ...init }) });
    } else {
      body.append(el(doc, 'h2', { id: 'exodus-welcome-title', text: 'You’re all set' }),
        el(doc, 'p', { text: 'Everything you chose can be changed in Settings. To run this setup again, open Settings → Account.' }),
        el(doc, 'p', { className: 'exodus-welcome-muted', text: 'Tip: you can share notes, lists, calendars and documents with family in Settings → Account → Spaces.' }));
    }
    body.querySelector('h2')?.setAttribute('tabindex', '-1');
    body.querySelector('h2')?.focus?.();
  }

  footer.addEventListener('click', event => {
    const action = event.target.closest?.('[data-welcome]')?.dataset.welcome;
    if (action === 'back' && step > 0) { step -= 1; render(); }
    else if (action === 'next') { if (STEPS[step] === 'done') close(); else { step += 1; render(); } }
    else if (action === 'skip') close({ skipped: true });
  });
  doc.addEventListener('keydown', onKey, true);
  doc.body.append(overlay);
  render();
  return closed;
}

/** App start: open the welcome by itself when it applies. */
export async function maybeStartWelcome(options = {}) {
  if (!(await shouldShowWelcome(options.fetchImpl))) return null;
  let owner = '';
  try {
    const r = await (options.fetchImpl || globalThis.fetch)('/api/home/profile', { credentials: 'same-origin' });
    owner = r.ok ? ((await r.json()).owner || '') : '';
  } catch (_) {}
  return openWelcome({ ...options, owner });
}
