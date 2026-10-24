// Exodus shared spaces in the Library's Documents tab: a "Family · by dad"
// tag on shared documents and "Share to" choices in a document's ⋯ menu.
// Members can open and edit shared documents; only the owner can archive,
// delete or re-share them.
let cache = null;
let loading = null;

export function ensureDocSpaces({ fetchImpl = globalThis.fetch, force = false } = {}) {
  if (cache && !force) return Promise.resolve(cache);
  if (!loading || force) {
    loading = fetchImpl('/api/spaces', { credentials: 'same-origin' })
      .then(r => (r.ok ? r.json() : { me: null, spaces: [] }))
      .catch(() => ({ me: null, spaces: [] }))
      .then(data => {
        cache = { me: data.me || null, spaces: Array.isArray(data.spaces) ? data.spaces : [] };
        return cache;
      });
  }
  return loading;
}

export function _resetDocSpacesForTests() {
  cache = null;
  loading = null;
}

/** True when the signed-in person owns the document (or spaces aren't in use). */
export function ownsDocument(doc) {
  return !cache?.me || !doc?.owner || doc.owner === cache.me;
}

/** Text for the meta line of a shared document, or "" for a personal one. */
export function sharedLabel(doc) {
  if (!doc?.space_id) return '';
  const space = (cache?.spaces || []).find(s => s.id === doc.space_id);
  const name = space ? space.name : 'a space';
  return ownsDocument(doc) ? `Shared in ${name}` : `${name} · by ${doc.owner}`;
}

/**
 * Append "Share to" choices to a document's dropdown (owner only).
 * `save(spaceId)` resolves on success or throws an Error whose message is
 * shown to the person (e.g. "PDF documents can't be shared yet").
 */
export function addDocShareItems(dropdown, doc, { close, save, onSaved, toast, icon = '' } = {}) {
  const spaces = (cache?.spaces || []).filter(s => s.role);
  if (!spaces.length || !ownsDocument(doc)) return;
  const divider = document.createElement('div');
  divider.className = 'dropdown-divider';
  const title = document.createElement('div');
  title.className = 'doclib-share-title';
  title.textContent = 'Share to';
  dropdown.append(divider, title);
  for (const choice of [{ id: '', name: 'Only me' }, ...spaces.map(s => ({ id: s.id, name: s.name }))]) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'dropdown-item-compact doclib-share-item';
    item.style.cssText = 'background:none;border:none;width:100%;';
    item.dataset.shareSpace = choice.id;
    const current = (doc.space_id || '') === choice.id;
    item.setAttribute('aria-pressed', String(current));
    item.innerHTML = `<span class="dropdown-icon">${current ? '✓' : icon}</span><span></span>`;
    item.lastChild.textContent = choice.name;
    item.addEventListener('click', async event => {
      event.stopPropagation();
      close?.();
      if (current) return;
      try {
        await save(choice.id);
        doc.space_id = choice.id || null;
        toast?.(choice.id ? `Shared with ${choice.name}` : 'Now only you can see this document');
        onSaved?.();
      } catch (error) {
        toast?.(error?.message || 'Could not change who can see this document', true);
      }
    });
    dropdown.append(item);
  }
}

/** PUT /api/spaces/documents/{id}; throws with the server's reason. */
export async function saveDocumentSpace(docId, spaceId, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(`/api/spaces/documents/${encodeURIComponent(docId)}`, {
    method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ space_id: spaceId }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not change who can see this document');
  }
  return response.json();
}
