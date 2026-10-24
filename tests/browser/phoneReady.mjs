// Exodus on phones, in a real browser at iPhone size: the sign-in page fits,
// its fields don't trigger iOS zoom, the home-screen name follows the
// workspace name, and the welcome shows above Home's first-run screen.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium, devices } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext({ ...devices['iPhone 13'] });
  const page = await ctx.newPage();
  // Serve the sign-in page at /login so its relative static/ links resolve;
  // the server API is faked as "not configured yet / no brand".
  const login = readFileSync('static/login.html', 'utf8').replaceAll('{{CSP_NONCE}}', 'test');
  await page.route('**/login', route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: login }));
  await page.route('**/api/**', route => route.fulfill({ json: {} }));
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => [...document.styleSheets].length > 0
    && [...document.styleSheets].every(sheet => { try { return sheet.cssRules.length > 0; } catch (_) { return false; } }), null, { timeout: 60000 });

  const signIn = await page.evaluate(() => {
    const fields = [...document.querySelectorAll('input[type=text], input[type=password], input:not([type])')]
      .filter(e => e.getBoundingClientRect().width > 0);
    return {
      scrollW: document.documentElement.scrollWidth, W: window.innerWidth,
      fieldSizes: fields.map(e => parseFloat(getComputedStyle(e).fontSize)),
      viewport: document.querySelector('meta[name=viewport]').content,
      capable: document.querySelector('meta[name=apple-mobile-web-app-capable]')?.content,
      title: document.querySelector('meta[name=apple-mobile-web-app-title]')?.content,
    };
  });
  assert.ok(signIn.scrollW <= signIn.W, `sign-in page scrolls sideways: ${signIn.scrollW} > ${signIn.W}`);
  assert.ok(signIn.fieldSizes.length >= 2 && signIn.fieldSizes.every(size => size >= 16), `iOS zooms on fields under 16px: ${signIn.fieldSizes}`);
  assert.match(signIn.viewport, /maximum-scale=1/); // the iPhone user agent gets the no-zoom-on-focus setting
  assert.equal(signIn.capable, 'yes');
  assert.equal(signIn.title, 'Exodus');

  // A custom workspace name names the home-screen icon too.
  const named = await page.evaluate(async () => {
    const m = await import('/static/js/workspaceBrand.js');
    await m.refreshWorkspaceBrand({ fetchImpl: async () => new Response(JSON.stringify({ name: 'Peralta Family Hub', custom_name: true, has_logo: false, logo_url: null })) });
    return document.querySelector('meta[name=apple-mobile-web-app-title]').content;
  });
  assert.equal(named, 'Peralta Family Hub');

  // The welcome sits above Home's first-run screen and stays visible while
  // Home hides everything else (html[data-workspace-mode=choose]).
  const layered = await ctx.newPage();
  const css = [...readFileSync('static/index.html', 'utf8').matchAll(/<link rel="stylesheet" href="(\/static\/[^"?]+\.css)/g)].map(m => `<link rel="stylesheet" href="${m[1]}">`).join('');
  await layered.route('**/layers', route => route.fulfill({ contentType: 'text/html; charset=utf-8',
    body: `<!doctype html><html data-workspace-mode="choose"><head><meta charset="utf-8">${css}</head><body><main id="workspace-home"><section id="home-choice">Choose</section></main></body></html>` }));
  await layered.goto(`${origin}/layers`, { waitUntil: 'networkidle' });
  // Wait until every stylesheet has actually loaded and parsed.
  await layered.waitForFunction(() => [...document.styleSheets].length > 10
    && [...document.styleSheets].every(sheet => { try { return sheet.cssRules.length > 0; } catch (_) { return false; } }), null, { timeout: 60000 });
  const state = await layered.evaluate(async () => {
    const m = await import('/static/js/welcome/welcomeSetup.js');
    m.openWelcome({ fetchImpl: async () => new Response('{}'), reload: () => {} });
    const w = document.getElementById('exodus-welcome');
    const skip = w.querySelector('[data-welcome="skip"]').getBoundingClientRect();
    const hit = document.elementFromPoint(skip.left + skip.width / 2, skip.top + skip.height / 2);
    return {
      visibility: getComputedStyle(w).visibility,
      homeChoice: getComputedStyle(document.getElementById('home-choice')).display,
      skipReachable: !!hit?.closest('[data-welcome="skip"]'),
      sheets: [...document.styleSheets].map(s => (s.href || '').split('/').pop() + ':' + (() => { try { return s.cssRules.length; } catch { return 'x'; } })()).join(' '),
      bodyClass: document.body.className,
    };
  });
  assert.deepEqual({ visibility: state.visibility, homeChoice: state.homeChoice, skipReachable: state.skipReachable }, { visibility: 'visible', homeChoice: 'none', skipReachable: true });
  console.log('PASS: phone sign-in fits, no iOS field zoom, home-screen name, welcome above Home');
} finally {
  await browser.close();
}
