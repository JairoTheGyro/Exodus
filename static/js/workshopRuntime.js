export const WORKSHOP_MARKER = '<!-- sovereign-workshop:v1 -->';
export const isWorkshopSource = source => String(source || '').trimStart().startsWith(WORKSHOP_MARKER);

export async function workshopRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  return body;
}

// Return cleanup immediately, including while initial data is still loading.
export function mountWorkshopPreview(iframe, docId, source) {
  const channel = crypto.randomUUID();
  let disposed = false, ready = false, snapshot, failure, queue = Promise.resolve();
  const send = message => { if (!disposed) iframe.contentWindow?.postMessage({ ...message, channel }, '*'); };
  const start = () => {
    if (!ready || disposed) return;
    if (failure) send({type: 'error', error: failure});
    else if (snapshot) send({type: 'init', source, data: snapshot.data});
  };
  const listener = event => {
    if (disposed || event.source !== iframe.contentWindow) return;
    const msg = event.data;
    if (msg?.type === 'workshop-frame-ready') { ready = true; start(); return; }
    if (!snapshot || msg?.channel !== channel || msg.type !== 'save') return;
    // docId comes only from the editor, never from generated code.
    queue = queue.then(async () => {
      if (disposed) return;
      try {
        if (!msg.data || typeof msg.data !== 'object' || Array.isArray(msg.data)) throw new Error('Save a JSON object.');
        if (new TextEncoder().encode(JSON.stringify(msg.data)).length > 100000) throw new Error('App data exceeds 100 KB.');
        snapshot = await workshopRequest(`/api/workshop/${encodeURIComponent(docId)}/state`, {
          method: 'PUT', body: JSON.stringify({revision: snapshot.revision, data: msg.data}),
        });
        send({type: 'saved', id: msg.id, data: snapshot.data});
      } catch (error) { send({type: 'saved', id: msg.id, error: error.message}); }
    });
  };
  window.addEventListener('message', listener);
  iframe.removeAttribute('srcdoc');
  iframe.setAttribute('sandbox', 'allow-scripts');
  iframe.src = '/static/workshop-frame.html';
  workshopRequest(`/api/workshop/${encodeURIComponent(docId)}/state`)
    .then(value => { snapshot = value; start(); })
    .catch(error => { failure = `Cannot open saved data: ${error.message}`; start(); });
  return () => {
    disposed = true;
    window.removeEventListener('message', listener);
    iframe.removeAttribute('src');
    iframe.srcdoc = '';
    iframe.setAttribute('sandbox', 'allow-scripts allow-modals');
  };
}
