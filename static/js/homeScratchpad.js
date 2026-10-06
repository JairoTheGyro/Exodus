// One owner-scoped draft; local recovery protects edits while the server is offline.
// Revision conflicts always require an explicit choice instead of overwriting another tab.
export function createScratchpad({request, storage, owner, recoveryId = 'default', delay = 500, schedule = setTimeout, cancel = clearTimeout, uuid = () => crypto.randomUUID()}) {
  const key = `exodus:scratchpad:${encodeURIComponent(owner)}:${encodeURIComponent(recoveryId)}`;
  const listeners = new Set();
  let state = {text:'', revision:null, savedText:'', dirty:false, busy:false, error:'', conflict:null, recoveryAvailable:true, pending:null};
  let queue = Promise.resolve(), timer, disposed = false, editVersion = 0;
  try {
    const saved = JSON.parse(storage?.getItem(key) || 'null');
    if (saved && typeof saved.text === 'string' && (saved.revision === null || typeof saved.revision === 'string')) {
      editVersion = Number.isSafeInteger(saved.editVersion) ? saved.editVersion : 0;
      state = {...state, text:saved.text, revision:saved.revision, savedText:typeof saved.savedText === 'string' ? saved.savedText : '', dirty:true, pending:saved.pending || null};
    }
  } catch { state.recoveryAvailable = false; }
  const snapshot = () => ({...state, pending:state.pending && {...state.pending}});
  function emit() { for (const listener of listeners) listener(snapshot()); }
  function persist() {
    try {
      if (!storage) throw Error('Browser storage unavailable');
      if (state.dirty || state.pending || state.conflict) storage.setItem(key, JSON.stringify({text:state.text, revision:state.revision, savedText:state.savedText, pending:state.pending, editVersion}));
      else storage.removeItem(key);
      state.recoveryAvailable = true;
    } catch { state.recoveryAvailable = false; }
  }
  function remember() { state.dirty = state.text !== state.savedText; persist(); emit(); }
  function later() {
    cancel(timer);
    if (state.dirty && !state.conflict && !state.pending && !disposed) timer = schedule(() => flush().catch(() => {}), delay);
  }
  function serialized(fn) {
    const result = queue.catch(() => {}).then(async () => {
      state.busy = true; emit();
      try { return await fn(); }
      catch (error) { state.error = error.message || 'Could not save. Your draft is kept here.'; persist(); emit(); throw error; }
      finally { state.busy = false; emit(); }
    });
    queue = result;
    return result;
  }
  function reconcile(remote) {
    if (!remote || typeof remote.text !== 'string' || typeof remote.revision !== 'string') throw Error('Scratchpad response was incomplete.');
    if (!state.dirty && !state.pending && !state.conflict) {
      state.text = remote.text; state.savedText = remote.text; state.revision = remote.revision; state.conflict = null;
    } else if (remote.text === state.text) {
      state.savedText = remote.text; state.revision = remote.revision; state.conflict = null;
    } else if (remote.text === state.savedText) {
      state.revision = remote.revision; state.conflict = null;
    } else {
      state.conflict = remote;
    }
    remember();
  }
  async function fetchSaved() { reconcile(await request('/api/home/scratchpad')); }
  async function save() {
    if (state.pending) throw Error('A note save needs confirmation. Retry Save to Notes; your new edits are kept here.');
    if (state.revision === null) await fetchSaved();
    if (state.conflict) throw Error('This scratchpad changed in another window. Choose which version to keep.');
    while (state.text !== state.savedText) {
      const text = state.text;
      let result;
      try { result = await request('/api/home/scratchpad', {method:'PUT', body:{text, revision:state.revision}}); }
      catch (error) {
        const current = error.detail?.current;
        if (error.status === 409 && current) {
          if (current.text === text) result = current; // An earlier successful response may have been lost.
          else { state.conflict = current; throw Error('This scratchpad changed in another window. Your draft is preserved.'); }
        } else throw error;
      }
      state.revision = result.revision; state.savedText = text; state.error = ''; state.conflict = null; remember();
    }
  }
  function flush() { cancel(timer); return serialized(save); }
  function refresh() {
    return serialized(async () => {
      // A lost conversion response must be resolved with its original id before any new save.
      if (state.pending) return;
      await fetchSaved(); state.error = ''; emit(); later();
    });
  }
  function input(text) { editVersion++; state.text = text; state.error = ''; remember(); later(); }
  function convert() {
    cancel(timer);
    return serialized(async () => {
      if (!state.pending) {
        await save();
        if (!state.text.trim()) throw Error('Write something before saving a note.');
        state.pending = {request_id:uuid(), revision:state.revision, text:state.text, editVersion}; persist(); emit();
      }
      const pending = state.pending;
      let result;
      try { result = await request('/api/home/scratchpad/to-note', {method:'POST', body:{request_id:pending.request_id, revision:pending.revision}}); }
      catch (error) {
        if (error.status === 409 || error.status === 410 || error.status === 422) {
          state.pending = null;
          if (error.detail?.current) state.conflict = error.detail.current;
          else if (error.status === 410) { state.dirty = true; state.revision = null; try { await fetchSaved(); } catch { /* Keep local text if recovery fetch is also offline. */ } }
        }
        throw error;
      }
      state.pending = null;
      // The response is the authoritative post-conversion scratchpad; preserve newer local typing.
      if (state.text === pending.text && editVersion === pending.editVersion) state.text = result.text;
      state.savedText = result.text; state.revision = result.revision; state.conflict = null; state.error = '';
      remember(); later();
      return result;
    });
  }
  return {
    getState:snapshot, input, refresh, flush, convert,
    subscribe(listener) { listeners.add(listener); listener(snapshot()); return () => listeners.delete(listener); },
    resolve(choice) {
      return serialized(async () => {
        if (!state.conflict) return;
        const remote = state.conflict;
        state.revision = remote.revision; state.savedText = remote.text; state.conflict = null;
        if (choice === 'remote') state.text = remote.text;
        state.error = ''; remember();
        if (choice === 'local') await save();
      });
    },
    dispose() { disposed = true; cancel(timer); listeners.clear(); },
  };
}
