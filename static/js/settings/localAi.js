// Settings → Account → Local AI (admins): how much memory the AI computer
// has, what size of model fits, the best official models for it, and how to
// connect one as everyone's Shared AI. Uses the Cookbook's /api/hwfit ranking,
// which inside Docker reads the whole computer from scripts/host_hardware.py.
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

const gb = value => `${Math.round(Number(value) || 0)} GB`;

/** Share of an Apple chip's memory its graphics can use (matches services/hwfit/hardware.py). */
export function appleUsableGb(total) {
  const frac = total <= 16 ? 0.67 : total <= 64 ? 0.75 : 0.80;
  return Math.round(total * frac * 10) / 10;
}

/** Memory a model can use, and where it runs. */
export function usableMemory(system) {
  if (system?.has_gpu && Number(system.gpu_vram_gb) > 0) {
    return { gb: Number(system.gpu_vram_gb), where: system.unified_memory ? 'shared' : 'graphics' };
  }
  return { gb: Math.round((Number(system?.total_ram_gb) || 0) * 0.6 * 10) / 10, where: 'processor' };
}

/** One plain sentence about the model sizes that fit. */
export function sizeAdvice(usableGb) {
  if (usableGb < 6) return 'Small models (up to about 8 billion parameters) only just fit. They’re fine for quick helpers; a cloud AI is better for everyday chat.';
  if (usableGb < 12) return 'Models up to about 8 billion parameters fit: good for quick helpers and simple chat.';
  if (usableGb < 20) return 'Models up to about 14 billion parameters fit: a solid everyday assistant.';
  if (usableGb < 40) return 'Models up to about 32 billion parameters fit (or “30B-A3B” style models, which are faster): the best quality most homes can run.';
  if (usableGb < 80) return 'Models up to about 70 billion parameters fit: close to cloud quality.';
  return 'Very large models (100 billion parameters and more) fit.';
}

/** Cookbook query for the person's own description of another computer. */
export function manualQuery({ kind, memory, graphics }) {
  const total = Math.max(1, Number(memory) || 0);
  if (kind === 'mac') return { manual_mode: 'gpu', manual_backend: 'metal', manual_gpu_count: '1', manual_vram_gb: String(appleUsableGb(total)), manual_ram_gb: String(total) };
  if (kind === 'nvidia') return { manual_mode: 'gpu', manual_backend: 'cuda', manual_gpu_count: '1', manual_vram_gb: String(Math.max(1, Number(graphics) || 8)), manual_ram_gb: String(total) };
  return { manual_mode: 'ram', manual_ram_gb: String(total) };
}

function sourceLine(system, manual) {
  if (manual) return 'Using the computer you described.';
  if (system.probe_scope === 'host_snapshot') {
    const when = String(system.host_measured_at || '').slice(0, 10);
    return when ? `Whole computer, measured on ${when}.` : 'Whole computer.';
  }
  if (system.probe_scope === 'native') return 'Measured on this computer just now.';
  return '';
}

export function renderLocalAi(container, { system, models = [], error = '', catalogEmpty = false, manual = null } = {}, doc = container.ownerDocument || document) {
  container.replaceChildren();
  if (system && !system.error) {
    const usable = usableMemory(system);
    const name = manual ? 'That computer' : (system.cpu_name || system.gpu_name || 'This computer');
    container.append(el(doc, 'p', { className: 'local-ai-machine', text: `${name}: ${gb(system.total_ram_gb)} memory` }));
    const source = sourceLine(system, manual);
    if (source) container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: source }));
    if (!manual && system.probe_scope === 'container') {
      container.append(el(doc, 'p', { className: 'local-ai-warn', role: 'note',
        text: `Exodus runs in Docker here, so it only sees ${gb(system.total_ram_gb)}, Docker’s share. To use the whole computer’s memory, run python3 scripts/host_hardware.py from the Exodus folder on the computer itself, then press Check again. Or describe the computer below.` }));
    }
    const where = usable.where === 'shared' ? 'usable by the graphics chip'
      : usable.where === 'graphics' ? 'of graphics memory'
      : 'for models running on the processor (slower; no graphics chip found)';
    container.append(el(doc, 'p', { className: 'local-ai-usable', text: `About ${gb(usable.gb)} ${where}.` }),
      el(doc, 'p', { className: 'admin-toggle-sub', text: sizeAdvice(usable.gb) }));
  }
  if (catalogEmpty) {
    container.append(el(doc, 'p', { className: 'local-ai-warn', role: 'note', text: 'The list of AI models hasn’t been downloaded yet. Press Update model list (needs the internet).' }));
  } else if (error) container.append(el(doc, 'p', { className: 'local-ai-warn', role: 'note', text: error }));
  if (models.length) {
    container.append(el(doc, 'p', { className: 'local-ai-title', text: manual ? 'Good fits for that computer:' : 'Good fits for this computer:' }));
    const list = el(doc, 'ul', { className: 'local-ai-models' });
    for (const m of models.slice(0, 5)) {
      const bits = [m.quant, m.required_gb ? `needs ${m.required_gb} GB` : '', m.speed_tps ? `about ${Math.round(m.speed_tps)} words/s` : ''].filter(Boolean);
      list.append(el(doc, 'li', {}, el(doc, 'strong', { text: m.name || '' }), el(doc, 'span', { text: bits.length ? ` · ${bits.join(' · ')}` : '' })));
    }
    container.append(list);
  } else if (system && !system.error && !error && !catalogEmpty) {
    container.append(el(doc, 'p', { className: 'admin-toggle-sub', text: 'No model fits comfortably. A cloud AI is the better choice for this computer.' }));
  }

  const kind = el(doc, 'select', { className: 'local-ai-kind', 'aria-label': 'Kind of computer' });
  for (const [value, label] of [['mac', 'Mac with an Apple chip'], ['nvidia', 'PC with an NVIDIA graphics card'], ['cpu', 'PC without a graphics card']]) {
    const option = el(doc, 'option', { value, text: label });
    if (manual?.kind === value) option.selected = true;
    kind.append(option);
  }
  const memory = el(doc, 'input', { type: 'number', min: '1', step: '1', className: 'local-ai-memory', 'aria-label': 'Memory in GB', placeholder: 'Memory (GB)' });
  const graphics = el(doc, 'input', { type: 'number', min: '1', step: '1', className: 'local-ai-graphics', 'aria-label': 'Graphics memory in GB', placeholder: 'Graphics memory (GB)' });
  if (manual?.memory) memory.value = String(manual.memory);
  if (manual?.graphics) graphics.value = String(manual.graphics);
  graphics.hidden = (manual?.kind || 'mac') !== 'nvidia';
  container.append(
    el(doc, 'details', { className: 'local-ai-other' },
      el(doc, 'summary', { text: 'The AI will run on a different computer' }),
      el(doc, 'div', { className: 'local-ai-row' }, kind, memory, graphics,
        el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { localAi: 'manual' }, text: 'Check this computer' }))),
    el(doc, 'ol', { className: 'local-ai-steps' },
      el(doc, 'li', { text: 'On the AI computer, install LM Studio (lmstudio.ai) or Ollama (ollama.com).' }),
      el(doc, 'li', { text: 'Download one of the models above and start its server.' }),
      el(doc, 'li', { text: 'Connect it in Added Models and share it. Everyone can then pick Shared AI in Your AI.' })),
    el(doc, 'div', { className: 'local-ai-row' },
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { localAi: 'check' }, text: 'Check again' }),
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { localAi: 'refresh' }, text: 'Update model list' }),
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { localAi: 'cookbook' }, text: 'All models in Cookbook' }),
      el(doc, 'button', { type: 'button', className: 'admin-btn-sm', dataset: { localAi: 'connect' }, text: 'Open Added Models' })),
    el(doc, 'p', { className: 'local-ai-msg admin-toggle-sub', role: 'status' }));
}

const MODEL_QUERY = { recommended: 'true', limit: '5', sort: 'score', use_case: 'general' };

/** Mount the card for admins; hides it for everyone else. */
export async function mountLocalAi(container, {
  api = (url, init) => fetch(url, { credentials: 'same-origin', ...init }),
  openSettings = async tab => (await import('../settings.js?v=20260912writingstyle3')).default.open(tab),
  openCookbook = () => {
    if (window.cookbookModule?.open) window.cookbookModule.open({ tab: 'Search' });
    else document.getElementById('tool-cookbook-btn')?.click();
  },
} = {}) {
  if (!container) return;
  const card = container.closest('.admin-card') || container;
  let manual = null;

  async function load(fresh = false, refreshCatalog = false) {
    const say = text => { const msg = container.querySelector('.local-ai-msg'); if (msg) msg.textContent = text; };
    say(refreshCatalog ? 'Downloading the model list… this can take a minute.' : 'Checking…');
    const params = new URLSearchParams({ ...MODEL_QUERY, ...(manual ? manualQuery(manual) : {}), ...(fresh ? { fresh: 'true' } : {}), ...(refreshCatalog ? { refresh_catalog: 'true' } : {}) });
    let response;
    try { response = await api(`/api/hwfit/models?${params}`); } catch (_) { response = null; }
    if (response && (response.status === 401 || response.status === 403)) { card.hidden = true; return; }
    card.hidden = false;
    const body = response ? await response.json().catch(() => ({})) : {};
    if (!response || !response.ok) {
      renderLocalAi(container, { error: 'Could not check this computer. Try again in a moment.', manual });
      return;
    }
    const refreshFailed = refreshCatalog && body.catalog_refresh?.error;
    renderLocalAi(container, { system: body.system, models: body.models || [], error: body.error || '', catalogEmpty: !!body.catalog_empty, manual });
    if (refreshFailed) say('Could not download the model list. Check the internet connection and try again.');
  }

  if (!container.dataset.bound) {
    container.dataset.bound = '1';
    container.addEventListener('change', event => {
      if (event.target.classList?.contains('local-ai-kind')) {
        const graphics = container.querySelector('.local-ai-graphics');
        if (graphics) graphics.hidden = event.target.value !== 'nvidia';
      }
    });
    container.addEventListener('click', async event => {
      const action = event.target.closest?.('[data-local-ai]')?.dataset.localAi;
      if (!action) return;
      if (action === 'check') { manual = null; await load(true); }
      else if (action === 'refresh') { event.target.disabled = true; await load(false, true); }
      else if (action === 'manual') {
        const memory = Number(container.querySelector('.local-ai-memory')?.value);
        if (!(memory > 0)) { container.querySelector('.local-ai-memory')?.focus(); return; }
        manual = { kind: container.querySelector('.local-ai-kind')?.value || 'mac', memory, graphics: Number(container.querySelector('.local-ai-graphics')?.value) || 0 };
        await load();
      } else if (action === 'cookbook') openCookbook();
      else if (action === 'connect') await openSettings('added-models');
    });
  }
  await load();
}
