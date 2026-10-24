// Settings → Appearance → App look, in a real browser against the real modules.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  // Any same-origin URL gives the modules an origin to load from.
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    localStorage.clear();
    document.body.innerHTML = '<div id="rows"></div><div id="calc-window" data-app-look-id="calculator" data-look="apple"></div>';
  });
  await page.evaluate(async () => {
    const { mountAppLookPicker } = await import('/static/js/settings/appLooks.js');
    mountAppLookPicker(document.getElementById('rows'));
  });
  const state = () => page.evaluate(() => ({
    rows: [...document.querySelectorAll('#rows .app-look-row')].map(row => ({
      name: row.querySelector('.vis-label').firstChild.textContent.trim(),
      scope: row.querySelector('select').dataset.appLookScope,
      value: row.querySelector('select').value,
      options: [...row.querySelectorAll('option')].map(o => o.textContent),
    })),
    saved: JSON.parse(localStorage.getItem('exodus-app-looks-v1') || 'null'),
    calcWindow: document.getElementById('calc-window').dataset.look,
  }));
  const choose = (scope, value) => page.selectOption(`select[data-app-look-scope="${scope}"]`, value);

  // One row for every app plus "All apps"; nothing saved yet means the default.
  let s = await state();
  assert.deepEqual(s.rows.map(r => r.scope), ['all', 'clock', 'calculator']);
  assert.deepEqual(s.rows.map(r => r.name), ['All apps', 'Clock', 'Calculator']);
  assert.deepEqual(s.rows[0].options, ['Apple-like', 'Exodus']);
  assert.equal(s.rows[0].value, 'apple');
  assert.deepEqual(s.rows[1].options, ['Default (Apple-like)', 'Apple-like', 'Exodus']);
  assert.equal(s.rows[1].value, '');
  assert.equal(s.saved, null);

  // All apps → Exodus: saved, open windows follow, and app rows say so.
  await choose('all', 'exodus');
  s = await state();
  assert.deepEqual(s.saved, { workspace: 'exodus', apps: {} });
  assert.equal(s.calcWindow, 'exodus');
  assert.equal(s.rows[2].options[0], 'Default (Exodus)');

  // One app back to Apple-like overrides the all-apps choice for that app only.
  await choose('calculator', 'apple');
  s = await state();
  assert.deepEqual(s.saved, { workspace: 'exodus', apps: { calculator: 'apple' } });
  assert.equal(s.calcWindow, 'apple');
  assert.equal(s.rows[1].value, '');

  // "Default" clears the override again.
  await choose('calculator', '');
  s = await state();
  assert.deepEqual(s.saved, { workspace: 'exodus', apps: {} });
  assert.equal(s.calcWindow, 'exodus');

  // A change made elsewhere shows up in the picker; mounting twice adds no
  // duplicate listeners (one change still saves exactly once).
  await page.evaluate(async () => {
    const { setLook } = await import('/static/js/apps/looks.js');
    setLook({ app: 'clock', look: 'apple' });
    const { mountAppLookPicker } = await import('/static/js/settings/appLooks.js');
    mountAppLookPicker(document.getElementById('rows'));
  });
  s = await state();
  assert.equal(s.rows[1].value, 'apple');
  assert.equal(s.rows.length, 3);
  await page.evaluate(() => {
    window.__saves = 0;
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (k, v) { if (k === 'exodus-app-looks-v1') window.__saves += 1; return original.call(this, k, v); };
  });
  await choose('clock', 'exodus');
  assert.equal(await page.evaluate(() => window.__saves), 1);
  console.log('PASS: app look picker rows, all-apps choice, per-app override, clearing, external sync, no duplicate listeners');
} finally {
  await browser.close();
}
