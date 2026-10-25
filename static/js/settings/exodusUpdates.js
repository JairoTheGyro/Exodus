// Settings → License Tracker → Updates (admins): is a tested Exodus update
// ready, what changed, and one click to install it through the update helper
// on the server (scripts/update_agent.py). Talks to /api/updates.
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

const short = revision => String(revision || '').slice(0, 7);
const day = value => String(value || '').slice(0, 10);

const TESTED = {
  passed: 'All tests passed',
  testing: 'Still being tested; check again later',
  failed: 'Some tests failed, so it can’t be installed yet',
  unknown: 'No test results yet',
};

export function renderUpdates(container, view, doc = container.ownerDocument || document) {
  container.replaceChildren();
  const installed = view.installed;
  const latest = view.latest;
  const status = view.status || {};
  const busy = status.state === 'pending' || status.state === 'running';

  container.append(el(doc, 'p', { className: 'exodus-updates-line', text: installed
    ? `This server runs version ${short(installed.revision)}.`
    : 'This server’s version isn’t known yet. It’s recorded once the update helper or the updater runs.' }));

  if (latest) {
    const line = view.update_available
      ? `A newer version is available: ${short(latest.revision)} from ${day(latest.date)}.`
      : (installed ? 'Exodus is up to date.' : `Newest version: ${short(latest.revision)} from ${day(latest.date)}.`);
    container.append(el(doc, 'p', { className: 'exodus-updates-line', text: line }));
    if (view.update_available) {
      container.append(el(doc, 'p', { className: `exodus-updates-tested is-${latest.tested}`, text: TESTED[latest.tested] || TESTED.unknown }));
      const changes = view.changes || [];
      if (changes.length) {
        const count = Number.isInteger(view.ahead_by) ? view.ahead_by : changes.length;
        const list = el(doc, 'ul', { className: 'exodus-updates-changes' });
        for (const change of changes.slice(-15).reverse()) list.append(el(doc, 'li', { text: change }));
        container.append(el(doc, 'details', {}, el(doc, 'summary', { text: `What’s new (${count} changes)` }), list));
      }
      if (view.compare_url) {
        container.append(el(doc, 'a', { href: view.compare_url, target: '_blank', rel: 'noopener noreferrer', className: 'exodus-updates-link', text: 'See every change on GitHub' }));
      }
    }
  }
  if (view.checked_at) container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: `Last checked ${day(view.checked_at)}. Exodus checks once a day and tells admins when a tested update is ready.` }));
  if (view.error) container.append(el(doc, 'p', { className: 'exodus-updates-warn', role: 'note', text: view.error }));

  if (status.state) {
    const box = el(doc, 'div', { className: `exodus-updates-status is-${status.state}`, role: 'status' },
      el(doc, 'p', { text: status.message || '' }));
    if (status.state === 'failed' && status.log?.length) {
      const pre = el(doc, 'pre', { className: 'exodus-updates-log', text: status.log.join('\n') });
      box.append(el(doc, 'details', {}, el(doc, 'summary', { text: 'Details' }), pre));
    }
    if (status.state === 'done') box.append(el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { updates: 'reload' }, text: 'Reload' }));
    container.append(box);
  }

  const row = el(doc, 'div', { className: 'exodus-updates-row' },
    el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { updates: 'check' }, text: 'Check for updates' }));
  const canInstall = view.update_available && latest?.tested === 'passed' && view.helper?.online && !busy;
  if (view.update_available && latest?.tested === 'passed') {
    const install = el(doc, 'button', { type: 'button', className: 'admin-btn-add', dataset: { updates: 'install' }, text: 'Update now' });
    if (!canInstall) install.disabled = true;
    row.prepend(install);
  }
  container.append(row);

  if (!view.helper?.online) {
    container.append(el(doc, 'div', { className: 'exodus-updates-setup' },
      el(doc, 'p', { text: 'To update with one click, set up the update helper once. On the server, in the Exodus folder, run:' }),
      el(doc, 'code', { text: 'python3 scripts/update_agent.py install' }),
      el(doc, 'p', { className: 'admin-toggle-sub', text: 'Or update by hand with python3 scripts/update_local.py. Either way, your data is backed up first and the previous version is kept so you can go back.' })));
  }
  container.append(el(doc, 'p', { className: 'exodus-updates-msg admin-toggle-sub', role: 'status' }));
}

/** Mount the card for admins; hides it for everyone else. */
export async function mountUpdates(container, {
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
  confirmFn = message => (window.uiModule?.styledConfirm ? window.uiModule.styledConfirm(message) : Promise.resolve(window.confirm(message))),
  reload = () => location.reload(),
  pollMs = 5000,
} = {}) {
  if (!container) return;
  const card = container.closest('.admin-card') || container;
  let view = null;
  let timer = null;
  const say = text => { const msg = container.querySelector('.exodus-updates-msg'); if (msg) msg.textContent = text; };

  const show = next => {
    view = next;
    renderUpdates(container, view);
    clearTimeout(timer);
    if (['pending', 'running'].includes(view.status?.state) && container.isConnected) timer = setTimeout(refresh, pollMs);
  };

  async function call(url, init) {
    const response = await api(url, init);
    const body = await response.json().catch(() => ({}));
    return { response, body };
  }

  async function refresh() {
    try {
      const { response, body } = await call('/api/updates');
      if (response.status === 401 || response.status === 403) { card.hidden = true; return; }
      if (response.ok) show(body);
    } catch (_) {
      // Exodus restarts during an update; keep asking.
      if (['pending', 'running'].includes(view?.status?.state)) timer = setTimeout(refresh, pollMs);
    }
  }

  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('click', async event => {
      const action = event.target.closest?.('[data-updates]')?.dataset.updates;
      if (!action) return;
      if (action === 'reload') { reload(); return; }
      if (action === 'check') {
        event.target.disabled = true;
        say('Checking GitHub…');
        const { response, body } = await call('/api/updates/check', { method: 'POST' });
        if (response.ok) show(body);
        else { event.target.disabled = false; say(typeof body.detail === 'string' ? body.detail : 'The check didn’t work.'); }
      } else if (action === 'install') {
        const ok = await confirmFn('Install this Exodus update now? Your data is backed up first. Exodus restarts and may be unavailable for a few minutes.');
        if (!ok) return;
        event.target.disabled = true;
        const { response, body } = await call('/api/updates/approve', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: view.latest.revision }),
        });
        if (response.ok) show(body);
        else { event.target.disabled = false; say(typeof body.detail === 'string' ? body.detail : 'The update couldn’t start.'); }
      }
    });
  }
  const { response, body } = await call('/api/updates').catch(() => ({ response: null, body: {} }));
  if (!response || response.status === 401 || response.status === 403) { card.hidden = true; return; }
  card.hidden = false;
  if (response.ok) show(body);
}
