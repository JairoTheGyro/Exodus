// Workspace look (Apple-like) and the Dock, in a real browser against the real modules and stylesheet.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', e => console.log('PAGEERROR', e.message));
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(async () => {
    localStorage.clear();
    document.head.innerHTML = '<link rel="stylesheet" href="/static/css/91-look-apple.css">';
    document.body.innerHTML = `
      <nav id="sidebar"><button id="home-sidebar-button">Home</button>
        <button id="sidebar-new-chat-btn">New chat</button>
        <span id="email-section-title"><svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16"/></svg>Email</span>
        <div id="tool-calendar-btn" class="list-item"><svg viewBox="0 0 24 24"><path d="M3 4h18v18H3z"/></svg>Calendar</div>
        <div id="tool-notes-btn" class="list-item" style="display:none">Notes</div>
        <div id="tool-calculator-btn" class="list-item">Calculator</div>
        <button id="user-bar-settings">Settings</button></nav>
      <div class="modal hidden" id="calendar-modal"><div class="modal-content"><div class="modal-header"><h4>Calendar</h4><button class="close-btn">✖</button></div></div></div>
      <div id="settings-rows"></div>`;
    window.__clicks = [];
    for (const b of document.querySelectorAll('#sidebar > *')) b.addEventListener('click', () => window.__clicks.push(b.id));
    document.getElementById('tool-calendar-btn').addEventListener('click', () => document.getElementById('calendar-modal').classList.remove('hidden'));
    const look = await import('/static/js/apps/workspaceLook.js');
    const dock = await import('/static/js/apps/dock.js');
    const settings = await import('/static/js/settings/workspaceLookSettings.js');
    window.__look = look;
    look.followWorkspaceLook();
    look.applyWorkspaceLook();
    dock.mountDock();
    settings.mountWorkspaceLook(document.getElementById('settings-rows'));
  });
  const state = () => page.evaluate(() => ({
    look: document.documentElement.dataset.uiLook || 'exodus',
    dockHidden: document.getElementById('app-dock').hidden,
    items: [...document.querySelectorAll('#app-dock [data-dock-item]')].map(b => b.dataset.dockItem),
    dockSelect: !!document.getElementById('workspace-dock-select'),
  }));

  // Default: the Exodus look, no Dock.
  let s = await state();
  assert.equal(s.look, 'exodus');
  assert.equal(s.dockHidden, true);
  assert.equal(s.dockSelect, false);

  // Choose Apple-like in Settings.
  await page.selectOption('#workspace-look-select', 'apple');
  s = await state();
  assert.equal(s.look, 'apple');
  assert.equal(s.dockHidden, false);
  assert.equal(s.dockSelect, true);
  // Notes is hidden in the sidebar, so it isn't in the Dock; Clock has no button here.
  assert.deepEqual(s.items, ['home', 'chat', 'email', 'calendar', 'calculator', 'settings']);
  assert.equal(await page.locator('#app-dock .app-dock-separator').count(), 2);
  assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem('exodus-workspace-look-v1'))).look, 'apple');

  // The look's styling: system font for the default mono font, round red close button first, on the left.
  const styled = await page.evaluate(() => {
    const close = document.querySelector('.close-btn');
    const cs = getComputedStyle(close);
    return { font: getComputedStyle(document.documentElement).getPropertyValue('--font-family'), order: cs.order, bg: cs.backgroundColor, radius: cs.borderTopLeftRadius };
  });
  assert.match(styled.font, /system-ui|-apple-system/);
  assert.equal(styled.order, '-2'); // red close first, then yellow minimize (-1)
  assert.equal(styled.bg, 'rgb(255, 95, 87)');
  assert.equal(styled.radius, '50%');
  // A font chosen on purpose stays; the Temple presentation keeps its own chrome.
  const kept = await page.evaluate(async () => {
    document.documentElement.style.setProperty('--font-family', "'OpenDyslexic', sans-serif");
    await new Promise(r => setTimeout(r, 30));
    const font = getComputedStyle(document.documentElement).getPropertyValue('--font-family');
    const flag = document.documentElement.dataset.uiFont;
    document.documentElement.classList.add('theme-temple');
    const order = getComputedStyle(document.querySelector('.close-btn')).order;
    document.documentElement.classList.remove('theme-temple');
    document.documentElement.style.removeProperty('--font-family');
    await new Promise(r => setTimeout(r, 30));
    return { font, flag, order, back: document.documentElement.dataset.uiFont };
  });
  assert.match(kept.font, /OpenDyslexic/);
  assert.equal(kept.flag, 'chosen');
  assert.equal(kept.order, '0');
  assert.equal(kept.back, 'mono');

  // Auto-hide: hidden until the pointer reaches the bottom edge.
  const revealed = () => page.evaluate(() => document.getElementById('app-dock').classList.contains('is-revealed'));
  assert.equal(await revealed(), false);
  await page.mouse.move(640, 798);
  await page.waitForFunction(() => document.getElementById('app-dock').classList.contains('is-revealed'));
  // Clicking a Dock icon presses the same sidebar button; its window gets the open dot.
  await page.click('#app-dock [data-dock-item="calendar"]');
  await page.waitForFunction(() => document.querySelector('[data-dock-item="calendar"]').classList.contains('is-open'));
  assert.deepEqual(await page.evaluate(() => window.__clicks), ['tool-calendar-btn']);
  assert.equal(await page.getAttribute('[data-dock-item="calendar"]', 'aria-label'), 'Calendar (open)');
  await page.evaluate(() => document.getElementById('calendar-modal').classList.add('hidden'));
  await page.waitForFunction(() => !document.querySelector('[data-dock-item="calendar"]').classList.contains('is-open'));
  // Minimized windows still count as open.
  await page.evaluate(() => document.getElementById('calendar-modal').classList.add('modal-minimized'));
  await page.waitForFunction(() => document.querySelector('[data-dock-item="calendar"]').classList.contains('is-open'));

  // A section shown again in Settings → Sidebar reappears; added buttons (Clock) too.
  await page.evaluate(() => {
    document.getElementById('tool-notes-btn').style.display = '';
    const clock = document.createElement('div'); clock.id = 'tool-clock-btn'; clock.textContent = 'Clock';
    document.getElementById('sidebar').append(clock);
  });
  await page.waitForFunction(() => document.querySelector('[data-dock-item="notes"]') && document.querySelector('[data-dock-item="clock"]'));

  // Always show / Hide.
  await page.selectOption('#workspace-dock-select', 'always');
  assert.equal(await page.evaluate(() => document.documentElement.dataset.dockMode), 'always');
  assert.equal(await page.isVisible('.app-dock-hotspot'), false);
  await page.selectOption('#workspace-dock-select', 'off');
  assert.equal((await state()).dockHidden, true);

  // Back to the Exodus look: no Dock, no Apple styling.
  await page.selectOption('#workspace-dock-select', 'auto');
  await page.selectOption('#workspace-look-select', 'exodus');
  s = await state();
  assert.equal(s.look, 'exodus');
  assert.equal(s.dockHidden, true);
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.close-btn')).order), '0');

  // Phones: the Dock never shows (it would cover the chat box).
  await page.evaluate(() => window.__look.setWorkspaceLook({ look: 'apple', dock: 'always' }));
  await page.setViewportSize({ width: 390, height: 800 });
  assert.equal(await page.isVisible('#app-dock'), false);
  console.log('PASS: workspace look and dock');
} finally {
  await browser.close();
}
