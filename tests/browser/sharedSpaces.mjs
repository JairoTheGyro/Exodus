// Shared spaces UI in a real browser against the real modules: the
// Settings → Account → Spaces card and the Notes badge / "Share to" menu.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    document.body.innerHTML = '<div id="rows"></div>';
    window.__calls = [];
    window.__data = {
      me: 'mom',
      spaces: [{
        id: 's1', name: 'Family', created_by: 'mom', role: 'manager', can_manage: true, note_count: 2,
        members: [{ username: 'mom', role: 'manager' }, { username: 'dad', role: 'member' }],
      }, {
        id: 's2', name: 'Book club', created_by: 'ana', role: 'member', can_manage: false, note_count: 1,
        members: [{ username: 'ana', role: 'manager' }, { username: 'mom', role: 'member' }],
      }],
    };
    window.__api = async (url, init = {}) => {
      window.__calls.push({ url, method: init.method || 'GET', body: init.body || null });
      if (url === '/api/spaces' && !init.method) return new Response(JSON.stringify(window.__data));
      if (url.endsWith('/members') && init.body?.includes('ghost')) {
        return new Response(JSON.stringify({ detail: 'There is no account with that username.' }), { status: 404 });
      }
      return new Response('{}');
    };
  });
  await page.evaluate(async () => {
    const { mountSpacesSettings } = await import('/static/js/settings/spacesSettings.js');
    await mountSpacesSettings(document.getElementById('rows'), {
      api: window.__api, confirmFn: async () => true, promptFn: async () => 'Peraltas',
    });
  });
  const spaces = () => page.evaluate(() => [...document.querySelectorAll('.spaces-space')].map(box => ({
    name: box.querySelector('.spaces-name').textContent,
    meta: box.querySelector('.spaces-meta').textContent,
    actions: [...box.querySelectorAll('.spaces-actions [data-space-action]')].map(b => b.dataset.spaceAction),
    members: [...box.querySelectorAll('[data-member]')].map(li => li.textContent),
    canAdd: !!box.querySelector('.spaces-add'),
  })));

  let s = await spaces();
  assert.deepEqual(s.map(x => x.name), ['Family', 'Book club']);
  assert.equal(s[0].meta, '2 members · 2 shared notes');
  assert.equal(s[1].meta, '2 members · 1 shared note');
  assert.deepEqual(s[0].actions, ['rename', 'delete', 'leave']);
  assert.deepEqual(s[1].actions, ['leave']);
  assert.deepEqual(s[0].members, ['mom (you)Manager', 'dadMemberMake managerRemove']);
  assert.equal(s[0].canAdd, true);
  assert.equal(s[1].canAdd, false);

  const posts = async () => page.evaluate(() => window.__calls.filter(c => c.method !== 'GET').map(c => [c.method, c.url, c.body]));
  // Each action sends one request, then reloads the card; wait for both.
  const step = async fn => {
    const before = await page.evaluate(() => window.__calls.length);
    await fn();
    await page.waitForFunction(n => window.__calls.length >= n + 2, before);
    // The reload's render runs a few microtasks after its request is recorded.
    await page.waitForTimeout(100);
    await page.waitForFunction(() => document.querySelector('.spaces-create'));
  };
  await step(async () => { await page.fill('.spaces-create input', 'Work'); await page.press('.spaces-create input', 'Enter'); });
  await step(async () => { await page.fill('[data-space-id="s1"] .spaces-add input', 'kid'); await page.click('[data-space-id="s1"] .spaces-add [data-space-action="add"]'); });
  await step(() => page.click('[data-space-id="s1"] [data-member="dad"] [data-space-action="promote"]'));
  await step(() => page.click('[data-space-id="s1"] [data-member="dad"] [data-space-action="remove"]'));
  await step(() => page.click('[data-space-id="s2"] [data-space-action="leave"]'));
  await step(() => page.click('[data-space-id="s1"] [data-space-action="rename"]'));
  await step(() => page.click('[data-space-id="s1"] [data-space-action="delete"]'));
  assert.deepEqual(await posts(), [
    ['POST', '/api/spaces', '{"name":"Work"}'],
    ['POST', '/api/spaces/s1/members', '{"username":"kid"}'],
    ['POST', '/api/spaces/s1/members', '{"username":"dad","role":"manager"}'],
    ['DELETE', '/api/spaces/s1/members/dad', null],
    ['DELETE', '/api/spaces/s2/members/mom', null],
    ['PUT', '/api/spaces/s1', '{"name":"Peraltas"}'],
    ['DELETE', '/api/spaces/s1', null],
  ]);

  // A refused request shows the server's reason.
  await page.fill('[data-space-id="s1"] .spaces-add input', 'ghost');
  await page.click('[data-space-id="s1"] .spaces-add [data-space-action="add"]');
  await page.waitForFunction(() => document.querySelector('.spaces-msg')?.textContent);
  assert.equal(await page.textContent('.spaces-msg'), 'There is no account with that username.');

  // Notes: badge text, and "Share to" only for the owner and only into spaces you belong to.
  const notes = await page.evaluate(async () => {
    const mod = await import('/static/js/features/notes/ui/spaces.js');
    let rendered = 0;
    mod._resetSpacesForTests();
    await mod.ensureSpaces(() => { rendered += 1; }, { fetchImpl: async () => new Response(JSON.stringify(window.__data)) });
    await new Promise(r => setTimeout(r, 0));
    const box = document.createElement('div');
    box.innerHTML = mod.spaceBadgeHtml({ space_id: 's1', owner: 'dad' }) + '|' + mod.spaceBadgeHtml({ space_id: 's1', owner: 'mom' }) + '|' + mod.spaceBadgeHtml({ space_id: null });
    const own = { id: 'n1', owner: 'mom', space_id: null };
    const menu = document.createElement('div');
    const saved = [];
    mod.addShareItems(menu, own, { close: () => {}, save: async id => { saved.push(id); return { space_id: id || null }; }, onSaved: () => {}, toast: () => {} });
    const choices = [...menu.querySelectorAll('[data-share-space]')].map(b => [b.dataset.shareSpace, b.textContent, b.getAttribute('aria-pressed')]);
    menu.querySelector('[data-share-space="s1"]').click();
    await new Promise(r => setTimeout(r, 0));
    const othersMenu = document.createElement('div');
    mod.addShareItems(othersMenu, { id: 'n2', owner: 'dad', space_id: 's1' }, { close() {}, save: async () => ({}) });
    return { rendered, badge: box.textContent, choices, saved, ownNow: own.space_id, othersItems: othersMenu.children.length };
  });
  assert.equal(notes.rendered, 1);
  assert.equal(notes.badge, 'Family · by dad|Family|');
  assert.deepEqual(notes.choices, [['', '✓Only me', 'true'], ['s1', 'Family', 'false'], ['s2', 'Book club', 'false']]);
  assert.deepEqual(notes.saved, ['s1']);
  assert.equal(notes.ownNow, 's1');
  assert.equal(notes.othersItems, 0);
  console.log('PASS: spaces settings card, member actions, error message, note badge and share menu');
} finally {
  await browser.close();
}
