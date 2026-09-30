// Temple is a presentation of the existing workspace, not a second app shell.
let active = false;
function fitDesktop() {
  if (!active) return;
  const available = Math.min(window.innerWidth / 640, window.innerHeight / 480);
  // Integer enlargement keeps the 8x8 outlines aligned to screen pixels.
  const scale = available >= 1 ? Math.max(1, Math.floor(available)) : available;
  document.documentElement.style.setProperty('--temple-scale', String(scale));
}
export function applyTemplePresentation(enabled) {
  active = !!enabled;
  document.documentElement.classList.toggle('theme-temple', active);
  let bar = document.getElementById('temple-menu');
  if (active && !bar && document.getElementById('tool-theme-btn')) {
    bar = document.createElement('div');
    bar.id = 'temple-menu';
    bar.setAttribute('aria-label', 'Temple desktop');
    const title = document.createElement('span');
    title.textContent = 'Exodus :: Temple';
    const details = document.createElement('span');
    details.textContent = '640x480 / 16 colors';
    const theme = document.createElement('button');
    theme.type = 'button'; theme.textContent = '[ Themes ]';
    theme.setAttribute('aria-label', 'Change theme');
    theme.onclick = () => document.getElementById('tool-theme-btn')?.click();
    bar.append(title, details, theme);
    document.body.append(bar);
  }
  if (bar) bar.hidden = !active;
  fitDesktop();
  if (!active) document.documentElement.style.removeProperty('--temple-scale');
}
window.addEventListener('resize', fitDesktop);
