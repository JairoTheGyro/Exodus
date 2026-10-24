// Exodus workspace name and logo on the page, in a real browser against the
// real module, with the server's brand endpoint answered by the test.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  let brand = { name: 'Peralta Hub', custom_name: true, has_logo: true, version: 7 };
  await page.route('**/api/workspace/brand', route => route.fulfill({ json: brand }));
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    localStorage.clear();
    document.head.innerHTML = '<title>Home · Exodus</title><link rel="manifest" href="/static/manifest.json">';
    document.body.innerHTML = `
      <nav id="sidebar"><span class="sidebar-brand-title">Exodus</span><button title="Open Exodus settings">x</button></nav>
      <div id="welcome-screen"><div class="welcome-name">Exodus</div></div>
      <div id="settings-modal">
        <p id="setting-text">Saved on this Exodus server.</p>
        <textarea id="field">Exodus in a form field</textarea>
        <section data-keep-product-name><p id="credit">The open-source foundation of Exodus.</p></section>
      </div>
      <div id="chat-history"><p id="chat">I am building Exodus today.</p></div>`;
  });
  await page.evaluate(async () => {
    const m = await import('/static/js/workspaceBrand.js');
    window.__brand = m;
    m.startWorkspaceBrand();
  });
  const read = () => page.evaluate(() => ({
    title: document.title,
    sidebar: document.querySelector('.sidebar-brand-title').textContent,
    buttonTitle: document.querySelector('#sidebar button').getAttribute('title'),
    welcome: document.querySelector('.welcome-name').textContent,
    setting: document.getElementById('setting-text').textContent,
    field: document.getElementById('field').value,
    credit: document.getElementById('credit').textContent,
    chat: document.getElementById('chat').textContent,
    home: document.getElementById('workspace-home')?.textContent || null,
    logo: window.__brand.workspaceLogoUrl(),
    manifest: document.querySelector('link[rel="manifest"]').getAttribute('href'),
  }));
  await page.waitForFunction(() => document.title === 'Home · Peralta Hub');

  let s = await read();
  assert.equal(s.sidebar, 'Peralta Hub');
  assert.equal(s.buttonTitle, 'Open Peralta Hub settings');
  assert.equal(s.welcome, 'Peralta Hub');
  assert.equal(s.setting, 'Saved on this Peralta Hub server.');
  // Never touched: form fields, the legal credit, people's own content.
  assert.equal(s.field, 'Exodus in a form field');
  assert.equal(s.credit, 'The open-source foundation of Exodus.');
  assert.equal(s.chat, 'I am building Exodus today.');
  assert.equal(s.logo, '/api/workspace/brand/logo?v=7');
  assert.match(s.manifest, /^blob:/);
  const manifest = await page.evaluate(async href => (await fetch(href)).json(), s.manifest);
  assert.equal(manifest.name, 'Peralta Hub');
  assert.equal(manifest.icons[0].src, `${origin}/api/workspace/brand/logo?v=7`);

  // Content the app adds later (Home, re-rendered text, new titles) follows too.
  await page.evaluate(() => {
    const home = document.createElement('main');
    home.id = 'workspace-home';
    home.textContent = 'Welcome to Exodus';
    document.body.append(home);
    document.querySelector('.sidebar-brand-title').textContent = 'Exodus';
    document.title = 'Calendar — Exodus';
  });
  await page.waitForFunction(() => document.getElementById('workspace-home').textContent === 'Welcome to Peralta Hub');
  await page.waitForFunction(() => document.title === 'Calendar — Peralta Hub');
  s = await read();
  assert.equal(s.sidebar, 'Peralta Hub');

  // Back to the default restores the original wording everywhere.
  brand = { name: 'Exodus', custom_name: false, has_logo: false, version: 8 };
  await page.evaluate(() => window.__brand.refreshWorkspaceBrand());
  s = await read();
  assert.equal(s.title, 'Calendar — Exodus');
  assert.equal(s.sidebar, 'Exodus');
  assert.equal(s.welcome, 'Exodus');
  assert.equal(s.home, 'Welcome to Exodus');
  assert.equal(s.setting, 'Saved on this Exodus server.');
  assert.equal(s.buttonTitle, 'Open Exodus settings');
  assert.equal(s.logo, null);
  assert.equal(s.manifest, '/static/manifest.json');

  // The remembered brand paints at once on the next load, before the server answers.
  brand = { name: 'Acme', custom_name: true, has_logo: false, version: 9 };
  await page.evaluate(() => window.__brand.refreshWorkspaceBrand());
  const cached = await page.evaluate(() => JSON.parse(localStorage.getItem('exodus-workspace-brand-v1')));
  assert.deepEqual(cached, { name: 'Acme', has_logo: false, version: 9 });
  console.log('PASS: workspace brand name, logo, manifest, live updates, protected areas, restore, cache');
} finally {
  await browser.close();
}
