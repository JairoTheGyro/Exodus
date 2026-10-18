/**
 * Clock — small DOM helpers shared by the four Clock views: an element
 * builder, SVG icons, in-window sheets, body-portaled context menus and the
 * sound picker.
 */

import { topPortalZ } from '../toolWindowZOrder.js';
import { bindMenuDismiss } from '../escMenuStack.js';
import { SOUNDS, soundName, preview } from './sound.js';

const CSS_HREF = '/static/js/clock/clock.css';

/** Load the Clock stylesheet once (the window and the alert cards need it). */
export function ensureClockCss() {
  if (document.querySelector('link[data-clock-css]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS_HREF;
  link.dataset.clockCss = '1';
  document.head.append(link);
}

/** h('div.cls#id', { attrs, on: { click } }, ...children) */
export function h(spec, props = {}, ...children) {
  const m = /^([a-z0-9-]+)?((?:[.#][\w-]+)*)$/i.exec(spec) || [];
  const el = document.createElement(m[1] || 'div');
  (m[2] || '').replace(/([.#])([\w-]+)/g, (_, kind, name) => {
    if (kind === '.') el.classList.add(name); else el.id = name;
    return '';
  });
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'on') for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const svg = (body, size = 16, extra = '') =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;

export const ICONS = {
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 14),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 16),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>', 16),
  search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 14),
  play: '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" fill="currentColor"/></svg>',
  pause: '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><rect x="6.5" y="5" width="4" height="14" rx="1.2" fill="currentColor"/><rect x="13.5" y="5" width="4" height="14" rx="1.2" fill="currentColor"/></svg>',
  bell: '<svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a6 6 0 0 0-6 6v4.5L4 16v1h16v-1l-2-3.5V8a6 6 0 0 0-6-6zm0 21a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 23z" fill="currentColor"/></svg>',
  trash: svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>', 14),
  alarm: '<svg width="40" height="40" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8" fill="currentColor"/><path d="M12 9v4.2h-3" stroke="var(--clk-surface-0)" stroke-width="1.8" fill="none" stroke-linecap="round"/><path d="M3.2 6.6 6.6 3.2M20.8 6.6 17.4 3.2M6.5 20 5 21.8M17.5 20 19 21.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  globe: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.8 3 2.8 15 0 18M12 3c-2.8 3-2.8 15 0 18"/></svg>',
  timer: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 13V9M9.5 2.5h5"/></svg>',
  sunrise: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 18a7 7 0 0 1 14 0M3 21h18M12 3v5M9 6l3-3 3 3M4.2 11.2l1.4 1.4M19.8 11.2l-1.4 1.4"/></svg>',
  sunset: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 18a7 7 0 0 1 14 0M3 21h18M12 8V3M9 5l3 3 3-3M4.2 11.2l1.4 1.4M19.8 11.2l-1.4 1.4"/></svg>',
};

/**
 * Show a macOS-style sheet inside the Clock window. Returns { el, close }.
 * Esc and the backdrop close it (Esc is handled by the Clock window so a sheet
 * closes before the window does).
 */
export function openSheet(host, content, { onClose, className = '' } = {}) {
  host.querySelectorAll(':scope > .clk-sheet-backdrop').forEach(n => n._close?.());
  const backdrop = h('div.clk-sheet-backdrop');
  const sheet = h(`div.clk-sheet${className ? '.' + className : ''}`, { role: 'dialog', 'aria-modal': 'true' }, content);
  backdrop.append(sheet);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.classList.add('clk-closing');
    setTimeout(() => backdrop.remove(), 140);
    onClose?.();
  };
  backdrop._close = close;
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
  host.append(backdrop);
  requestAnimationFrame(() => sheet.querySelector('[autofocus], input, button.clk-primary')?.focus());
  return { el: sheet, close };
}

/** Close the topmost sheet in `host`; true when one was open. */
export function closeTopSheet(host) {
  const all = host?.querySelectorAll(':scope > .clk-sheet-backdrop:not(.clk-closing)');
  const top = all?.[all.length - 1];
  if (!top) return false;
  top._close?.();
  return true;
}

/** Right-click style menu: items = [{ label, action, danger }]. */
export function contextMenu(x, y, items) {
  document.querySelectorAll('.clk-menu').forEach(m => m._dismiss?.());
  const menu = h('div.clk-menu', { role: 'menu' });
  for (const it of items) {
    if (it === '-') { menu.append(h('div.clk-menu-sep')); continue; }
    menu.append(h(`button.clk-menu-item${it.danger ? '.clk-danger' : ''}`, {
      type: 'button', role: 'menuitem', text: it.label, disabled: !!it.disabled,
      on: { click: () => { close(); it.action?.(); } },
    }));
  }
  menu.style.zIndex = String(topPortalZ());
  document.body.append(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, window.innerWidth - r.width - 6)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - r.height - 6)}px`;
  const close = bindMenuDismiss(menu, () => menu.remove());
  return close;
}

/** Native <select> of alert sounds; previews a tone when changed. */
export function soundSelect(value, onChange) {
  const sel = h('select.clk-select', { 'aria-label': 'Sound' });
  for (const s of SOUNDS) sel.append(new Option(soundName(s.id), s.id, false, s.id === value));
  sel.addEventListener('change', () => { preview(sel.value); onChange?.(sel.value); });
  return sel;
}

/** iOS/macOS-style switch built on a checkbox. */
export function toggle(checked, onChange, label) {
  const input = h('input', { type: 'checkbox', checked: !!checked, 'aria-label': label || 'Toggle' });
  input.addEventListener('change', () => onChange?.(input.checked));
  input.addEventListener('click', e => e.stopPropagation());
  return h('label.clk-switch', { on: { click: e => e.stopPropagation() } }, input, h('span.clk-switch-track'));
}
