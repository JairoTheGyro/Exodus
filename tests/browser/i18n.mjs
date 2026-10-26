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
  // ── Wave 2: sidebar, menus and toasts ──
  await app.evaluate(() => {
    document.body.insertAdjacentHTML('beforeend', `
      <nav id="sidebar"><div class="list-item"><span class="grow">Calendar</span></div>
        <div class="list-item session-item"><span class="grow text-ellipsis">Notes</span></div>
        <div class="session-folder-header"><span class="folder-name">Library</span></div></nav>
      <div id="toast" class="toast" role="status"></div>`);
  });
  await app.waitForFunction(() => document.querySelector('#sidebar .grow').textContent === 'Calendario');
  // A chat titled "Notes" and a folder named "Library" are people's words: untouched.
  assert.equal(await app.evaluate(() => document.querySelector('.session-item .text-ellipsis').textContent), 'Notes');
  assert.equal(await app.evaluate(() => document.querySelector('.folder-name').textContent), 'Library');
  const toast = async text => {
    await app.evaluate(t => { const el = document.getElementById('toast'); el.textContent = ''; const span = document.createElement('span'); span.textContent = t; el.append(span); }, text);
    await app.waitForTimeout(50);
    return app.evaluate(() => document.getElementById('toast').textContent);
  };
  assert.equal(await toast('Session deleted'), 'Sesión eliminada');
  assert.equal(await toast('Session renamed to Plan B'), 'Sesión renombrada a Plan B');
  assert.equal(await toast('Install failed: disk full'), 'No se pudo instalar: disk full');
  assert.equal(await toast('3 sessions restored'), '3 sesiones restauradas');
  assert.equal(await toast('Something brand new happened'), 'Something brand new happened');
  // Menus appear later, anywhere in the page.
  await app.evaluate(() => {
    const menu = document.createElement('div');
    menu.className = 'dropdown session-dropdown-menu';
    menu.innerHTML = '<button class="dropdown-item-compact">Rename</button><button class="dropdown-item-compact" title="Delete chat">Delete</button>';
    document.body.append(menu);
  });
  await app.waitForFunction(() => document.querySelector('.session-dropdown-menu button').textContent === 'Renombrar');
  assert.equal(await app.evaluate(() => document.querySelectorAll('.session-dropdown-menu button')[1].getAttribute('title')), 'Eliminar chat');
  // ── Wave 3: Notes, Calendar, Email and Documents ──
  await app.evaluate(() => {
    document.body.insertAdjacentHTML('beforeend', `
      <div id="calendar-modal"><span class="cal-title"><span class="cal-title-month">October</span> 2026</span>
        <button id="w3-new" title="New event">New</button><div class="cal-event-name" id="w3-event">Today</div>
        <input id="w3-search" placeholder="Search all events…" value="Today"></div>
      <div id="notes-pane"><div class="note-card"><div class="note-card-title" id="w3-note">Notes</div>
        <div class="note-content-preview" id="w3-note-body">Delete</div></div><p id="w3-empty">No notes yet</p></div>
      <div id="email-lib-modal"><div class="email-subject" id="w3-subject">Delete</div><button id="w3-reply">Reply All</button>
        <span class="memory-count" id="w3-count">3 emails</span></div>
      <div id="doc-editor-pane"><span class="doc-tab-title" id="w3-doc">Untitled</span><button id="w3-bold" title="Bold (Ctrl+B)">B</button>
        <div contenteditable="true" id="w3-body">Delete</div></div>`);
  });
  await app.waitForFunction(() => document.getElementById('w3-empty').textContent === 'Todavía no hay notas');
  const w3 = await app.evaluate(() => {
    const $ = id => document.getElementById(id);
    return { month: document.querySelector('.cal-title-month').textContent, newTitle: $('w3-new').title, newText: $('w3-new').textContent,
      event: $('w3-event').textContent, hint: $('w3-search').placeholder, typed: $('w3-search').value,
      note: $('w3-note').textContent, noteBody: $('w3-note-body').textContent, subject: $('w3-subject').textContent,
      reply: $('w3-reply').textContent, count: $('w3-count').textContent, doc: $('w3-doc').textContent,
      bold: $('w3-bold').title, body: $('w3-body').textContent };
  });
  assert.deepEqual(w3, { month: 'Octubre', newTitle: 'Nuevo evento', newText: 'Nuevo', event: 'Today', hint: 'Buscar en todos los eventos…',
    typed: 'Today', note: 'Notes', noteBody: 'Delete', subject: 'Delete', reply: 'Responder a todos', count: '3 correos',
    doc: 'Untitled', bold: 'Negrita (Ctrl+B)', body: 'Delete' });
  console.log('PASS: translations on sign-in, Home/Settings content, patterns, protected content, brand, restore, wave 3 windows');
} finally {
  await browser.close();
}
