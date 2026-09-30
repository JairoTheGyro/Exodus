import documentModule from './document.js?v=20260929workspace1';
import settingsModule from './settings.js?v=sovereign-essentials1';
import { isWorkshopSource, workshopRequest } from './workshopRuntime.js';

const examples = {
  habits: ['Habit tracker', 'A simple weekly checklist for routines I choose.', 'Add and remove habits, check off each day, and keep my entries after reopening.'],
  study: ['Study planner', 'Help me divide study topics into small sessions.', 'Add topics and target dates, mark sessions complete, and show remaining sessions from my real entries.'],
  trip: ['Trip checklist', 'A reusable packing list without names, addresses, or booking details.', 'Create categories, add items, tick packed items, and reset checks for the next trip.'],
  quote: ['Estimate calculator', 'Calculate an informal estimate from quantities and prices I enter. No customer details.', 'Add line items, multiply quantity by price, show the total, and clearly label it an informal estimate.'],
};
let modal, busy = false, modelOptions = [], canGenerate = false, assessment, assessedBrief, pendingBuild;
let previousFocus, buildController;
let allModelOptions = [];
const el = id => modal.querySelector(`#ws-${id}`);
const status = message => { el('status').textContent = message; };

function brief() {
  return {
    title: el('title').value.trim(), description: el('description').value.trim(),
    features: el('features').value.trim(), audience: el('audience').value,
    sensitive: el('sensitive').value === 'yes', external: el('external').checked,
    accounts: el('accounts').checked, critical: el('critical').checked,
  };
}
function controls() {
  el('build').disabled = busy || !canGenerate || !modelOptions.length || !assessment?.can_build ||
    (assessment.zone === 'yellow' && !el('ack').checked);
  el('retry').hidden = !pendingBuild;
  el('retry').disabled = busy;
  el('retry-save').disabled = busy;
  el('source-export').disabled = busy;
  el('inputs').disabled = busy || !!pendingBuild;
  el('close').disabled = busy;
  el('review').disabled = busy || !!pendingBuild;
  el('refresh').disabled = busy;
  el('models').disabled = busy;
  el('settings').disabled = busy;
  el('library').disabled = busy;
  el('brief-export').disabled = busy;
  el('build').hidden = !!pendingBuild;
  el('engine').disabled = busy;
  el('code').disabled = busy;
  el('cancel').hidden = !buildController;
}
function invalidate() {
  assessment = null; assessedBrief = null;
  el('scope').hidden = true; el('ack').checked = false;
  controls();
}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderModels() {
  const previous = modelOptions[Number(el('models').value)];
  modelOptions = allModelOptions.filter(m => el('engine').value === 'direct' || m.harness_compatible);
  el('models').replaceChildren(...modelOptions.map((model, index) => new Option(model.label, String(index))));
  if (!modelOptions.length) el('models').add(new Option('No compatible model connected', ''));
  const selected = modelOptions.findIndex(m => m.endpoint_id === previous?.endpoint_id && m.model === previous?.model);
  if (selected >= 0) el('models').value = String(selected);
  controls();
}
async function refreshModels() {
  try {
    const result = await workshopRequest('/api/workshop/models');
    allModelOptions = result.models; canGenerate = result.can_generate;
    renderModels();
    el('model-note').textContent = !canGenerate ? 'An administrator account is required to generate apps in this first version.' :
      !modelOptions.length ? 'Model setup can wait. Explore the brief and review flow now; connect a model in Settings when you want to build.' :
      'Builds send your brief and any app source being revised to this model, never saved entries. Harness may make several requests while fixing its work. Cloud models may charge your API account.';
  } catch (error) {
    modelOptions = []; allModelOptions = []; canGenerate = false;
    el('models').replaceChildren(new Option('Models unavailable', ''));
    el('model-note').textContent = error.message;
  }
  controls();
}
async function assess(event) {
  event.preventDefault();
  busy = true; controls(); status('Checking the scope…');
  try {
    const value = brief();
    assessment = await workshopRequest('/api/workshop/assess', {method: 'POST', body: JSON.stringify(value)});
    assessedBrief = JSON.stringify(value);
    el('scope').hidden = false;
    el('zone').textContent = `${assessment.zone[0].toUpperCase() + assessment.zone.slice(1)} zone`;
    el('zone').dataset.zone = assessment.zone;
    el('assessment').textContent = assessment.message;
    el('reasons').replaceChildren(...assessment.reasons.map(reason => { const li = document.createElement('li'); li.textContent = reason; return li; }));
    el('ack-wrap').hidden = assessment.zone !== 'yellow';
    status(assessment.can_build ? 'Scope checked. This is a screening aid, not a security or compliance review.' : 'Building is paused for this scope. Download the brief for review, or narrow the idea to a low-risk tool.');
  } catch (error) { status(error.message); }
  finally { busy = false; controls(); }
}
async function saveBuild() {
  // Reuse Documents for ownership, Library, source export and version history.
  const doc = await workshopRequest('/api/document', {method: 'POST', body: JSON.stringify(pendingBuild)});
  pendingBuild = null;
  documentModule.injectFreshDoc(doc);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (documentModule.getCurrentDocId() === doc.id) documentModule.showHtmlPreview();
  }));
  return doc;
}
async function build(retry = false) {
  if (busy) return;
  busy = true; controls();
  try {
    if (!retry) {
      if (JSON.stringify(brief()) !== assessedBrief) throw new Error('Review the changed brief before building.');
      const selected = modelOptions[Number(el('models').value)];
      if (!selected) throw new Error('Connect and select a model first.');
      buildController = new AbortController(); controls();
      status(el('engine').value === 'harness' ? 'The coding engine is building and checking your tool… This can take up to five minutes.' : 'Building with your selected model… This can take a few minutes.');
      const result = await workshopRequest('/api/workshop/generate', {method: 'POST', signal: buildController.signal, body: JSON.stringify({
        ...brief(), engine: el('engine').value, endpoint_id: selected.endpoint_id, model: selected.model, acknowledged: el('ack').checked,
      })});
      buildController = null; controls();
      pendingBuild = {title: result.title, content: result.content, language: 'html', request_id: crypto.randomUUID()};
    }
    status('Saving to your existing Library…');
    await saveBuild();
    status('Saved. Use Run to open your tool, Code to edit it, and the existing version and export controls.');
    busy = false; close();
  } catch (error) {
    status(`${error.name === 'AbortError' ? 'Build cancelled. Nothing was saved. Requests already sent to a cloud provider may still be billed.' : error.message}${pendingBuild ? ' Your generated source is still held here. Retry saving without generating again, or download the source.' : ''}`);
  } finally { buildController = null; busy = false; controls(); }
}
async function currentApp() {
  const id = documentModule.getCurrentDocId();
  if (!id) throw new Error('Open a Workshop app from the Library first.');
  const doc = await workshopRequest(`/api/document/${encodeURIComponent(id)}`);
  if (!isWorkshopSource(doc.current_content || doc.content)) throw new Error('The open document is not a Workshop app.');
  return doc;
}
function close() {
  if (busy) return;
  modal.hidden = true; modal.classList.add('hidden'); previousFocus?.focus();
}
function createModal() {
  modal = document.createElement('div');
  modal.id = 'workshop-modal'; modal.className = 'modal'; modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-labelledby', 'ws-heading');
  modal.innerHTML = `<div class="modal-content ws-content">
    <div class="modal-header"><h4 id="ws-heading">AI Workshop</h4><button type="button" class="close-btn" id="ws-close" aria-label="Close Workshop">✕</button></div>
    <div class="modal-body ws-body">
      <p class="ws-intro">Small idea. Your own tool.</p>
      <p>Describe one useful thing in everyday language. The coding engine builds and checks your tool behind the scenes, then opens it inside Exodus.</p>
      <div class="ws-demo"><strong>Demo only — do not enter private information.</strong><br>AI-generated tools can make mistakes. Test with non-sensitive entries. This is not a production app builder.</div>
      <div class="ws-actions"><button type="button" id="ws-library">Open Library</button><button type="button" id="ws-brief-export">Download review brief</button></div>
      <form id="ws-form"><fieldset id="ws-inputs">
        <div class="ws-examples" aria-label="Brief examples"><span>Start with an idea:</span><button type="button" data-example="habits">Habits</button><button type="button" data-example="study">Study</button><button type="button" data-example="trip">Trip checklist</button><button type="button" data-example="quote">Estimates</button></div>
        <label for="ws-title">Tool name</label><input id="ws-title" required maxlength="100" placeholder="My weekly planner">
        <label for="ws-description">What do you want to build?</label><textarea id="ws-description" required minlength="10" maxlength="4000" rows="2" placeholder="Explain the problem in everyday language."></textarea>
        <p class="ws-hint">Try: “I need [a tool] to help me [a task]. I enter [these things], and it should [do this].” Keep your first version small.</p>
        <div class="ws-columns"><div><label for="ws-audience">Who is it for?</label><select id="ws-audience"><option value="me">Just me</option><option value="family">Family</option><option value="group">Small group</option><option value="public">Public</option></select></div><div><label for="ws-sensitive">Will it store sensitive information?</label><select id="ws-sensitive"><option value="no">No</option><option value="yes">Yes / I'm unsure</option></select></div></div>
        <label for="ws-features">What should it actually do?</label><textarea id="ws-features" required minlength="5" maxlength="4000" rows="3" placeholder="List the inputs, calculations or actions, and what should be saved."></textarea>
        <details><summary>Does the idea need anything beyond a personal tool?</summary><label class="ws-check"><input type="checkbox" id="ws-external">External APIs, cloud storage, or syncing</label><label class="ws-check"><input type="checkbox" id="ws-accounts">Accounts or login</label><label class="ws-check"><input type="checkbox" id="ws-critical">Critical decisions or business operations</label></details>
      </fieldset><button id="ws-review" type="submit">Review scope</button></form>
      <section id="ws-scope" hidden aria-live="polite"><strong id="ws-zone" class="ws-zone"></strong><p id="ws-assessment"></p><ul id="ws-reasons"></ul><label id="ws-ack-wrap" class="ws-check" hidden><input type="checkbox" id="ws-ack">I understand this builds a local prototype. Sharing, accounts, and external connections are not provided.</label></section>
      <section class="ws-model"><label for="ws-models">Build with</label><select id="ws-models"><option>Checking connected models…</option></select><p id="ws-model-note" class="ws-hint"></p><div class="ws-actions"><button type="button" id="ws-settings">Model settings</button><button type="button" id="ws-refresh">Refresh models</button></div></section>
      <details><summary>Advanced options</summary><label for="ws-engine">Builder</label><select id="ws-engine"><option value="harness">Harness — build and check (recommended)</option><option value="direct">Basic builder — one model response</option></select><p class="ws-hint">Harness checks HTML structure and JavaScript syntax. These checks do not guarantee correct behavior. Test the finished tool.</p><button type="button" id="ws-code">Open Code for direct coding…</button></details>
      <button type="button" id="ws-build" disabled>Build my tool</button><button type="button" id="ws-cancel" hidden>Cancel build</button><div id="ws-retry" hidden><button type="button" id="ws-retry-save">Retry saving</button><button type="button" id="ws-source-export">Download generated source</button></div>
      <p id="ws-status" role="status" aria-live="polite"></p>
      <details><summary>Saved entries &amp; prototype limits</summary><p>Each tool has separate entries stored on this Exodus server, with a 100 KB limit. Tools use a restricted preview. Ordinary web requests, popups, and access to your account are blocked; this is not a security certification. Browser protections vary.</p><p>Source and versions live in the existing Library. Exported source using the Workshop storage API requires this host to run. Back up your entries separately below. No Workshop telemetry or automatic publishing is added.</p><div class="ws-actions"><button type="button" id="ws-data-export">Export open app's entries</button><button type="button" id="ws-data-import">Restore entries…</button><input id="ws-file" type="file" accept="application/json,.json" hidden></div></details>
    </div></div>`;
  document.body.append(modal);
  el('close').onclick = close;
  el('form').onsubmit = assess;
  el('inputs').addEventListener('input', invalidate);
  el('inputs').addEventListener('change', invalidate);
  el('ack').onchange = controls;
  el('build').onclick = () => build();
  el('retry-save').onclick = () => build(true);
  el('source-export').onclick = () => {
    const url = URL.createObjectURL(new Blob([pendingBuild.content], {type: 'text/html'}));
    const a = document.createElement('a'); a.href = url; a.download = 'workshop-source.html'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  el('refresh').onclick = refreshModels;
  el('engine').onchange = () => { renderModels(); refreshModels(); };
  el('code').onclick = () => { close(); document.getElementById('tool-code-btn')?.click(); };
  el('cancel').onclick = () => { buildController?.abort(); };
  el('settings').onclick = () => { close(); settingsModule.open('services'); };
  el('library').onclick = () => { close(); documentModule.openLibrary(); };
  el('brief-export').onclick = () => download('workshop-review-brief.json', {brief: brief(), assessment, prototype_only: true});
  modal.querySelectorAll('[data-example]').forEach(button => { button.onclick = () => {
    [el('title').value, el('description').value, el('features').value] = examples[button.dataset.example]; invalidate();
  }; });
  el('data-export').onclick = async () => {
    try { const doc = await currentApp(); const state = await workshopRequest(`/api/workshop/${encodeURIComponent(doc.id)}/state`); download('workshop-entries.json', {format: 'sovereign-workshop-state-v1', app_id: doc.id, title: doc.title, data: state.data}); status('Entries exported. Source is exported separately from the editor.'); }
    catch (error) { status(error.message); }
  };
  el('data-import').onclick = () => el('file').click();
  el('file').onchange = async () => {
    const file = el('file').files[0]; el('file').value = ''; if (!file) return;
    try {
      if (file.size > 110000) throw new Error('The backup is too large.');
      const doc = await currentApp(), backup = JSON.parse(await file.text());
      if (backup.format !== 'sovereign-workshop-state-v1' || backup.app_id !== doc.id || !backup.data || typeof backup.data !== 'object' || Array.isArray(backup.data)) throw new Error('Choose an entries backup belonging to this app.');
      const state = await workshopRequest(`/api/workshop/${encodeURIComponent(doc.id)}/state`);
      if (!window.confirm(`Replace the saved entries for “${doc.title}” with this backup? Export current entries first if you need to keep them.`)) return;
      await workshopRequest(`/api/workshop/${encodeURIComponent(doc.id)}/state`, {method: 'PUT', body: JSON.stringify({revision: state.revision, data: backup.data})});
      status('Entries restored. Switch the app to Code, then Run to reload them.');
    } catch (error) { status(error.message); }
  };
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.stopPropagation(); close(); }
    if (event.key === 'Tab') {
      const items = [...modal.querySelectorAll('button,input,textarea,select,summary')].filter(node => !node.disabled && node.getClientRects().length);
      const first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
}
export function openWorkshop() {
  previousFocus = document.activeElement;
  if (!modal) createModal();
  modal.hidden = false; modal.classList.remove('hidden'); el('title').focus();
  refreshModels();
}
document.getElementById('tool-workshop-btn')?.addEventListener('click', openWorkshop);
