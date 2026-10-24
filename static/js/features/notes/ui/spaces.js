/** Exodus shared spaces in Notes: the "Shared in …" badge and the Share menu.
 *
 * Spaces come from /api/spaces (Settings → Spaces creates them). A note in a
 * space is visible to every member; only its owner can move it. */
let cache = null; // { me, spaces }
let loading = null;
const waiting = new Set();

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Load spaces once; call `onReady` (e.g. a re-render) when they arrive. */
export function ensureSpaces(onReady, { force = false, fetchImpl = globalThis.fetch } = {}) {
  if (cache && !force) return cache;
  if (onReady) waiting.add(onReady);
  if (!loading || force) {
    loading = fetchImpl('/api/spaces', { credentials: 'same-origin' })
      .then(r => (r.ok ? r.json() : { me: null, spaces: [] }))
      .catch(() => ({ me: null, spaces: [] }))
      .then(data => {
        cache = { me: data.me || null, spaces: Array.isArray(data.spaces) ? data.spaces : [] };
        const callbacks = [...waiting];
        waiting.clear();
        callbacks.forEach(fn => { try { fn(); } catch (_) {} });
        return cache;
      });
  }
  return cache;
}

export function _resetSpacesForTests(value = null) {
  cache = value;
  loading = null;
  waiting.clear();
}

/** Spaces the person belongs to (managers who aren't members can't share into it). */
export function memberSpaces() {
  return (cache?.spaces || []).filter(space => space.role);
}

/** Small badge for a shared note's card; empty for personal notes. */
export function spaceBadgeHtml(note) {
  if (!note?.space_id) return '';
  const space = (cache?.spaces || []).find(s => s.id === note.space_id);
  const name = space ? space.name : 'a space';
  const by = cache?.me && note.owner && note.owner !== cache.me ? ` · by ${note.owner}` : '';
  return `<div class="note-card-space" data-space-id="${esc(note.space_id)}" title="Everyone in ${esc(name)} can see and edit this">`
    + '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'
    + `<span>${esc(name)}${esc(by)}</span></div>`;
}

/** Whether this person may move the note between spaces (its owner only). */
export function canMoveNote(note) {
  return !cache?.me || !note?.owner || note.owner === cache.me;
}

/**
 * Add "Share to…" choices to a note's ⋯ menu. `save(spaceId)` sends the change
 * ("" = personal) and resolves to the updated note or throws.
 */
export function addShareItems(menu, note, { close, save, onSaved, toast }) {
  const spaces = memberSpaces();
  if (!spaces.length || !canMoveNote(note)) return;
  const group = document.createElement('div');
  group.className = 'ncm-share-group';
  group.innerHTML = '<div class="ncm-share-title">Share to</div>';
  const choices = [{ id: '', name: 'Only me' }, ...spaces.map(s => ({ id: s.id, name: s.name }))];
  for (const choice of choices) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ncm-item ncm-share';
    button.dataset.shareSpace = choice.id;
    const current = (note.space_id || '') === choice.id;
    button.setAttribute('aria-pressed', String(current));
    button.innerHTML = `<span class="ncm-share-check">${current ? '✓' : ''}</span><span></span>`;
    button.lastChild.textContent = choice.name;
    button.addEventListener('click', async () => {
      close();
      if (current) return;
      try {
        const updated = await save(choice.id);
        note.space_id = updated?.space_id ?? (choice.id || null);
        onSaved?.();
        toast?.(choice.id ? `Shared with ${choice.name}` : 'Now only you can see this note');
      } catch (_) {
        toast?.('Could not change who can see this note');
      }
    });
    group.append(button);
  }
  menu.append(group);
}
