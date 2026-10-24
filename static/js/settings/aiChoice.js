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
    // Filled in by mountAiChoice from /api/my-ai (your private accounts).
    container.append(el(doc, 'div', { className: 'ai-own-accounts' }));
    if (data.is_admin && !compact) {
      container.append(el(doc, 'div', { className: 'ai-choice-row' },
        el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'add-account' }, text: 'Advanced: all AI connections' })));
    }
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

/** Your connected accounts plus the "connect one" form. */
export function renderOwnAccounts(box, { accounts = [], providers = [] } = {}, doc = box.ownerDocument || document) {
  box.replaceChildren();
  const list = el(doc, 'ul', { className: 'ai-own-list' });
  for (const account of accounts) {
    list.append(el(doc, 'li', { dataset: { account: account.id } },
      el(doc, 'span', { text: `${account.provider_name || account.name} · ${account.models} models` }),
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm admin-btn-danger', dataset: { aiAction: 'remove-account' }, text: 'Remove' })));
  }
  if (accounts.length) box.append(list);
  const select = el(doc, 'select', { className: 'ai-own-provider', 'aria-label': 'AI provider' });
  for (const provider of providers) select.append(el(doc, 'option', { value: provider.id, text: provider.name }));
  const key = el(doc, 'input', { type: 'password', className: 'ai-own-key', placeholder: 'Paste your API key', autocomplete: 'off', 'aria-label': 'API key' });
  box.append(el(doc, 'div', { className: 'ai-choice-row ai-own-form' }, select, key,
    el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { aiAction: 'connect-account' }, text: 'Connect' })));
  box.append(el(doc, 'p', { className: 'admin-toggle-sub', text: 'Only you can use and see this account. Exodus stores the key encrypted and never shows it again. Create the key on the provider\u2019s website; you pay them directly.' }));
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
  const loadOwn = async () => {
    const box = container.querySelector('.ai-own-accounts');
    if (!box) return;
    const [accounts, providers] = await Promise.all([
      api('/api/my-ai/accounts').then(r => (r.ok ? r.json() : { accounts: [] })).catch(() => ({ accounts: [] })),
      api('/api/my-ai/providers').then(r => (r.ok ? r.json() : { providers: [] })).catch(() => ({ providers: [] })),
    ]);
    renderOwnAccounts(box, { accounts: accounts.accounts || [], providers: providers.providers || [] });
  };
  const show = data => { latest = data; renderAiChoice(container, data, { compact }); loadOwn(); return data; };
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
      } else if (action === 'connect-account') {
        const box = container.querySelector('.ai-own-accounts');
        const provider = box.querySelector('.ai-own-provider')?.value;
        const key = box.querySelector('.ai-own-key');
        if (!key.value.trim()) { key.focus(); return; }
        event.target.disabled = true;
        say('Checking the key with the provider…');
        const response = await send('/api/my-ai/accounts', 'POST', { provider, api_key: key.value });
        event.target.disabled = false;
        if (!response.ok) { say(await errorText(response)); return; }
        key.value = '';
        await loadOwn();
        say('Connected. Its models now appear in your model picker.');
      } else if (action === 'remove-account') {
        const id = event.target.closest('[data-account]')?.dataset.account;
        const response = await api(`/api/my-ai/accounts/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!response.ok) { say(await errorText(response)); return; }
        await loadOwn();
        say('Removed.');
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
