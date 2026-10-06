// Extend the existing Users panel; no duplicate account system or email sender.
let initialized = false;
const el = id => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch('/api/auth/' + path, {
    credentials: 'same-origin', cache: 'no-store', ...options,
    headers: {'Content-Type': 'application/json', ...options.headers},
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || 'The request failed. Please try again.');
  return body;
}

export async function loadInvitations() {
  const list = el('team-invitations');
  if (!list) return;
  try {
    const {invitations} = await request('invitations');
    list.replaceChildren();
    if (!invitations.length) { list.textContent = 'No pending invitations.'; return; }
    for (const invite of invitations) {
      const row = document.createElement('div');
      row.className = 'admin-toggle-row';
      const label = document.createElement('span');
      label.textContent = `${invite.username} · expires ${new Date(invite.expires * 1000).toLocaleDateString()}`;
      const revoke = document.createElement('button');
      revoke.type = 'button'; revoke.className = 'admin-btn-sm'; revoke.textContent = 'Revoke';
      revoke.setAttribute('aria-label', 'Revoke invitation for ' + invite.username);
      revoke.addEventListener('click', async () => {
        revoke.disabled = true;
        try {
          await request('invitations/' + encodeURIComponent(invite.id), {method: 'DELETE'});
          el('team-invite-result').hidden = true;
          el('team-invite-link').value = '';
          await loadInvitations();
        } catch (error) { el('team-invite-status').textContent = error.message; revoke.disabled = false; }
      });
      row.append(label, revoke); list.append(row);
    }
  } catch (error) { list.textContent = error.message; }
}

export function initTeamInvitations() {
  if (initialized || !el('team-create-invite')) return;
  initialized = true;
  el('team-create-invite').addEventListener('click', async () => {
    const button = el('team-create-invite'), status = el('team-invite-status');
    status.textContent = ''; button.disabled = true;
    try {
      const invite = await request('invitations', {
        method: 'POST', body: JSON.stringify({username: el('team-invite-username').value.trim()}),
      });
      const link = new URL('login', window.location.href.split('#')[0]);
      link.hash = new URLSearchParams({invite: invite.token, username: invite.username}).toString();
      el('team-invite-link').value = link.href;
      el('team-invite-result').hidden = false;
      status.textContent = 'Invitation created. Copy it now and share it privately. No email has been sent.';
      el('team-invite-username').value = '';
      await loadInvitations();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  el('team-copy-invite').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(el('team-invite-link').value); el('team-invite-status').textContent = 'Invitation copied.'; }
    catch { el('team-invite-link').select(); el('team-invite-status').textContent = 'Select and copy the invitation link above.'; }
  });
}
