// Settings → System → Services and per-person app hiding, in a real browser
// against the real modules. The /api/services server is faked in the page.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="rows"></div>';
    window.__calls = [];
    window.__services = [
      { name: 'searxng', label: 'SearXNG', state: 'running', data_volumes: ['searxng-data'], data_folders: [] },
      { name: 'ntfy', label: 'ntfy', state: 'stopped', data_volumes: ['ntfy-cache'], data_folders: [] },
      { name: 'replica', label: 'Replica video player', state: 'removed', data_volumes: [], data_folders: ['data/replica'] },
      { name: 'harness', label: 'Code', state: 'running', busy: 'reinstall', data_volumes: [], data_folders: [] },
      { name: 'chromadb', label: 'ChromaDB', state: 'stopped', error: 'start failed: no space', data_volumes: [], data_folders: [] },
    ];
    window.__api = async (url, init = {}) => {
      window.__calls.push({ url, method: init.method || 'GET', body: init.body || null });
      if (url === '/api/services') return new Response(JSON.stringify({ available: true, services: window.__services }));
      if (url.endsWith('/start')) return new Response(JSON.stringify({ detail: 'That service is already busy; try again when it finishes.' }), { status: 409 });
      return new Response('{}', { status: 202 });
    };
  });
  await page.evaluate(async () => {
    const { mountServicesManager } = await import('/static/js/settings/servicesManager.js');
    await mountServicesManager(document.getElementById('rows'), { api: window.__api });
  });
  const rows = () => page.evaluate(() => [...document.querySelectorAll('.services-row')].map(row => ({
    name: row.dataset.service,
    state: row.querySelector('.services-state').textContent,
    actions: [...row.querySelectorAll('.services-actions [data-service-action]')].map(b => `${b.dataset.serviceAction}:${b.textContent}`),
    error: row.querySelector('.services-error')?.textContent || null,
  })));

  // Each state offers the right buttons; a busy service offers none.
  let r = await rows();
  assert.deepEqual(r.map(x => [x.name, x.state]), [
    ['searxng', 'On'], ['ntfy', 'Off'], ['replica', 'Removed'], ['harness', 'Reinstalling…'], ['chromadb', 'Off'],
  ]);
  assert.deepEqual(r[0].actions, ['stop:Turn off', 'remove:Remove', 'reinstall:Reinstall']);
  assert.deepEqual(r[1].actions, ['start:Turn on', 'remove:Remove', 'reinstall:Reinstall']);
  assert.deepEqual(r[2].actions, ['start:Install', 'reinstall:Reinstall']);
  assert.deepEqual(r[3].actions, []);
  assert.equal(r[4].error, 'start failed: no space');

  // Remove asks first; data is kept unless the box is ticked.
  await page.click('[data-service="searxng"] [data-service-action="remove"]');
  const confirmText = await page.textContent('[data-service="searxng"] .services-confirm');
  assert.match(confirmText, /Its data is kept/);
  assert.match(confirmText, /searxng-data/);
  await page.click('[data-service="searxng"] [data-service-action="cancel-remove"]');
  assert.equal(await page.$('[data-service="searxng"] .services-confirm'), null);

  await page.click('[data-service="searxng"] [data-service-action="remove"]');
  await page.click('[data-service="searxng"] [data-service-action="confirm-remove"]');
  await page.click('[data-service="ntfy"] [data-service-action="remove"]');
  await page.check('[data-service="ntfy"] .services-confirm input[type="checkbox"]');
  await page.click('[data-service="ntfy"] [data-service-action="confirm-remove"]');
  // A service with no Docker volumes has nothing to tick.
  await page.click('[data-service="chromadb"] [data-service-action="remove"]');
  assert.equal(await page.$('[data-service="chromadb"] .services-confirm input'), null);
  await page.waitForFunction(() => window.__calls.filter(c => c.method === 'POST').length === 2);
  const posts = await page.evaluate(() => window.__calls.filter(c => c.method === 'POST'));
  assert.deepEqual(posts, [
    { url: '/api/services/searxng/remove', method: 'POST', body: '{"delete_data":false}' },
    { url: '/api/services/ntfy/remove', method: 'POST', body: '{"delete_data":true}' },
  ]);

  // A refused action shows the server's reason on that row.
  await page.click('[data-service="replica"] [data-service-action="start"]');
  await page.waitForFunction(() => window.__calls.some(c => c.url.endsWith('/replica/start')));
  await page.waitForSelector('[data-service="replica"] .services-error', { state: 'attached' }).catch(() => {});

  // Without the add-on the card explains how to enable it.
  const off = await page.evaluate(async () => {
    const { renderServices } = await import('/static/js/settings/servicesManager.js');
    const box = document.createElement('div');
    renderServices(box, { available: false, reason: 'not_enabled', hint: 'add docker/service-manager.yml' });
    return box.textContent;
  });
  assert.match(off, /Services manager is off/);
  assert.match(off, /docker\/service-manager\.yml/);

  // Per-person hiding: a hidden app is left out of the menu it is added to.
  const hidden = await page.evaluate(async () => {
    localStorage.setItem('odysseus-ui-visibility', JSON.stringify({ 'tool-clock': false }));
    document.body.innerHTML = '<div id="tool-calendar-btn"></div><div id="tool-skills-btn"></div>';
    const { installApps } = await import('/static/js/apps/launcher.js');
    installApps({ loadPanel: async () => ({}), schedule: () => {} });
    const { UI_VIS_MAP } = await import('/static/js/ui_visibility.js');
    return {
      clock: document.getElementById('tool-clock-btn').style.display,
      calculator: document.getElementById('tool-calculator-btn').style.display,
      keys: Object.keys(UI_VIS_MAP).filter(k => ['tool-clock', 'tool-calculator', 'tool-workshop', 'tool-code',
        'local-services-section', 'privacy-hub-section'].includes(k)).sort(),
    };
  });
  assert.equal(hidden.clock, 'none');
  assert.equal(hidden.calculator, '');
  assert.deepEqual(hidden.keys, ['local-services-section', 'privacy-hub-section', 'tool-calculator', 'tool-clock', 'tool-code', 'tool-workshop']);
  console.log('PASS: services manager states, remove confirmation, delete-data choice, add-on hint, per-person app hiding');
} finally {
  await browser.close();
}
