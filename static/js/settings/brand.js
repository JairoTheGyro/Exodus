// Render color variants of the supplied pixel-art mark locally. The source PNG
// is never changed; UI images and the root favicon share the same rendered URL.
import Storage from '../storage.js';
import { BRAND_EVENT, startWorkspaceBrand, workspaceLogoUrl, workspaceName } from '../workspaceBrand.js';

const SOURCE = new URL('../../icons/exodus.png', import.meta.url).href;
const KEY = 'odysseus-logo-variant';
const DEFAULT_COLORS = { panel:'#111111', fg:'#9cdef2', red:'#e06c75' };
const variants = [
  ['auto', 'Match theme'], ['original', 'Original'],
  ['gold', 'Gold', '#292313', '#edc76c'],
  ['ocean', 'Ocean', '#122d43', '#64d2ff'],
  ['emerald', 'Emerald', '#153526', '#7ed6a5'],
  ['rose', 'Rose', '#422032', '#f7a5c8'],
  ['amethyst', 'Amethyst', '#302342', '#c6a0f6'],
  ['copper', 'Copper', '#3c271c', '#eba879'],
  ['ice', 'Ice', '#243940', '#b9eff2'],
  ['mono', 'Silver', '#303238', '#e4e4e7'],
];
let colors = Storage.getJSON('odysseus-theme', null)?.colors || DEFAULT_COLORS;
let choice = readChoice();
let choiceEdited = false;
let revision = 0;
let sourcePixels;
const cache = new Map();

function readChoice() {
  const saved = Storage.get(KEY);
  return variants.some(([key]) => key === saved) ? saved : 'auto';
}
function rgb(value, fallback) {
  const hex = /^#[\da-f]{6}$/i.test(value || '') ? value : fallback;
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
}
function mix(a, b, amount) { return a.map((v, i) => Math.round(v * (1 - amount) + b[i] * amount)); }
function luminance(color) {
  const linear = color.map(v => v / 255 <= .04045 ? v / 3294.6 : ((v / 255 + .055) / 1.055) ** 2.4);
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}
function palette(key) {
  if (key === 'auto' && colors.presentation === 'temple') {
    return { background:[255,255,255], frame:[0,0,170], accent:[170,0,0], outline:[0,0,0], steel:[170,170,170] };
  }
  const entry = variants.find(([id]) => id === key);
  const accent = rgb(entry?.[3] || colors.advanced?.brandColor || colors.red, '#e06c75');
  const background = entry?.[2] ? rgb(entry[2], '#282c34') : mix(rgb(colors.panel || colors.bg, '#111111'), accent, .18);
  let highlight = accent;
  if (contrast(highlight, background) < 3) {
    const ink = luminance(background) > .3 ? [0,0,0] : [255,255,255];
    highlight = mix(accent, ink, .55);
    if (contrast(highlight, background) < 3) highlight = ink;
  }
  return { background, frame:highlight, accent:highlight,
    outline:luminance(background) < .2 ? mix(highlight, [255,255,255], .25) : [0,0,0],
    steel:mix([255,255,255], accent, .12) };
}
function loadSource() {
  if (!sourcePixels) sourcePixels = new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 256;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(img, 0, 0, 256, 256);
        resolve(ctx.getImageData(0, 0, 256, 256));
      } catch (error) { reject(error); }
    };
    img.onerror = () => reject(new Error('The Exodus logo could not be loaded.'));
    img.src = SOURCE;
  });
  return sourcePixels;
}
async function logoURL(key) {
  if (key === 'original') return SOURCE;
  const p = palette(key);
  const cacheKey = JSON.stringify(p);
  if (cache.has(cacheKey)) return cache.get(cacheKey);
  const source = await loadSource();
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = source.width;
  const ctx = canvas.getContext('2d');
  const result = ctx.createImageData(source.width, source.height);
  const data = result.data;
  for (let i = 0; i < source.data.length; i += 4) {
    const [r, g, b] = source.data.subarray(i, i + 3);
    let color;
    // The original consists of cyan backdrop, navy frame, yellow scales and
    // hilt, and a grayscale blade/outline. Keep every shape and shading step.
    if (g > r + 35 && b > r + 35) color = p.background;
    else if (r > b + 35 && g > b + 35) color = p.accent;
    else if (b > r + 35 && b > g + 35) color = p.frame;
    else color = mix(p.outline, p.steel, (r + g + b) / 765);
    data.set(color, i);
    data[i + 3] = source.data[i + 3];
  }
  ctx.putImageData(result, 0, 0);
  const url = canvas.toDataURL('image/png');
  if (cache.size >= 32) cache.delete(cache.keys().next().value);
  cache.set(cacheKey, url);
  return url;
}

export async function applyExodusLogo(nextColors = colors) {
  colors = nextColors;
  const current = ++revision;
  const selected = choice;
  try {
    // Exodus: an admin-set workspace logo replaces the mark everywhere; the
    // color choices below still apply to the default mark.
    const custom = workspaceLogoUrl();
    const url = custom || await logoURL(selected);
    // Decode off-screen so the first visible frame already has the saved colors.
    const decoded = new Image();
    decoded.src = url;
    await decoded.decode();
    if (current !== revision) return;
    document.querySelectorAll('img.exodus-logo').forEach(img => {
      img.src = url;
      img.dataset.logoVariant = selected;
      img.removeAttribute('data-logo-pending');
    });
    const favicon = document.querySelector('link[rel="icon"]');
    // Dedicated tool routes retain their existing, theme-colored glyphs.
    if (favicon && favicon.dataset.routeIcon !== 'true') {
      favicon.type = 'image/png';
      favicon.href = url;
      favicon.dataset.logoVariant = selected;
      const apple = document.querySelector('link[rel="apple-touch-icon"]');
      if (apple) apple.href = url;
    }
    const status = document.getElementById('exodus-logo-status');
    if (status) status.textContent = custom
      ? `${workspaceName()} uses a custom logo set by an admin. These colors apply to the default logo.`
      : selected === 'auto'
      ? `The logo and ${workspaceName()} tab icon follow your theme. Choice saved in this browser.`
      : `${variants.find(([key]) => key === selected)[1]} stays selected when you change themes. Choice saved in this browser.`;
    for (const button of document.querySelectorAll('[data-logo-choice]')) {
      button.setAttribute('aria-pressed', String(button.dataset.logoChoice === selected));
      const preview = await logoURL(button.dataset.logoChoice);
      if (current !== revision) return;
      button.querySelector('img').src = preview;
    }
  } catch (error) {
    // Keep the existing themed image (or reserved blank space) on failure.
    // Never substitute the original colors unless the user selected Original.
    if (current !== revision) return;
    const status = document.getElementById('exodus-logo-status');
    if (status) status.textContent = 'Logo colors could not load. Reload to retry.';
    console.warn('[Exodus logo]', error.message);
  }
}

export function initLogoChoices() {
  const grid = document.getElementById('exodus-logo-choices');
  if (!grid || grid.dataset.bound) return;
  grid.dataset.bound = 'true';
  variants.forEach(([key, name]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.logoChoice = key;
    button.setAttribute('aria-label', `${name} logo`);
    button.setAttribute('aria-pressed', String(key === choice));
    const img = document.createElement('img');
    img.alt = ''; img.width = img.height = 40;
    const label = document.createElement('span');
    label.textContent = name;
    button.append(img, label);
    button.addEventListener('click', () => {
      choiceEdited = true;
      choice = key;
      Storage.set(KEY, choice);
      fetch('/api/prefs/logo-variant', {method:'PUT', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({value:choice})})
        .then(response => { if (!response.ok) throw new Error('save'); })
        .catch(() => { const status = document.getElementById('exodus-logo-status');
          if (status) status.textContent = 'Logo changed on this browser, but could not save to your account. Try again.'; });
      applyExodusLogo();
    });
    grid.append(button);
  });
}

window.addEventListener('storage', event => {
  if (event.key === KEY || event.key === null) {
    choice = readChoice();
    applyExodusLogo();
  }
});
// Exodus: workspace name and logo (both pages load this module).
startWorkspaceBrand();
document.addEventListener(BRAND_EVENT, () => applyExodusLogo());
// Login has no theme picker, but should use the same saved logo choice.
applyExodusLogo();

// Load the signed-in account's choice; never fetch personal settings on login.
if (document.getElementById('settings-modal')) {
  fetch('/api/prefs/logo-variant', {credentials:'same-origin', cache:'no-store'})
    .then(response => response.ok ? response.json() : null)
    .then(data => {
      if (data && !choiceEdited && variants.some(([key]) => key === data.value)) {
        choice = data.value; Storage.set(KEY, choice); applyExodusLogo();
      }
    }).catch(() => {});
}
