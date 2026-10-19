// Exodus Notes JSON import, exercised on the real Notes toolbar module.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createToolbar } from '../../static/js/features/notes/ui/toolbar.js';

const panelSource = readFileSync('static/js/features/notes/ui/panel.js', 'utf8');
assert.match(panelSource, /id="notes-import-file" type="file" accept="\.json,application\/json" hidden/);
assert.match(panelSource, /id="notes-import-status" role="status" aria-live="polite"/);
assert.doesNotMatch(panelSource, /API_BASE/, 'Export links must not depend on an undefined API_BASE');

// wireToolbar also looks up search/archive/view controls; none exist here.
globalThis.document = { getElementById: () => null, querySelector: () => null };

function fixture({ editing = false, response = { ok: true, json: async () => ({ imported: 2, archived: 1, warnings: [{ message: 'Images omitted.', count: 1 }] }) } } = {}) {
  const element = () => ({ events: {}, disabled: false, hidden: true, textContent: '', value: 'selected', attrs: {},
    addEventListener(name, handler) { this.events[name] = handler; }, click() { this.clicked = true; },
    setAttribute(k, v) { this.attrs[k] = v; }, focus() {}, querySelectorAll: () => [] });
  const button = element(), input = element(), status = element(), exportBtn = element(), exportOptions = element();
  const uploads = [], toasts = [];
  let fetched = 0, rendered = 0;
  const pane = { querySelector(selector) { return {
    '#notes-export-toggle': exportBtn, '#notes-export-options': exportOptions,
    '#notes-import-select': button, '#notes-import-file': input, '#notes-import-status': status,
    '.note-form': editing ? {} : null }[selector]; } };
  const toolbar = createToolbar({
    app: { setSearchQuery() {}, setShowingArchived() {}, setActiveLabel() {}, setActiveFilter() {}, clearSelection() {}, setViewMode() {} },
    state: { open: true, showingArchived: false, viewMode: 'list' },
    persistence: { setItem() {} },
    api: { importJson: async file => { uploads.push(file); return response; } },
    showToast: text => toasts.push(text),
    _renderNotes: () => { rendered++; }, _fetchNotes: async () => { fetched++; }, _applyMasonry() {},
  });
  toolbar.wireToolbar(pane);
  return { button, input, status, exportBtn, exportOptions, uploads, toasts, counts: () => ({ fetched, rendered }) };
}

const normal = fixture();
assert.equal(normal.uploads.length, 0, 'No import or network request before file selection');
normal.exportBtn.events.click(); assert.equal(normal.exportOptions.hidden, false);
normal.button.events.click(); assert.equal(normal.input.clicked, true);
const file = { size: 300, name: 'exodus-notes.json' }; normal.input.files = [file];
await normal.input.events.change();
assert.equal(normal.uploads[0], file, 'Send the selected file directly, not an unbounded parsed copy');
assert.match(normal.status.textContent, /Imported 2 notes as new copies \(1 archived\)/);
assert.match(normal.status.textContent, /Images omitted/);
assert.deepEqual(normal.counts(), { fetched: 1, rendered: 1 });
assert.equal(normal.input.value, ''); assert.equal(normal.button.disabled, false);

const editing = fixture({ editing: true }); editing.input.files = [file]; await editing.input.events.change();
assert.deepEqual(editing.counts(), { fetched: 1, rendered: 0 }, 'Do not destroy an unsaved note editor');

const large = fixture(); large.input.files = [{ size: 10 * 1024 * 1024 + 1 }]; await large.input.events.change();
assert.equal(large.uploads.length, 0); assert.match(large.status.textContent, /10 MiB/);
assert.equal(large.button.disabled, false);

const invalid = fixture({ response: { ok: false, json: async () => ({ detail: 'Note 2: Invalid checklist.' }) } });
invalid.input.files = [file]; await invalid.input.events.change();
assert.match(invalid.status.textContent, /Note 2/); assert.deepEqual(invalid.counts(), { fetched: 0, rendered: 0 });
assert.equal(invalid.toasts.length, 0);

// The import endpoint itself: authenticated same-origin POST of the raw file.
const { createNotesApi } = await import('../../static/js/features/notes/infrastructure/http.js');
const seen = [];
const realApi = createNotesApi({ origin: 'http://local.test', request: async (url, options) => { seen.push({ url, options }); return { ok: true }; } });
await realApi.importJson(file);
assert.equal(seen[0].url, 'http://local.test/api/notes/import/json');
assert.equal(seen[0].options.method, 'POST'); assert.equal(seen[0].options.credentials, 'same-origin');
assert.equal(seen[0].options.body, file);
console.log('PASS: Notes import explicit file choice, direct bounded upload, authenticated endpoint, counts/warnings, local refresh, draft preservation, size/error handling.');
