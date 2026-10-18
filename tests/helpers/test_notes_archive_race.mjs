// Exodus archive-race guarantees, exercised on the real Notes state, workflow
// and reminder modules with a controllable fake API.
import assert from 'node:assert/strict';
import { createNotesState } from '../../static/js/features/notes/application/state.js';
import { createNotesWorkflows } from '../../static/js/features/notes/application/workflows.js';
import { createNotesReminders } from '../../static/js/features/notes/application/reminders.js';

function fixture() {
  const requests = [], badges = [], renders = [];
  const app = createNotesState({});
  app.setOpen(true);
  const ids = () => app.state.notes.map(n => n.id).join(',');
  const pending = (kind, detail) => new Promise(resolve => requests.push({ kind, ...detail, resolve }));
  const api = {
    listNotes: archived => pending('list', { archived }),
    patchNote: (id, patch) => pending('patch', { id, patch }),
    saveNote: () => Promise.resolve({}),
    deleteNote: () => Promise.resolve(),
  };
  const workflows = createNotesWorkflows({
    app, api,
    effects: {
      render: () => renders.push(ids()), isEditing: () => false,
      showError: () => {}, archived: () => {}, celebrateArchive: () => {},
    },
  });
  const reminders = createNotesReminders({
    app, api,
    persistence: { getItem: () => null, setItem: () => {}, _loadFiredReminders: () => new Set(), _saveFiredReminders: () => {} },
    notifications: {}, clock: { now: () => Date.now() },
    scheduler: { setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {} },
    effects: { badge: notes => badges.push(notes) },
    fetchNotes: opts => workflows._fetchNotes(opts),
    isNoteFullyDone: () => false, hasItems: () => false, dismissedKey: 'test-dismissed',
  });
  return { app, ids, workflows, reminders, requests, badges, renders };
}
const listResponse = notes => ({ ok: true, json: async () => ({ notes }) });
const flush = () => new Promise(resolve => setImmediate(resolve));

// Late active-list GET must not replace a newer Archive result.
const a = fixture();
const first = a.workflows._fetchNotes();
a.app.setShowingArchived(true);
const second = a.workflows._fetchNotes();
a.requests[1].resolve(listResponse([{ id: 'archived', archived: true }])); await second;
a.requests[0].resolve(listResponse([{ id: 'active' }])); await first;
assert.equal(a.ids(), 'archived'); assert.equal(a.app.state.showingArchived, true);

// Most recent request wins even within the same view.
const b = fixture();
const older = b.workflows._fetchNotes(), newer = b.workflows._fetchNotes();
b.requests[1].resolve(listResponse([{ id: 'new' }])); await newer;
b.requests[0].resolve(listResponse([{ id: 'old' }])); await older;
assert.equal(b.ids(), 'new');

// Archive toggled before the PUT completes: a premature empty GET, then a
// post-write refresh of the currently selected (archive) view.
const c = fixture();
c.app.replaceNotes([{ id: 'groceries', title: 'Groceries' }]);
assert.equal(c.workflows._archiveNoteById('groceries'), true);
assert.equal(c.requests[0].kind, 'patch');
assert.deepEqual(c.requests[0].patch, { archived: true });
c.app.setShowingArchived(true);
const prematurelyRead = c.workflows._fetchNotes();
c.requests[1].resolve(listResponse([])); await prematurelyRead;
assert.equal(c.ids(), '');
c.requests[0].resolve({ id: 'groceries', archived: true }); await flush();
assert.equal(c.requests[2].kind, 'list'); assert.equal(c.requests[2].archived, true);
c.requests[2].resolve(listResponse([{ id: 'groceries', archived: true }])); await flush();
assert.equal(c.ids(), 'groceries'); assert.equal(c.renders.at(-1), 'groceries');

// Badge refresh reads active reminders without switching or replacing Archive.
const d = fixture();
d.app.setShowingArchived(true);
d.app.replaceNotes([{ id: 'keep-archived', archived: true }]);
const badge = d.reminders.refreshDueBadge({ force: true });
assert.equal(d.app.state.showingArchived, true);
assert.equal(d.requests[0].archived, false);
d.requests[0].resolve(listResponse([{ id: 'active-reminder' }])); await badge;
assert.equal(d.app.state.showingArchived, true); assert.equal(d.ids(), 'keep-archived');
assert.equal(d.badges[0][0].id, 'active-reminder');
console.log('PASS: Archive post-save refresh, stale list request protection, same-view ordering, badge/view independence.');
