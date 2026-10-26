// Settings → Appearance → Workspace look: the look of all of Exodus (Exodus or
// Apple-like) and, for the Apple-like look, how its Dock behaves. Saved in this
// browser by js/apps/workspaceLook.js and applied right away.
import { WORKSPACE_LOOKS, DOCK_MODES, LAUNCHER_FOR_LOOK, WORKSPACE_LOOK_EVENT, readWorkspaceLook, setWorkspaceLook } from '../apps/workspaceLook.js';

function select(doc, { id, label, options, value }) {
  const el = doc.createElement('select');
  el.id = id;
  el.className = 'theme-fd-select app-look-select';
  el.setAttribute('aria-label', label);
  for (const [v, text] of Object.entries(options)) {
    const option = doc.createElement('option');
    option.value = v;
    option.textContent = text;
    option.selected = v === value;
    el.append(option);
  }
  return el;
}

function row(doc, labelText, control) {
  const label = doc.createElement('label');
  label.className = 'vis-row app-look-row';
  const text = doc.createElement('span');
  text.className = 'vis-label';
  text.textContent = labelText;
  label.append(text, control);
  return label;
}

export function renderWorkspaceLook(container, { storage = globalThis.localStorage, doc = container.ownerDocument || document } = {}) {
  const prefs = readWorkspaceLook(storage);
  const rows = [row(doc, 'Look', select(doc, { id: 'workspace-look-select', label: 'Workspace look', options: WORKSPACE_LOOKS, value: prefs.look }))];
  if (LAUNCHER_FOR_LOOK[prefs.look] === 'dock') {
    rows.push(row(doc, 'Dock', select(doc, { id: 'workspace-dock-select', label: 'Dock', options: DOCK_MODES, value: prefs.dock })));
  }
  container.replaceChildren(...rows);
  return prefs;
}

export function mountWorkspaceLook(container, { storage = globalThis.localStorage, doc = container?.ownerDocument || globalThis.document } = {}) {
  if (!container) return;
  renderWorkspaceLook(container, { storage, doc });
  if (container.dataset.bound) return;
  container.dataset.bound = '1';
  container.addEventListener('change', event => {
    if (event.target.id === 'workspace-look-select') setWorkspaceLook({ look: event.target.value }, { storage, doc });
    if (event.target.id === 'workspace-dock-select') setWorkspaceLook({ dock: event.target.value }, { storage, doc });
  });
  doc.addEventListener(WORKSPACE_LOOK_EVENT, () => renderWorkspaceLook(container, { storage, doc }));
}
