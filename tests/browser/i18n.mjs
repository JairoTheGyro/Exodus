// Exodus translations in a real browser: the real sign-in page, and Home /
// Settings style content, switching to Spanish and back.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const loginHtml = fs.readFileSync(new URL('../../static/login.html', import.meta.url), 'utf8');
const browser = await chromium.launch({ headless: true });
try {
  // ── Sign-in page, served at /login like the app does ──
  const ctx = await browser.newContext({ locale: 'en-US' });
  const page = await ctx.newPage();
  let brand = { name: 'Exodus', custom_name: false, has_logo: false, version: 0 };
  await page.route('**/login', route => route.fulfill({ contentType: 'text/html', body: loginHtml.replaceAll('{{CSP_NONCE}}', 'test') }));
  await page.route('**/api/workspace/brand', route => route.fulfill({ json: brand }));
  await page.route(/\/api\/(auth|version|prefs)/, route => route.fulfill({ status: 404, json: {} }));
  await page.goto(`${origin}/login`);
  const heading = () => page.evaluate(() => ({
    lang: document.documentElement.lang,
    label: document.querySelector('label[for="username"]')?.textContent.trim(),
    submit: document.getElementById('submitBtn')?.textContent.trim(),
    menu: document.getElementById('login-language')?.value,
    options: [...document.querySelectorAll('#login-language option')].map(o => o.textContent),
  }));
  await page.waitForFunction(() => document.querySelectorAll('#login-language option').length === 2);
  let s = await heading();
  assert.equal(s.lang, 'en');
  assert.equal(s.label, 'Username');
  assert.deepEqual(s.options, ['English', 'Español (Latinoamérica)']);
  await page.selectOption('#login-language', 'es-419');
  await page.waitForFunction(() => document.querySelector('label[for="username"]').textContent.trim() === 'Usuario');
  s = await heading();
  assert.equal(s.lang, 'es-419');
  // The test server reports no accounts yet, so the page may be in first-time setup.
  assert.ok(['Iniciar sesión', 'Crear cuenta de administrador'].includes(s.submit), s.submit);
  // The choice survives a reload (kept in this browser before sign-in).
  await page.reload();
  await page.waitForFunction(() => document.querySelector('label[for="username"]').textContent.trim() === 'Usuario');
  assert.equal((await heading()).menu, 'es-419');
  // A Spanish browser starts in Spanish without any saved choice.
  const es = await browser.newContext({ locale: 'es-MX' });
  const esPage = await es.newPage();
  await esPage.route('**/login', route => route.fulfill({ contentType: 'text/html', body: loginHtml.replaceAll('{{CSP_NONCE}}', 'test') }));
  await esPage.route(/\/api\//, route => route.fulfill({ status: 404, json: {} }));
  await esPage.goto(`${origin}/login`);
  await esPage.waitForFunction(() => document.querySelector('label[for="username"]').textContent.trim() === 'Usuario');
  await es.close();

  // ── Home / Settings style content ──
  const app = await ctx.newPage();
  await app.route(/\/api\/prefs\/language/, route => route.fulfill({ json: { key: 'language', value: null } }));
  await app.route('**/api/workspace/brand', route => route.fulfill({ json: brand }));
  await app.goto(`${origin}/static/manifest.json`);
  await app.evaluate(() => {
    localStorage.setItem('exodus-language', 'en');
    document.head.innerHTML = '<title>Home · Exodus</title>';
    document.body.innerHTML = `
      <div id="settings-modal"><h2 id="s-title">Settings</h2><button id="s-close" aria-label="Close settings">x</button>
        <p id="s-unknown">A sentence nobody translated yet.</p><textarea id="s-field">Settings</textarea></div>
      <main id="workspace-home"><h1 id="greeting">Good evening, admin.</h1><span id="eyebrow">Welcome to Exodus</span>
        <div class="home-title" data-i18n-skip id="user-note">Settings</div></main>
      <div id="chat-history"><p id="chat">Settings</p></div>`;
  });
  await app.evaluate(async () => { const m = await import('/static/js/i18n.js'); window.__i18n = m; await m.startTranslations(); });
  const read = () => app.evaluate(() => Object.fromEntries(['s-title', 's-unknown', 'greeting', 'eyebrow', 'user-note', 'chat']
    .map(id => [id, document.getElementById(id).textContent])
    .concat([['close', document.getElementById('s-close').getAttribute('aria-label')], ['field', document.getElementById('s-field').value],
      ['title', document.title], ['lang', document.documentElement.lang], ['locale', globalThis.__exodusLocale ?? null]])));
  let r = await read();
  assert.equal(r['s-title'], 'Settings');
  assert.equal(r.locale, null);

  await app.evaluate(() => window.__i18n.setLanguage('es-419'));
  r = await read();
  assert.equal(r['s-title'], 'Configuración');
  assert.equal(r.close, 'Cerrar configuración');
  assert.equal(r.greeting, 'Buenas noches, admin.');
  assert.equal(r.eyebrow, 'Bienvenido a Exodus');
  assert.equal(r.title, 'Inicio · Exodus');
  assert.equal(r.lang, 'es-419');
  assert.equal(r.locale, 'es-419');
  // Untranslated text stays English; people's content and fields are untouched.
  assert.equal(r['s-unknown'], 'A sentence nobody translated yet.');
  assert.equal(r.field, 'Settings');
  assert.equal(r['user-note'], 'Settings');
  assert.equal(r.chat, 'Settings');

  // Text the app renders later is translated too (Home's greeting ticks every second).
  await app.evaluate(() => { document.getElementById('greeting').textContent = 'Good morning, admin.'; });
  await app.waitForFunction(() => document.getElementById('greeting').textContent === 'Buenos días, admin.');

  // Works with a custom workspace name.
  brand = { name: 'Peralta Hub', custom_name: true, has_logo: false, version: 2 };
  await app.evaluate(async () => { const b = await import('/static/js/workspaceBrand.js'); b.startWorkspaceBrand(); await b.refreshWorkspaceBrand(); });
  await app.waitForFunction(() => document.getElementById('eyebrow').textContent === 'Bienvenido a Peralta Hub');

  // Back to English restores the original wording.
  await app.evaluate(() => window.__i18n.setLanguage('en'));
  r = await read();
  assert.equal(r['s-title'], 'Settings');
  assert.equal(r.greeting, 'Good morning, admin.');
  assert.equal(r.eyebrow, 'Welcome to Peralta Hub');
  assert.equal(r.close, 'Close settings');
  assert.equal(r.lang, 'en');

  // t() for code: exact text, patterns and variables.
  await app.evaluate(() => window.__i18n.setLanguage('es-419'));
  const fromCode = await app.evaluate(() => [window.__i18n.t('Sign In'), window.__i18n.t('Good afternoon, {name}.', { name: 'Ana' }), window.__i18n.t('Not in catalog')]);
  assert.deepEqual(fromCode, ['Iniciar sesión', 'Buenas tardes, Ana.', 'Not in catalog']);
  console.log('PASS: translations on sign-in, Home/Settings content, patterns, protected content, brand, restore');
} finally {
  await browser.close();
}
