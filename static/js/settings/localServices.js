// Shared service details, also reachable through the former Settings API.
import * as Modals from '../modalManager.js';
import Storage from '../storage.js';
import { initCodeDetails } from './code.js';
import { initVaultwardenDetails } from './vaultwarden.js';

const names = { searxng: 'SearXNG', chroma: 'ChromaDB', ntfy: 'ntfy', vaultwarden: 'Vaultwarden', code: 'Code' };
const linkTargetKey = 'exodus-local-services-link-target';
let dismiss;

export function openLocalServices(service) {
  dismiss?.();
  const previousFocus = document.activeElement;
  const template = document.getElementById('local-services-content');
  if (!template) return;
  const modal = document.createElement('div');
  modal.id = 'local-services-modal';
  modal.className = 'modal';
  modal.innerHTML = '<div class="modal-content"><div class="modal-header"><h2 id="local-service-heading"></h2><button type="button" class="close-btn" aria-label="Close service details">✕</button></div><div class="modal-body"></div></div>';
  modal.querySelector('h2').textContent = names[service] || 'Local Services';
  const body = modal.querySelector('.modal-body');
  body.append(template.content.cloneNode(true));
  const targetChoice = body.querySelector('#local-service-link-target');
  targetChoice.value = Storage.get(linkTargetKey) === '_self' ? '_self' : '_blank';
  const applyTarget = () => {
    body.querySelectorAll('a').forEach(link => {
      link.target = targetChoice.value;
      link.rel = 'noopener noreferrer';
    });
    body.querySelector('#local-service-link-hint').textContent = targetChoice.value === '_blank'
      ? 'Links open in a new tab, keeping Exodus open. Your browser may open a separate window instead.'
      : 'Links replace this tab. Use your browser’s Back button to return to Exodus.';
  };
  targetChoice.addEventListener('change', () => {
    Storage.set(linkTargetKey, targetChoice.value);
    applyTarget();
  });
  applyTarget();
  body.querySelectorAll('[data-service-card]').forEach(card => {
    // Keep the legacy Local Services overview separate from Privacy Hub.
    if (names[service] ? card.dataset.serviceCard !== service : !!card.dataset.serviceGroup) {
      card.remove();
    }
  });
  document.body.append(modal);
  const cleanup = service === 'code' ? initCodeDetails(body)
    : service === 'vaultwarden' ? initVaultwardenDetails(body) : null;
  Modals.register(modal.id, {
    label: names[service] || 'Local Services',
    closeFn: () => {
      cleanup?.();
      modal.remove();
      if (previousFocus?.isConnected) previousFocus.focus();
    },
  });
  dismiss = () => Modals.close(modal.id);
  modal._dismiss = dismiss;
  modal.addEventListener('click', event => { if (event.target === modal) dismiss(); });
  Modals.injectMinimizeButton(modal, modal.id);
  modal.querySelector('.close-btn').onclick = dismiss;
  modal.querySelector('.close-btn').focus();
}

document.querySelectorAll('[data-local-service]').forEach(button => {
  button.addEventListener('click', () => openLocalServices(button.dataset.localService));
});

// The existing section manager owns collapse/persistence; mirror it for AT.
document.querySelectorAll('#local-services-section, #privacy-hub-section').forEach(section => {
  const syncExpanded = () => section.querySelector('.section-title')
    .setAttribute('aria-expanded', String(!section.classList.contains('collapsed')));
  new MutationObserver(syncExpanded).observe(section, { attributes: true, attributeFilter: ['class'] });
  syncExpanded();
});
