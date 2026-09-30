// Progressive disclosure for Settings. This is presentation state only;
// it never changes providers, permissions, or feature configuration.
import { DEFAULT_SETTINGS_PANEL_ID, getSettingsPanel } from './registry.js';

const VIEW_KEY = 'odysseus-settings-view';
const _bound = new WeakSet();

export function setSettingsView(modalEl, view, { persist = true } = {}) {
  if (!modalEl) return;
  const advanced = view === 'advanced';
  modalEl.classList.toggle('settings-essentials', !advanced);
  modalEl.dataset.settingsView = advanced ? 'advanced' : 'essentials';
  modalEl.querySelectorAll('[data-settings-view]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.settingsView === modalEl.dataset.settingsView));
  });
  const hint = modalEl.querySelector('#settings-view-hint');
  if (hint) hint.textContent = advanced
    ? 'All settings, including model tuning, automation, and administration.'
    : 'Everyday settings. Open Advanced whenever you want more control.';
  if (persist) {
    try { localStorage.setItem(VIEW_KEY, modalEl.dataset.settingsView); } catch (_) {}
  }
}

export function revealSettingsPanel(modalEl, tab) {
  // Existing deep links and search results must still open advanced panels.
  if (getSettingsPanel(tab)?.advanced) setSettingsView(modalEl, 'advanced');
}

export function setSetupChoice(modalEl, choice) {
  if (!modalEl || !['local', 'cloud'].includes(choice)) return;
  modalEl.dataset.setupChoice = choice;
  modalEl.querySelectorAll('[data-setup-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.setupChoice === choice));
  });
}

export function bindSettingsExperience(modalEl) {
  if (!modalEl || _bound.has(modalEl)) return;
  _bound.add(modalEl);

  let storedView;
  try { storedView = localStorage.getItem(VIEW_KEY); } catch (_) {}
  setSettingsView(modalEl, storedView, { persist: false });
  setSetupChoice(modalEl, 'local');

  modalEl.querySelectorAll('[data-settings-view]').forEach(button => {
    button.addEventListener('click', () => {
      const view = button.dataset.settingsView;
      setSettingsView(modalEl, view);
      const active = modalEl.querySelector('[data-settings-tab].active');
      if (view !== 'advanced' && getSettingsPanel(active?.dataset.settingsTab)?.advanced) {
        modalEl.querySelector(`[data-settings-tab="${DEFAULT_SETTINGS_PANEL_ID}"]`)?.click();
      }
    });
  });

  modalEl.querySelectorAll('[data-setup-choice]').forEach(button => {
    button.addEventListener('click', () => setSetupChoice(modalEl, button.dataset.setupChoice));
  });

}
