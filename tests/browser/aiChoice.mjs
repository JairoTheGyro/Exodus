// Settings → Account → Your AI, in a real browser against the real module.
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
    window.__opened = [];
    window.__state = { me: 'mom', is_admin: true, source: null, ai_free: false, self_cap_usd: null, admin_cap_usd: null,
      cap_usd: null, spent_usd: 1.234, paused: false, connections: { own: [], shared: ['Home GPU'] } };
    window.__api = async (url, init = {}) => {
      const method = init.method || 'GET';
      window.__calls.push([method, url, init.body || null]);
      if (url === '/api/ai-budget' && method === 'PUT') {
        const b = JSON.parse(init.body);
        if (b.self_cap_usd === -1) return new Response(JSON.stringify({ detail: 'The cap must be between $0 and $100,000.' }), { status: 400 });
        const s = window.__state;
        if (b.source) { s.source = b.source; s.ai_free = b.source === 'off'; }
        if (b.clear_cap) s.self_cap_usd = null;
        if (b.self_cap_usd != null) s.self_cap_usd = b.self_cap_usd;
        s.cap_usd = s.self_cap_usd;
        s.paused = s.cap_usd != null && s.spent_usd >= s.cap_usd;
      }
      if (url === '/api/ai-budget/members') return new Response(JSON.stringify({ members: [
        { username: 'kid', spent_usd: 4, admin_cap_usd: 5, paused: false }, { username: 'mom', spent_usd: 1.234, admin_cap_usd: null, paused: false }] }));
      if (url.startsWith('/api/ai-budget/members/')) return new Response('{}');
      return new Response(JSON.stringify(window.__state));
    };
  });
  await page.evaluate(async () => {
    const { mountAiChoice } = await import('/static/js/settings/aiChoice.js');
    window.__changes = [];
    await mountAiChoice(document.getElementById('rows'), { api: window.__api, openSettings: tab => window.__opened.push(tab),
      onChanged: (d, p) => window.__changes.push([p?.source ?? null, d.source]) });
  });
  const checked = () => page.evaluate(() => [...document.querySelectorAll('[data-ai-source]')].filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.dataset.aiSource));
  const text = () => page.textContent('#rows');
  const settle = () => page.waitForTimeout(50);

  assert.deepEqual(await checked(), ['shared']); // nothing chosen yet = shared
  assert.match(await text(), /Available: Home GPU\./);
  assert.match(await text(), /This month: \$1\.23 \(no cap\)/);

  await page.click('[data-ai-source="own"]'); await settle();
  assert.deepEqual(await checked(), ['own']);
  assert.match(await text(), /You haven’t added an AI account yet\./);
  await page.click('[data-ai-action="add-account"]'); await settle();
  assert.deepEqual(await page.evaluate(() => window.__opened), ['added-models']);

  await page.fill('.ai-choice-row .ai-choice-cap', '1'); await page.click('[data-ai-action="save-cap"]'); await settle();
  assert.match(await text(), /This month: \$1\.23 of \$1\.00/);
  assert.match(await text(), /AI is paused until the 1st of next month/);
  await page.click('[data-ai-action="clear-cap"]'); await settle();
  assert.match(await text(), /\(no cap\)/);
  await page.fill('.ai-choice-row .ai-choice-cap', '-1'); await page.click('[data-ai-action="save-cap"]'); await settle();
  assert.equal(await page.textContent('.ai-choice-msg'), 'The cap must be between $0 and $100,000.');

  await page.click('[data-ai-source="off"]'); await settle();
  assert.deepEqual(await checked(), ['off']);
  assert.equal(await page.$('.ai-choice-spend'), null); // no costs to show without AI
  assert.deepEqual(await page.evaluate(() => window.__changes), [[null, 'own'], ['own', 'own'], ['own', 'own'], ['own', 'off']]);

  // Admin: everyone's spending and a per-member cap.
  await page.click('[data-ai-source="shared"]'); await settle();
  await page.click('[data-ai-action="members"]');
  await page.waitForSelector('.ai-choice-table');
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.ai-choice-table tr[data-member]')].map(r => r.textContent)), ['kid$4.00Save', 'mom$1.23Save']);
  await page.fill('tr[data-member="kid"] input', '10');
  await page.click('tr[data-member="kid"] [data-ai-action="member-cap"]'); await settle();
  assert.equal(await page.textContent('.ai-choice-msg'), 'Saved the cap for kid.');
  const puts = await page.evaluate(() => window.__calls.filter(c => c[0] === 'PUT').map(c => `${c[1]} ${c[2]}`));
  assert.equal(puts.at(-1), '/api/ai-budget/members/kid {"admin_cap_usd":10}');
  console.log('PASS: your AI card choices, own-account link, cap, paused, errors, no-AI, admin caps');
} finally {
  await browser.close();
}
