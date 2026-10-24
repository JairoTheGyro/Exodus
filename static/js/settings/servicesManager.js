// Settings → System → Services (admin): turn the optional services on/off,
// remove (data kept unless chosen) and reinstall. Talks to /api/services,
// which forwards to the opt-in service manager helper.
const STATE_LABEL = { running: 'On', stopped: 'Off', removed: 'Removed' };
const BUSY_LABEL = { start: 'Turning on…', stop: 'Turning off…', remove: 'Removing…', reinstall: 'Reinstalling…' };
let pollTimer = null;

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

function button(doc, label, action, extra = '') {
  return el(doc, 'button', { type: 'button', className: `admin-btn-sm ${extra}`.trim(), text: label, dataset: { serviceAction: action } });
}

function describeData(service) {
  const parts = [];
  if (service.data_volumes?.length) parts.push(`Docker volumes: ${service.data_volumes.join(', ')}`);
  if (service.data_folders?.length) parts.push(`folders on this computer: ${service.data_folders.join(', ')}`);
  return parts.join('; ');
}

export function renderServices(container, data, doc = container.ownerDocument || document) {
  container.replaceChildren();
  if (!data?.available) {
    container.append(
      el(doc, 'p', { className: 'admin-toggle-sub', text: data?.reason === 'unreachable'
        ? 'The service manager add-on is enabled but not answering. Check that the servicectl container is running.'
        : 'The Services manager is off.' }),
      el(doc, 'p', { className: 'admin-toggle-sub services-hint', text: data?.hint || '' }),
    );
    return;
  }
  for (const service of data.services) {
    const row = el(doc, 'div', { className: 'services-row', dataset: { service: service.name } });
    const state = service.busy ? (BUSY_LABEL[service.busy] || 'Working…') : (STATE_LABEL[service.state] || service.state);
    row.append(
      el(doc, 'span', { className: 'services-name', text: service.label }),
      el(doc, 'span', { className: `services-state services-${service.busy ? 'busy' : service.state}`, text: state }),
    );
    const actions = el(doc, 'span', { className: 'services-actions' });
    if (!service.busy) {
      if (service.state === 'running') actions.append(button(doc, 'Turn off', 'stop'));
      if (service.state === 'stopped') actions.append(button(doc, 'Turn on', 'start'));
      if (service.state === 'removed') actions.append(button(doc, 'Install', 'start'));
      if (service.state !== 'removed') actions.append(button(doc, 'Remove', 'remove', 'admin-btn-danger'));
      actions.append(button(doc, 'Reinstall', 'reinstall'));
    }
    row.append(actions);
    if (service.error) row.append(el(doc, 'p', { className: 'services-error', role: 'alert', text: service.error }));
    container.append(row);
  }
}

function confirmRemove(doc, row, service) {
  row.querySelector('.services-confirm')?.remove();
  const box = el(doc, 'div', { className: 'services-confirm' });
  const data = describeData(service);
  const check = el(doc, 'input', { type: 'checkbox', id: `services-delete-${service.name}` });
  box.append(
    el(doc, 'p', { className: 'admin-toggle-sub', text: `Removes ${service.label}'s container and image to free space. Its data is kept${data ? ` (${data})` : ''}, so reinstalling brings it back.` }),
  );
  if (service.data_volumes?.length) {
    box.append(el(doc, 'label', { for: check.id, className: 'services-delete-label' }, check,
      ` Also delete its data in Docker volumes (${service.data_volumes.join(', ')}). This can't be undone.`));
  }
  box.append(el(doc, 'span', { className: 'services-confirm-actions' },
    button(doc, 'Remove', 'confirm-remove', 'admin-btn-danger'), button(doc, 'Cancel', 'cancel-remove')));
  row.append(box);
  return check;
}

async function load(container, api) {
  const response = await api('/api/services');
  const data = response.ok ? await response.json() : { available: false, reason: 'error', hint: 'Could not load services.' };
  renderServices(container, data);
  clearTimeout(pollTimer);
  // Keep the screen current while something is working.
  if (data.available && data.services.some(s => s.busy)) pollTimer = setTimeout(() => load(container, api), 3000);
  return data;
}

/** Mount the Services card; safe to call each time System opens. */
export function mountServicesManager(container, { api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }) } = {}) {
  if (!container) return Promise.resolve();
  let latest = null;
  const refresh = () => load(container, api).then(data => { latest = data; return data; });
  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('click', async event => {
      const target = event.target.closest?.('[data-service-action]');
      if (!target) return;
      const row = target.closest('.services-row');
      const name = row?.dataset.service;
      const service = latest?.services?.find(s => s.name === name);
      const action = target.dataset.serviceAction;
      if (!service) return;
      if (action === 'remove') { confirmRemove(container.ownerDocument, row, service); return; }
      if (action === 'cancel-remove') { row.querySelector('.services-confirm')?.remove(); return; }
      const real = action === 'confirm-remove' ? 'remove' : action;
      const body = real === 'remove' ? JSON.stringify({ delete_data: !!row.querySelector('.services-confirm input')?.checked }) : undefined;
      target.disabled = true;
      const response = await api(`/api/services/${encodeURIComponent(name)}/${real}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({}))).detail || 'The action could not start.';
        row.append(el(container.ownerDocument, 'p', { className: 'services-error', role: 'alert', text: detail }));
      }
      refresh();
    });
  }
  return refresh();
}
