// Settings → Account → Spaces: create shared spaces (e.g. "Family"), add or
// remove members, leave, rename or delete. Talks to /api/spaces. Notes and
// lists are shared from their ⋯ menu ("Share to").
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

function btn(doc, label, action, extra = '') {
  return el(doc, 'button', { type: 'button', className: `admin-btn-sm ${extra}`.trim(), text: label, dataset: { spaceAction: action } });
}

// "3 members · 2 shared notes · 1 shared calendar" — one span per part so
// each part translates on its own.
function metaLine(doc, space) {
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const parts = [plural(space.members.length, 'member', 'members'),
    plural(space.note_count || 0, 'shared note', 'shared notes')];
  if (space.calendar_count) parts.push(plural(space.calendar_count, 'shared calendar', 'shared calendars'));
  const meta = el(doc, 'span', { className: 'spaces-meta' });
  parts.forEach((part, i) => {
    if (i) meta.append(' · ');
    meta.append(el(doc, 'span', { text: part }));
  });
  return meta;
}

export function renderSpaces(container, data, doc = container.ownerDocument || document) {
  container.replaceChildren();
  if (!data || data.error) {
    container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: data?.error || 'Spaces could not load.' }));
    return;
  }
  const me = data.me;
  for (const space of data.spaces) {
    const box = el(doc, 'div', { className: 'spaces-space', dataset: { spaceId: space.id } });
    const head = el(doc, 'div', { className: 'spaces-head' },
      el(doc, 'span', { className: 'spaces-name', text: space.name }),
      metaLine(doc, space));
    const actions = el(doc, 'span', { className: 'spaces-actions' });
    if (space.can_manage) actions.append(btn(doc, 'Rename', 'rename'), btn(doc, 'Delete', 'delete', 'admin-btn-danger'));
    if (space.role) actions.append(btn(doc, 'Leave', 'leave'));
    head.append(actions);
    box.append(head);
    const list = el(doc, 'ul', { className: 'spaces-members' });
    for (const member of space.members) {
      const item = el(doc, 'li', { dataset: { member: member.username } },
        el(doc, 'span', { text: member.username + (member.username === me ? ' (you)' : '') }),
        el(doc, 'span', { className: 'spaces-role', text: member.role === 'manager' ? 'Manager' : 'Member' }));
      if (space.can_manage && member.username !== me) {
        if (member.role !== 'manager') item.append(btn(doc, 'Make manager', 'promote'));
        item.append(btn(doc, 'Remove', 'remove', 'admin-btn-danger'));
      }
      list.append(item);
    }
    box.append(list);
    if (space.can_manage) {
      const input = el(doc, 'input', { type: 'text', className: 'spaces-input', placeholder: 'Username to add', 'aria-label': `Add someone to ${space.name}`, autocomplete: 'off' });
      box.append(el(doc, 'div', { className: 'spaces-add' }, input, btn(doc, 'Add', 'add')));
    }
    container.append(box);
  }
  const name = el(doc, 'input', { type: 'text', className: 'spaces-input', placeholder: 'New space name, e.g. Family', maxlength: '40', 'aria-label': 'New space name' });
  container.append(el(doc, 'div', { className: 'spaces-add spaces-create' }, name, btn(doc, 'Create space', 'create')));
  container.append(el(doc, 'p', { className: 'spaces-msg admin-toggle-sub', role: 'status' }));
}

async function readError(response) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === 'string' ? body.detail : 'That didn’t work. Try again.';
}

async function load(container, api) {
  const response = await api('/api/spaces');
  const data = response.ok ? await response.json() : { error: await readError(response) };
  renderSpaces(container, data);
  return data;
}

/** Mount the Spaces card; safe to call every time Account opens. */
export function mountSpacesSettings(container, {
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
  confirmFn = message => (window.uiModule?.styledConfirm ? window.uiModule.styledConfirm(message) : Promise.resolve(window.confirm(message))),
  promptFn = (message, value) => Promise.resolve(window.prompt(message, value)),
} = {}) {
  if (!container) return Promise.resolve();
  const send = (url, method, body) => api(url, {
    method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
  });
  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || !event.target.matches?.('.spaces-input')) return;
      event.preventDefault();
      event.target.closest('.spaces-add')?.querySelector('[data-space-action]')?.click();
    });
    container.addEventListener('click', async event => {
      const target = event.target.closest?.('[data-space-action]');
      if (!target) return;
      const action = target.dataset.spaceAction;
      const box = target.closest('.spaces-space');
      const id = box?.dataset.spaceId;
      const name = box?.querySelector('.spaces-name')?.textContent || '';
      const member = target.closest('[data-member]')?.dataset.member;
      const base = id ? `/api/spaces/${encodeURIComponent(id)}` : '/api/spaces';
      let response = null;
      if (action === 'create') {
        const input = target.parentElement.querySelector('input');
        if (!input.value.trim()) { input.focus(); return; }
        response = await send('/api/spaces', 'POST', { name: input.value });
      } else if (action === 'add') {
        const input = target.parentElement.querySelector('input');
        if (!input.value.trim()) { input.focus(); return; }
        response = await send(`${base}/members`, 'POST', { username: input.value });
      } else if (action === 'promote') {
        response = await send(`${base}/members`, 'POST', { username: member, role: 'manager' });
      } else if (action === 'remove') {
        if (!await confirmFn(`Remove ${member} from ${name}? Notes they shared there go back to being only theirs.`)) return;
        response = await send(`${base}/members/${encodeURIComponent(member)}`, 'DELETE');
      } else if (action === 'leave') {
        const me = JSON.parse(container.dataset.me || '""');
        if (!await confirmFn(`Leave ${name}? Notes you shared there go back to being only yours.`)) return;
        response = await send(`${base}/members/${encodeURIComponent(me)}`, 'DELETE');
      } else if (action === 'rename') {
        const next = await promptFn('New name for this space', name);
        if (!next || !next.trim() || next.trim() === name) return;
        response = await send(base, 'PUT', { name: next });
      } else if (action === 'delete') {
        if (!await confirmFn(`Delete ${name}? No notes are deleted: each goes back to the person who made it.`)) return;
        response = await send(base, 'DELETE');
      }
      if (!response) return;
      if (!response.ok) {
        const message = await readError(response);
        const msg = container.querySelector('.spaces-msg');
        if (msg) msg.textContent = message;
        return;
      }
      refresh();
    });
  }
  const refresh = () => load(container, api).then(data => {
    container.dataset.me = JSON.stringify(data?.me || '');
    return data;
  });
  return refresh();
}
