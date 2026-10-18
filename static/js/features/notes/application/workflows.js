/** Notes CRUD, optimistic archive and in-memory undo workflows. */
export function createNotesWorkflows({
  app,
  api,
  effects
}) {
  const state = app.state;
  const _undoStack = [];
  const _renderNotes = effects.render;
  let _notesFetchSequence = 0;
  let _archiveRefreshRunning = false;
  let _archiveRefreshPending = false;

  async function _patchNote(id, patch) {
    const saved = await api.patchNote(id, patch);
    if (Object.hasOwn(patch, 'archived') || Object.hasOwn(patch, 'is_archived')) {
      void _refreshAfterArchiveChange();
    }
    return saved;
  }
  const uiModule = effects;
  function _pushUndo(entry) {
    _undoStack.push(entry);
    if (_undoStack.length > 20) _undoStack.shift();
  }

  function _popAndRunUndo() {
    const entry = _undoStack.pop();
    if (entry) entry.run();
    return !!entry;
  }

  function _undoArchive(note, prevIdx) {
    // Re-insert at original position and clear archived flag on the server.
    const safeIdx = Math.min(Math.max(prevIdx, 0), state.notes.length);
    app.insertNoteAt(safeIdx, { ...note, archived: false });
    _renderNotes();
    _patchNote(note.id, { archived: false }).catch(() => {
      // Roll back local insertion if the server refuses
      const i = state.notes.findIndex(n => n.id === note.id);
      if (i >= 0) app.removeNoteAt(i);
      _renderNotes();
      uiModule.showError('Undo failed');
    });
  }

  function _archiveNoteById(id, { card = null, celebrate = false } = {}) {
    if (!id) return false;
    const idx = state.notes.findIndex(n => n.id === id);
    if (idx < 0) return false;
    const note = state.notes[idx];
    if (celebrate && card && note) effects.celebrateArchive(note, card);
    const removed = app.removeNoteAt(idx);
    app.setEditingId(null);
    _renderNotes();
    const undo = () => _undoArchive(removed, idx);
    _pushUndo({ label: 'archive', run: undo });
    _patchNote(id, { archived: true }).then(() => {
      effects.archived(undo);
    }).catch(() => {
      app.insertNoteAt(idx, removed);
      _renderNotes();
      uiModule.showError('Failed to archive');
    });
    return true;
  }

  // A fetch only replaces the shared list when it is the newest request and
  // still matches the selected (active/archived) view, so a slow response from
  // a previous view can never overwrite the current one. `apply: false` reads
  // without touching shared state (e.g. badge counts while viewing the archive).
  async function _fetchNotes({ archived = state.showingArchived, apply = true } = {}) {
    const sequence = apply ? ++_notesFetchSequence : null;
    const current = () => apply && sequence === _notesFetchSequence && archived === state.showingArchived;
    if (apply) app.setLoading(true);
    try {
      const res = await api.listNotes(archived);
      if (!res.ok) { if (current()) app.replaceNotes([]); return []; }
      const data = await res.json();
      const notes = data.notes || data || [];
      if (current()) app.replaceNotes(notes);
      return notes;
    } catch (e) {
      console.error('Failed to fetch notes:', e);
      if (current()) app.replaceNotes([]);
      return [];
    } finally {
      if (apply && sequence === _notesFetchSequence) app.setLoading(false);
    }
  }

  async function _refreshAfterArchiveChange() {
    // A view toggle may have read before the write committed. Coalesce completion
    // refreshes (including bulk actions) and always reread the currently selected view.
    _archiveRefreshPending = true;
    if (_archiveRefreshRunning) return;
    _archiveRefreshRunning = true;
    try {
      while (_archiveRefreshPending && state.open) {
        _archiveRefreshPending = false;
        await _fetchNotes();
        if (state.open && !(effects.isEditing && effects.isEditing())) _renderNotes();
      }
    } finally {
      _archiveRefreshRunning = false;
      _archiveRefreshPending = false;
    }
  }

  function _saveNote(note) { return api.saveNote(note); }

  function _deleteNoteApi(id) { return api.deleteNote(id); }

  return { _pushUndo, _popAndRunUndo, _undoArchive, _archiveNoteById, _fetchNotes, _refreshAfterArchiveChange, _saveNote, _deleteNoteApi, _patchNote, undoCount: () => _undoStack.length };
}
