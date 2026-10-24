// Settings → Account → Phone alerts: your private ntfy address, how to
// subscribe on a phone, a test button and "Get a new address".
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

function btn(doc, label, action) {
  return el(doc, 'button', { type: 'button', className: 'admin-btn-sm', text: label, dataset: { alertAction: action } });
}

export function renderPhoneAlerts(container, data, doc = container.ownerDocument || document) {
  container.replaceChildren();
  if (!data || data.error) {
    container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: data?.error || 'Phone alerts could not load.' }));
    return;
  }
  if (!data.enabled) {
    container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: 'Phone alerts are turned off on this server.' }));
    return;
  }
  container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: data.personal
    ? 'Your reminders and alerts go to this private address. Only people who know it can read it, so keep it to yourself.'
    : 'Without sign-in accounts, everyone shares this address.' }));
  const address = el(doc, 'code', { className: 'phone-alerts-topic', text: data.topic });
  container.append(el(doc, 'div', { className: 'phone-alerts-row' },
    el(doc, 'span', { className: 'phone-alerts-label', text: 'Server' }), el(doc, 'code', { className: 'phone-alerts-server', text: data.server })));
  container.append(el(doc, 'div', { className: 'phone-alerts-row' },
    el(doc, 'span', { className: 'phone-alerts-label', text: 'Topic' }), address, btn(doc, 'Copy', 'copy')));
  const steps = el(doc, 'ol', { className: 'phone-alerts-steps' },
    el(doc, 'li', { text: 'Install the free ntfy app on your phone.' }),
    el(doc, 'li', { text: 'Tap +, turn on "Use another server", and enter the server above.' }),
    el(doc, 'li', { text: 'Enter the topic above and subscribe.' }),
    el(doc, 'li', { text: 'Press Send test to check it works.' }));
  container.append(steps);
  const actions = el(doc, 'div', { className: 'phone-alerts-actions' }, btn(doc, 'Send test', 'test'));
  if (data.personal) actions.append(btn(doc, 'Get a new address', 'reset'));
  container.append(actions, el(doc, 'p', { className: 'phone-alerts-msg admin-toggle-sub', role: 'status' }));
}

/** Mount the Phone alerts card; safe to call every time Account opens. */
export function mountPhoneAlerts(container, {
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
  confirmFn = message => (window.uiModule?.styledConfirm ? window.uiModule.styledConfirm(message) : Promise.resolve(window.confirm(message))),
  copyFn = text => navigator.clipboard.writeText(text),
} = {}) {
  if (!container) return Promise.resolve();
  let latest = null;
  const say = text => { const msg = container.querySelector('.phone-alerts-msg'); if (msg) msg.textContent = text; };
  const show = data => { latest = data; renderPhoneAlerts(container, data); return data; };
  const load = async () => {
    const response = await api('/api/alerts/phone');
    return show(response.ok ? await response.json() : { error: 'Phone alerts could not load.' });
  };
  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('click', async event => {
      const target = event.target.closest?.('[data-alert-action]');
      if (!target || !latest) return;
      const action = target.dataset.alertAction;
      if (action === 'copy') {
        try { await copyFn(latest.topic); say('Topic copied.'); } catch (_) { say('Copy failed. Select the topic and copy it by hand.'); }
      } else if (action === 'test') {
        target.disabled = true;
        const response = await api('/api/alerts/phone/test', { method: 'POST' });
        const result = response.ok ? await response.json() : { status: 'failed' };
        target.disabled = false;
        say(result.status === 'sent'
          ? 'Test sent. It should appear on your phone in a few seconds.'
          : 'The test could not be sent. Check that the ntfy service is on (Settings → System → Services).');
      } else if (action === 'reset') {
        if (!await confirmFn('Get a new private address? Your phone stops receiving alerts until you subscribe to the new topic.')) return;
        const response = await api('/api/alerts/phone/reset', { method: 'POST' });
        if (response.ok) { show(await response.json()); say('New address ready. Subscribe to it on your phone.'); }
        else say('Could not get a new address.');
      }
    });
  }
  return load();
}
