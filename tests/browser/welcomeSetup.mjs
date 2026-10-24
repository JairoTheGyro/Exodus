// Exodus welcome setup in a real browser against the real modules; the
// server is faked in the page.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    localStorage.clear();
    document.body.innerHTML = '';
    window.__calls = [];
    window.__reloads = 0;
    window.__opened = [];
    window.__home = { owner: 'sofia', profile: {} };
    window.__pref = { key: 'exodus-welcome', value: null };
    window.__ai = { source: null, ai_free: false, spent_usd: 0, cap_usd: null, connections: { own: [], shared: ['Home GPU'] } };
    window.__fetch = async (url, init = {}) => {
      const method = init.method || 'GET';
      window.__calls.push([method, url, init.body || null]);
      if (url === '/api/home/profile' && method === 'GET') return new Response(JSON.stringify(window.__home));
      if (url === '/api/home/profile') { window.__home.profile.mode = JSON.parse(init.body).mode; return new Response(JSON.stringify({ profile: window.__home.profile })); }
      if (url === '/api/prefs/exodus-welcome' && method === 'GET') return new Response(JSON.stringify(window.__pref));
      if (url === '/api/prefs/exodus-welcome') { window.__pref.value = JSON.parse(init.body).value; return new Response('{}'); }
      if (url === '/api/ai-budget' && method === 'GET') return new Response(JSON.stringify({ ...window.__ai }));
      if (url === '/api/ai-budget') { const body = JSON.parse(init.body); window.__ai = { ...window.__ai, source: body.source, ai_free: body.source === 'off' }; return new Response(JSON.stringify(window.__ai)); }
      if (url === '/api/alerts/phone') return new Response(JSON.stringify({ enabled: true, personal: true, server: 'http://x:8091', topic: 'exodus-AAAAAAAAAAAAAAAAAAAAAAAA' }));
      return new Response('{}');
    };
  });
  const run = code => page.evaluate(code);

  // When it opens by itself.
  const when = await run(async () => {
    const m = await import('/static/js/welcome/welcomeSetup.js');
    const fresh = await m.shouldShowWelcome(window.__fetch);
    window.__home.profile.mode = 'full';
    const chosen = await m.shouldShowWelcome(window.__fetch);
    window.__home.profile = {};
    window.__pref.value = { done: true };
    const done = await m.shouldShowWelcome(window.__fetch);
    window.__pref.value = null;
    const broken = await m.shouldShowWelcome(async () => new Response('', { status: 500 }));
    return { fresh, chosen, done, broken };
  });
  assert.deepEqual(when, { fresh: true, chosen: false, done: false, broken: false });

  // Walk every step.
  await run(async () => {
    const m = await import('/static/js/welcome/welcomeSetup.js');
    window.__closed = m.maybeStartWelcome({
      fetchImpl: window.__fetch, reload: () => { window.__reloads += 1; }, openSettings: tab => { window.__opened.push(tab); },
    });
  });
  await page.waitForSelector('#exodus-welcome');
  const stepOf = () => page.getAttribute('.exodus-welcome-body', 'data-step');
  assert.equal(await stepOf(), 'hello');
  assert.equal(await page.textContent('#exodus-welcome-title'), 'Welcome to Exodus');
  assert.match(await page.textContent('.exodus-welcome-body'), /Hi sofia!/);
  assert.ok((await page.locator('#exodus-welcome-language option').count()) >= 2);
  assert.equal(await page.isVisible('[data-welcome="back"]'), false);

  await page.click('[data-welcome="next"]');
  assert.equal(await stepOf(), 'workspace');
  await page.waitForSelector('[data-ai-source="shared"]');
  assert.match(await page.textContent('.exodus-welcome-ai'), /Available: Home GPU\./);
  await page.click('[data-ai-source="off"]');
  await page.waitForFunction(() => document.querySelector('[data-ai-source="off"]')?.getAttribute('aria-checked') === 'true');
  assert.deepEqual(await run(() => window.__calls.filter(c => c[1] === '/api/ai-budget' && c[0] === 'PUT').map(c => c[2])), ['{"source":"off"}']);

  await page.click('[data-welcome="next"]');
  assert.equal(await stepOf(), 'look');
  assert.ok((await page.locator('.exodus-welcome-looks .app-look-row').count()) >= 2);
  await page.click('[data-welcome="back"]');
  assert.equal(await stepOf(), 'workspace');
  await page.click('[data-welcome="next"]');
  await page.click('[data-welcome="next"]');
  assert.equal(await stepOf(), 'connect');
  await page.click('[data-welcome="next"]');
  assert.equal(await stepOf(), 'phone');
  await page.waitForSelector('.exodus-welcome-phone .phone-alerts-topic');
  await page.click('[data-welcome="next"]');
  assert.equal(await stepOf(), 'done');
  assert.equal(await page.isVisible('[data-welcome="skip"]'), false);
  assert.equal(await page.textContent('[data-welcome="next"]'), 'Start using it');
  await page.click('[data-welcome="next"]');
  const result = await run(() => window.__closed);
  assert.deepEqual(result, { skipped: false, mode: 'ai-free' });
  assert.equal(await page.$('#exodus-welcome'), null);
  assert.equal(await run(() => window.__pref.value.done), true);
  assert.equal(await run(() => window.__reloads), 1); // new workspace choice applies right away

  // Skipping (button or Escape) remembers it and doesn't reload; "Connect email" opens Settings.
  const skipped = await run(async () => {
    const m = await import('/static/js/welcome/welcomeSetup.js');
    window.__pref.value = null;
    const a = m.openWelcome({ fetchImpl: window.__fetch, reload: () => { window.__reloads += 1; } });
    document.querySelector('[data-welcome="skip"]').click();
    const first = await a;
    const b = m.openWelcome({ fetchImpl: window.__fetch, reload: () => { window.__reloads += 1; } });
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    const second = await b;
    const c = m.openWelcome({ fetchImpl: window.__fetch, openSettings: tab => { window.__opened.push(tab); }, reload: () => {} });
    for (let i = 0; i < 3; i += 1) document.querySelector('[data-welcome="next"]').click();
    document.querySelector('[data-welcome-open="email"]').click();
    await c;
    await new Promise(r => setTimeout(r, 0));
    return { first, second, pref: window.__pref.value.skipped, reloads: window.__reloads, opened: window.__opened, open: !!document.getElementById('exodus-welcome') };
  });
  assert.deepEqual(skipped.first, { skipped: true, mode: null });
  assert.deepEqual(skipped.second, { skipped: true, mode: null });
  assert.equal(skipped.reloads, 1);
  assert.deepEqual(skipped.opened, ['email']);
  assert.equal(skipped.open, false);
  console.log('PASS: welcome opens for new accounts only, every step, workspace choice, skip, escape, connect email');
} finally {
  await browser.close();
}
