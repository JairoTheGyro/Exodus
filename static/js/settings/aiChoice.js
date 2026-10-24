// Settings → Account → Your AI (and the welcome setup): choose shared AI, your
// own cloud account, or no AI; set a monthly spending cap; admins can cap
// each member. Talks to /api/ai-budget (src/ai_budget.py).
const CHOICES = [
  ['shared', 'Shared AI', 'Use the AI connections your household or team set up. Nothing to set up.'],
  ['own', 'My own cloud account', 'Use your own AI provider account (for example OpenRouter or OpenAI). You pay that provider directly.'],
  ['off', 'No AI', 'Hide all AI features for your account. Notes, calendar, email and files still work.'],
];

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

const money = value => `$${Number(value || 0).toFixed(2)}`;

function currentChoice(data) {
  if (data.ai_free) return 'off';
  return data.source && data.source !== 'off' ? data.source : 'shared';
}

export function renderAiChoice(container, data, { compact = false, doc = container.ownerDocument || document } = {}) {
  container.replaceChildren();
  if (!data || data.error) {
    container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: data?.error || 'Your AI settings could not load.' }));
    return;
  }
  const chosen = currentChoice(data);
  const group = el(doc, 'div', { className: 'ai-choice-options', role: 'radiogroup', 'aria-label': 'Where your AI comes from' });
  for (const [id, title, text] of CHOICES) {
    const option = el(doc, 'button', { type: 'button', role: 'radio', className: 'ai-choice-option', 'aria-checked': String(id === chosen), dataset: { aiSource: id } },
      el(doc, 'strong', { text: title }), el(doc, 'span', { text }));
    group.append(option);
  }
  container.append(group);

  // What this choice means right now.
  const names = list => list.join(', ');
  let detail = '';
  if (chosen === 'shared') {
    detail = data.connections?.shared?.length
      ? `Available: ${names(data.connections.shared)}.`
      : 'No shared AI is set up yet. Ask your admin, or use your own account.';
  } else if (chosen === 'own') {
    detail = data.connections?.own?.length
      ? `Your accounts: ${names(data.connections.own)}.`
      : 'You haven’t added an AI account yet.';
  }
  if (detail) container.append(el(doc, 'p', { className: 'admin-toggle-sub ai-choice-detail', text: detail }));
  if (chosen === 'own') {
    container.append(el(doc, 'div', { className: 'ai-choice-row' },
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'add-account' }, text: 'Add or manage my AI accounts' })));
  }

  if (chosen !== 'off') {
    const spend = el(doc, 'p', { className: 'ai-choice-spend' });
    spend.textContent = data.cap_usd != null
      ? `This month: ${money(data.spent_usd)} of ${money(data.cap_usd)}`
      : `This month: ${money(data.spent_usd)} (no cap)`;
    container.append(spend);
    if (data.paused) {
      container.append(el(doc, 'p', { className: 'ai-choice-paused', role: 'alert', text: 'Your monthly cap is used up, so AI is paused until the 1st of next month. Raise the cap to keep going.' }));
    }
    if (!compact || chosen === 'own') {
      const input = el(doc, 'input', { type: 'number', min: '0', step: '1', className: 'ai-choice-cap', 'aria-label': 'Monthly spending cap in dollars', placeholder: 'No cap' });
      if (data.self_cap_usd != null) input.value = String(data.self_cap_usd);
      const row = el(doc, 'div', { className: 'ai-choice-row' },
        el(doc, 'span', { text: 'Monthly cap $' }), input,
        el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'save-cap' }, text: 'Save cap' }));
      if (data.self_cap_usd != null) row.append(el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'clear-cap' }, text: 'Remove cap' }));
      container.append(row);
      if (data.admin_cap_usd != null) {
        container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: `Your admin set a limit of ${money(data.admin_cap_usd)} a month.` }));
      }
      container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: 'Costs are estimates for cloud models; AI running on your own computers counts as $0.' }));
    }
  }

  if (data.is_admin && !compact) {
    container.append(el(doc, 'div', { className: 'ai-choice-members' },
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'members' }, text: 'Everyone’s AI spending' })));
  }
  container.append(el(doc, 'p', { className: 'ai-choice-msg admin-toggle-sub', role: 'status' }));
}

export function renderMembers(box, members, doc = box.ownerDocument || document) {
  box.replaceChildren();
  const table = el(doc, 'table', { className: 'ai-choice-table' });
  table.append(el(doc, 'tr', {}, el(doc, 'th', { text: 'Person' }), el(doc, 'th', { text: 'This month' }), el(doc, 'th', { text: 'Admin cap' }), el(doc, 'th')));
  for (const member of members) {
    const input = el(doc, 'input', { type: 'number', min: '0', step: '1', className: 'ai-choice-cap', placeholder: 'None', 'aria-label': `Monthly cap for ${member.username}` });
    if (member.admin_cap_usd != null) input.value = String(member.admin_cap_usd);
    table.append(el(doc, 'tr', { dataset: { member: member.username } },
      el(doc, 'td', { text: member.username }),
      el(doc, 'td', { text: money(member.spent_usd) + (member.paused ? ' (paused)' : '') }),
      el(doc, 'td', {}, input),
      el(doc, 'td', {}, el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'member-cap' }, text: 'Save' }))));
  }
  box.append(table);
}

/**
 * Mount the card. `onChanged(data, previous)` runs after a successful save
 * (the welcome uses it); `openSettings(tab)` opens another Settings panel.
 */
export function mountAiChoice(container, {
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
  compact = false,
  onChanged = null,
  openSettings = async tab => (await import('../settings.js?v=20260912writingstyle3')).default.open(tab),
} = {}) {
  if (!container) return Promise.resolve();
  let latest = null;
  const say = text => { const msg = container.querySelector('.ai-choice-msg'); if (msg) msg.textContent = text; };
  const show = data => { latest = data; renderAiChoice(container, data, { compact }); return data; };
  const send = (url, method, body) => api(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const errorText = async response => {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : 'Could not save. Try again.';
  };
  const save = async body => {
    const previous = latest;
    const response = await send('/api/ai-budget', 'PUT', body);
    if (!response.ok) { say(await errorText(response)); return null; }
    const data = show(await response.json());
    say('Saved for your account.');
    onChanged?.(data, previous);
    return data;
  };
  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('click', async event => {
      const source = event.target.closest?.('[data-ai-source]')?.dataset.aiSource;
      if (source) { await save({ source }); return; }
      const action = event.target.closest?.('[data-ai-action]')?.dataset.aiAction;
      if (!action) return;
      if (action === 'save-cap') {
        const raw = container.querySelector('.ai-choice-row .ai-choice-cap')?.value.trim();
        if (!raw) { await save({ clear_cap: true }); return; }
        await save({ self_cap_usd: Number(raw) });
      } else if (action === 'clear-cap') {
        await save({ clear_cap: true });
      } else if (action === 'add-account') {
        await openSettings('added-models');
      } else if (action === 'members') {
        const response = await api('/api/ai-budget/members');
        if (!response.ok) { say(await errorText(response)); return; }
        const box = container.querySelector('.ai-choice-members');
        renderMembers(box, (await response.json()).members);
      } else if (action === 'member-cap') {
        const row = event.target.closest('[data-member]');
        const raw = row.querySelector('input').value.trim();
        const response = await send(`/api/ai-budget/members/${encodeURIComponent(row.dataset.member)}`, 'PUT',
          { admin_cap_usd: raw === '' ? null : Number(raw) });
        say(response.ok ? `Saved the cap for ${row.dataset.member}.` : await errorText(response));
      }
    });
  }
  return api('/api/ai-budget').then(async response => show(response.ok ? await response.json() : { error: await errorText(response) }));
}
