// Settings → System → Workspace name and logo (admin). Saving goes through
// js/workspaceBrand.js, which updates every open part of the app at once.
import {
  DEFAULT_NAME, workspaceName, workspaceLogoUrl, refreshWorkspaceBrand,
  saveWorkspaceName, uploadWorkspaceLogo, removeWorkspaceLogo,
} from '../workspaceBrand.js';

function defaultLogo() {
  try { return new URL('../../icons/exodus.png', import.meta.url).pathname; }
  catch (_) { return '/static/icons/exodus.png'; }
}

function $(doc, id) { return doc.getElementById(id); }

function render(doc) {
  const input = $(doc, 'workspace-brand-name');
  const name = workspaceName();
  if (input && doc.activeElement !== input) input.value = name === DEFAULT_NAME ? '' : name;
  const preview = $(doc, 'workspace-brand-logo-preview');
  if (preview) preview.src = workspaceLogoUrl() || defaultLogo();
  const remove = $(doc, 'workspace-brand-logo-remove');
  if (remove) remove.disabled = !workspaceLogoUrl();
}

async function run(doc, button, action, done) {
  const status = $(doc, 'workspace-brand-status');
  if (button) button.disabled = true;
  try {
    await action();
    if (status) status.textContent = done();
  } catch (error) {
    if (status) status.textContent = error.message || 'Could not save.';
  } finally {
    if (button) button.disabled = false;
    render(doc);
  }
}

/** Wire the card once; refresh its values every time System opens. */
export function mountWorkspaceBrandSettings(doc = document) {
  const card = $(doc, 'workspace-brand-card');
  if (!card) return;
  render(doc);
  refreshWorkspaceBrand({ doc }).then(() => render(doc));
  if (card.dataset.bound) return;
  card.dataset.bound = '1';
  const input = $(doc, 'workspace-brand-name');
  const save = $(doc, 'workspace-brand-save');
  const file = $(doc, 'workspace-brand-logo-file');
  save?.addEventListener('click', () => run(doc, save, () => saveWorkspaceName(input.value),
    () => `Saved. Everyone now sees "${workspaceName()}".`));
  input?.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save?.click(); } });
  $(doc, 'workspace-brand-reset')?.addEventListener('click', event => run(doc, event.currentTarget,
    () => saveWorkspaceName(''), () => `Back to the default name, "${DEFAULT_NAME}".`));
  $(doc, 'workspace-brand-logo-upload')?.addEventListener('click', () => file?.click());
  file?.addEventListener('change', () => {
    const chosen = file.files?.[0];
    file.value = '';
    if (!chosen) return;
    run(doc, $(doc, 'workspace-brand-logo-upload'), () => uploadWorkspaceLogo(chosen), () => 'Logo saved.');
  });
  $(doc, 'workspace-brand-logo-remove')?.addEventListener('click', event => run(doc, event.currentTarget,
    () => removeWorkspaceLogo(), () => 'Back to the default logo.'));
}
