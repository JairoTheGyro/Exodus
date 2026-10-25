// Settings → Account → Move to Exodus: upload an export from Google, Apple or
// Microsoft, see what's in it, then import the parts you choose.
// Talks to /api/move-in (src/move_in.py).
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

const GUIDES = [
  ['Google', [
    'Go to takeout.google.com and choose Calendar, Contacts, Keep and Drive (and anything else you want).',
    'Choose a .zip export split into 2 GB parts, then download every part.',
    'Upload one part at a time here.',
  ]],
  ['Apple (iCloud)', [
    'Contacts: on icloud.com open Contacts, select all, then Export vCard.',
    'Calendars: in the Calendar app on a Mac, choose File → Export, or share a calendar and download the .ics file.',
    'Files: download them from iCloud Drive as a .zip.',
  ]],
  ['Microsoft (Outlook)', [
    'Calendar: in Outlook on the web, Settings → Calendar → Shared calendars → publish, then download the .ics link; or export it from Outlook on a computer.',
    'Contacts: People → Manage contacts → Export contacts (a .csv file).',
    'Files: download from OneDrive as a .zip.',
  ]],
];

const mb = bytes => `${Math.max(1, Math.round((bytes || 0) / 1024 / 1024))} MB`;

export function renderStart(container, doc = container.ownerDocument || document) {
  container.replaceChildren();
  const guides = el(doc, 'div', { className: 'move-in-guides' });
  for (const [name, steps] of GUIDES) {
    const list = el(doc, 'ol');
    for (const step of steps) list.append(el(doc, 'li', { text: step }));
    guides.append(el(doc, 'details', {}, el(doc, 'summary', { text: `From ${name}` }), list));
  }
  const input = el(doc, 'input', { type: 'file', className: 'move-in-file', accept: '.zip,.ics,.vcf,.csv', 'aria-label': 'Export file' });
  container.append(guides,
    el(doc, 'div', { className: 'move-in-row' }, input,
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { moveIn: 'scan' }, text: 'Look inside' })),
    el(doc, 'progress', { className: 'move-in-progress', max: '100', value: '0', hidden: '' }),
    el(doc, 'p', { className: 'move-in-msg admin-toggle-sub', role: 'status' }));
}

export function renderFound(container, scan, doc = container.ownerDocument || document) {
  container.replaceChildren();
  const s = scan.summary;
  const box = el(doc, 'div', { className: 'move-in-found' }, el(doc, 'p', { className: 'move-in-title', text: `Found in ${scan.filename}:` }));
  const choice = (key, label, count, disabledReason) => {
    const id = `move-in-${key}`;
    const check = el(doc, 'input', { type: 'checkbox', id, dataset: { choose: key } });
    check.checked = !!count && !disabledReason;
    check.disabled = !count || !!disabledReason;
    return el(doc, 'label', { className: 'move-in-choice', for: id }, check,
      el(doc, 'span', { text: `${label}: ${count}` + (disabledReason ? ` (${disabledReason})` : '') }));
  };
  box.append(
    choice('calendars', 'Calendars', s.calendars.length),
    choice('contacts', 'Contact files', s.contacts, s.contacts_need_admin ? 'only the admin can import contacts' : ''),
    choice('notes', 'Google Keep notes', s.keep_notes),
    choice('files', `Files (${mb(s.files_bytes)})`, s.files),
  );
  const notes = [];
  if (s.mail) notes.push('Mail archives aren’t imported: connect the email account in Settings → Email instead.');
  if (s.photos) notes.push(`Photos left out for now: ${s.photos}.`);
  if (s.office) notes.push(`Word, Excel or PowerPoint files left out: ${s.office}. Save them as PDF to bring them in.`);
  if (s.skipped.length) notes.push(`Other items skipped: ${s.skipped.length}.`);
  for (const text of notes) box.append(el(doc, 'p', { className: 'admin-toggle-sub', text }));
  box.append(el(doc, 'div', { className: 'move-in-row' },
    el(doc, 'button', { type: 'button', className: 'admin-btn-add', dataset: { moveIn: 'import' }, text: 'Import' }),
    el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { moveIn: 'cancel' }, text: 'Cancel' })));
  box.append(el(doc, 'p', { className: 'move-in-msg admin-toggle-sub', role: 'status' }));
  container.append(box);
}

export function renderDone(container, report, doc = container.ownerDocument || document) {
  container.replaceChildren();
  const lines = [];
  for (const cal of report.calendars || []) {
    lines.push(cal.error ? `${cal.file}: ${cal.error}` : `Calendar “${cal.calendar}”: ${cal.imported} events added`);
  }
  if (report.contacts) lines.push(`Contacts: ${report.contacts.imported} added`);
  if (report.notes) lines.push(`Notes: ${report.notes.imported} added`);
  if (report.files?.imported) lines.push(`Files: ${report.files.imported} added to Library`);
  if (report.files?.skipped?.length) lines.push(`Files skipped: ${report.files.skipped.length}`);
  const list = el(doc, 'ul', { className: 'move-in-done' });
  for (const line of lines.length ? lines : ['Nothing new was found to import.']) list.append(el(doc, 'li', { text: line }));
  container.append(el(doc, 'p', { className: 'move-in-title', text: 'Done.' }), list);
  for (const message of report.messages || []) container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: message }));
  container.append(el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { moveIn: 'again' }, text: 'Import another export' }));
}

function defaultUpload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/move-in/scan');
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-Filename', file.name);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = event => { if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100)); };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(typeof body.detail === 'string' ? body.detail : 'The upload didn’t work. Try again.'));
    };
    xhr.onerror = () => reject(new Error('The upload didn’t work. Check the connection and try again.'));
    xhr.send(file);
  });
}

/** Mount the Move to Exodus card; safe to call every time Account opens. */
export function mountMoveIn(container, {
  upload = defaultUpload,
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
} = {}) {
  if (!container) return;
  let scan = null;
  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('click', async event => {
      const action = event.target.closest?.('[data-move-in]')?.dataset.moveIn;
      if (!action) return;
      const say = text => { const msg = container.querySelector('.move-in-msg'); if (msg) msg.textContent = text; };
      if (action === 'scan') {
        const file = container.querySelector('.move-in-file')?.files?.[0];
        if (!file) { say('Choose your export file first.'); return; }
        const bar = container.querySelector('.move-in-progress');
        bar.hidden = false;
        event.target.disabled = true;
        say('Uploading…');
        try {
          scan = await upload(file, percent => { bar.value = percent; if (percent >= 100) say('Looking inside…'); });
          renderFound(container, scan);
        } catch (error) {
          event.target.disabled = false;
          bar.hidden = true;
          say(error.message);
        }
      } else if (action === 'import') {
        const chosen = key => !!container.querySelector(`[data-choose="${key}"]`)?.checked;
        event.target.disabled = true;
        say('Importing… this can take a few minutes for big exports.');
        const response = await api('/api/move-in/import', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: scan.token, calendars: chosen('calendars'), contacts: chosen('contacts'), notes: chosen('notes'), files: chosen('files') }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) { event.target.disabled = false; say(typeof body.detail === 'string' ? body.detail : 'The import didn’t work.'); return; }
        renderDone(container, body);
      } else if (action === 'cancel') {
        if (scan) await api(`/api/move-in/${encodeURIComponent(scan.token)}`, { method: 'DELETE' }).catch(() => {});
        scan = null;
        renderStart(container);
      } else if (action === 'again') {
        scan = null;
        renderStart(container);
      }
    });
  }
  if (!container.querySelector('.move-in-file, .move-in-found, .move-in-done')) renderStart(container);
}
