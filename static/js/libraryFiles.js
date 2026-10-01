/** Original files in Library. No preview processing, embeddings, or remote calls. */
import uiModule from './ui.js';

export function mountLibraryFiles(panel) {
  panel.innerHTML = `
    <p class="memory-desc">Keep original files on your Exodus server. Uploads stay local and are not analyzed by AI.</p>
    <button type="button" class="library-file-drop" aria-label="Upload files">Drop files here or click to upload</button>
    <input type="file" hidden multiple aria-label="Choose Library files" />
    <small class="library-file-help">PDF, TXT, MD, CSV and images.</small>
    <div class="library-file-toolbar"><span class="library-file-count"></span><button type="button" class="memory-toolbar-btn library-file-refresh">Refresh files</button></div>
    <p class="library-file-status" role="status" aria-live="polite"></p>
    <div class="library-file-list" role="list" aria-label="Uploaded files"></div>
    <button type="button" class="memory-toolbar-btn library-file-more" hidden>Load more files</button>`;
  const drop = panel.querySelector('.library-file-drop');
  const input = panel.querySelector('input');
  const list = panel.querySelector('.library-file-list');
  const status = panel.querySelector('.library-file-status');
  const more = panel.querySelector('.library-file-more');
  const refresh = panel.querySelector('.library-file-refresh');
  let files = [], total = 0, busy = false, loading = false, sequence = 0;
  let maxBytes = 25 * 1024 * 1024;
  let extensions = ['.pdf','.txt','.md','.csv','.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.svg','.avif','.ico'];
  input.accept = extensions.join(',');
  function bytes(value) {
    if (value < 1024) return `${value} B`;
    return value < 1024 * 1024 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  async function request(url, options) {
    const response = await fetch(url, {credentials:'same-origin', ...options});
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch (_) {}
      throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}). Please retry.`);
    }
    return response.json();
  }
  function setBusy(value) {
    busy = value;
    panel.setAttribute('aria-busy', String(value));
    drop.disabled = refresh.disabled = value;
    more.disabled = value;
    for (const button of list.querySelectorAll('button')) button.disabled = value;
  }
  function render() {
    list.replaceChildren();
    panel.querySelector('.library-file-count').textContent = `${total} file${total === 1 ? '' : 's'}`;
    if (!files.length) {
      const empty = document.createElement('p');
      empty.className = 'doclib-empty';
      empty.textContent = 'No uploaded files yet.';
      list.append(empty);
    }
    for (const file of files) {
      const row = document.createElement('div');
      row.className = 'library-file-row';
      row.setAttribute('role','listitem');
      const info = document.createElement('div');
      const name = document.createElement('strong');
      name.textContent = file.filename;
      const meta = document.createElement('small');
      const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(file.created_at) ? file.created_at : file.created_at + 'Z');
      meta.textContent = `${bytes(file.file_size)} · ${date.toLocaleString()} · ${file.mime_type}`;
      info.append(name, meta);
      const actions = document.createElement('div');
      actions.className = 'library-file-actions';
      if (!file.deletion_pending) {
        const link = document.createElement('a');
        link.href = `/api/documents/${encodeURIComponent(file.id)}/download`;
        link.download = file.filename;
        link.textContent = 'Download';
        link.setAttribute('aria-label', `Download ${file.filename}`);
        actions.append(link);
      } else {
        const pending = document.createElement('small');
        pending.textContent = 'Removal pending';
        info.append(pending);
      }
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'memory-toolbar-btn danger';
      remove.textContent = file.deletion_pending ? 'Retry delete' : 'Delete';
      remove.setAttribute('aria-label', `${remove.textContent} ${file.filename}`);
      remove.disabled = busy;
      remove.addEventListener('click', async () => {
        if (busy) return;
        const confirmed = await uiModule.styledConfirm(`Permanently delete “${file.filename}” from Library? This removes the stored file and cannot be undone.`, {confirmText:'Delete file', danger:true});
        if (!confirmed || busy) return;
        setBusy(true);
        try {
          await request(`/api/documents/${encodeURIComponent(file.id)}`,{method:'DELETE'});
          await load(true);
          status.textContent = 'File deleted.';
        } catch (error) {
          await load(true);
          status.textContent = error.message;
        } finally { setBusy(false); }
      });
      actions.append(remove);
      row.append(info,actions);
      list.append(row);
    }
    more.hidden = files.length >= total;
  }
  async function load(reset = true) {
    const ticket = ++sequence;
    loading = true;
    refresh.disabled = more.disabled = true;
    try {
      const result = await request(`/api/documents?offset=${reset ? 0 : files.length}&limit=50`);
      if (ticket !== sequence || !panel.isConnected) return;
      files = reset ? result.files : files.concat(result.files);
      total = result.total;
      maxBytes = result.max_upload_bytes;
      extensions = result.extensions;
      input.accept = extensions.join(',');
      panel.querySelector('.library-file-help').textContent = `PDF, TXT, MD, CSV and images · up to ${bytes(maxBytes)} per file.`;
      render();
    } catch (error) { status.textContent = error.message; }
    finally {
      if (ticket === sequence) { loading = false; refresh.disabled = more.disabled = busy; }
    }
  }
  async function upload(selected) {
    if (busy || !selected.length) return;
    setBusy(true);
    const failures = [];
    let saved = 0;
    for (const file of selected) {
      status.textContent = `Uploading ${file.name}…`;
      try {
        const extension = '.' + file.name.split('.').pop().toLowerCase();
        if (!extensions.includes(extension)) throw new Error('Unsupported file format.');
        if (!file.size) throw new Error('File is empty.');
        if (file.size > maxBytes) throw new Error(`File exceeds ${bytes(maxBytes)}.`);
        const body = new FormData();
        body.append('file',file);
        await request('/api/documents/upload',{method:'POST',body});
        saved++;
      } catch (error) { failures.push(`${file.name}: ${error.message}`); }
    }
    await load(true);
    setBusy(false);
    status.textContent = `${saved} file${saved === 1 ? '' : 's'} uploaded.` + (failures.length ? ' ' + failures.join(' ') : '');
  }
  drop.addEventListener('click', () => input.click());
  input.addEventListener('change', () => { const selected = [...input.files]; input.value = ''; upload(selected); });
  for (const event of ['dragenter','dragover']) drop.addEventListener(event, e => {
    e.preventDefault(); e.stopPropagation();
    if (!busy) { drop.classList.add('drag-over'); e.dataTransfer.dropEffect = 'copy'; }
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); e.stopPropagation(); drop.classList.remove('drag-over');
    upload([...e.dataTransfer.files]);
  });
  refresh.addEventListener('click', () => { if (!loading && !busy) { status.textContent=''; load(true); } });
  more.addEventListener('click', () => { if (!loading && !busy) load(false); });
  return () => { if (!busy && !loading) load(true); };
}
