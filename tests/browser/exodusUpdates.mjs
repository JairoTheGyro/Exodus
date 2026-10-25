// Settings → License Tracker → Updates, in a real browser against the real module.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const OLD = 'a'.repeat(40);
const NEW = 'b'.repeat(40);
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(({ OLD, NEW }) => {
    document.body.innerHTML = '<div class="admin-card" id="card" hidden><div id="rows"></div></div>';
    window.__calls = [];
    window.__confirms = [];
    window.__reloads = 0;
    const base = {
      installed: { revision: OLD }, update_available: true, ahead_by: 2, changes: ['fix: two', 'feat: one'],
      latest: { revision: NEW, date: '2026-10-25T01:00:00Z', tested: 'passed' }, checked_at: '2026-10-25T02:00:00+00:00',
      helper: { online: true }, status: {}, compare_url: `https://github.com/JairoTheGyro/Exodus/compare/${OLD}...${NEW}`,
    };
    window.__view = base;
    window.__polls = 0;
    window.__api = async (url, init = {}) => {
      window.__calls.push([init.method || 'GET', url, init.body || null]);
      if (window.__member) return new Response('{"detail":"Admin only"}', { status: 403 });
      if (url === '/api/updates/approve') {
        window.__view = { ...window.__view, status: { state: 'running', message: 'Updating: backing up…' } };
      } else if (url === '/api/updates' && window.__view.status?.state === 'running' && ++window.__polls >= 2) {
        window.__view = { ...window.__view, installed: { revision: NEW }, update_available: false, status: { state: 'done', message: 'Exodus is up to date. Reload the page.' } };
      }
      return new Response(JSON.stringify(window.__view));
    };
  }, { OLD, NEW });
  await page.evaluate(async () => {
    const { mountUpdates } = await import('/static/js/settings/exodusUpdates.js');
    await mountUpdates(document.getElementById('rows'), {
      api: window.__api, pollMs: 50, reload: () => { window.__reloads += 1; },
      confirmFn: async message => { window.__confirms.push(message); return true; },
    });
  });
  const text = () => page.textContent('#rows');
  assert.equal(await page.isVisible('#card'), true);
  assert.match(await text(), /This server runs version aaaaaaa\./);
  assert.match(await text(), /A newer version is available: bbbbbbb from 2026-10-25\./);
  assert.match(await text(), /All tests passed/);
  assert.match(await text(), /What’s new \(2 changes\)/);
  assert.equal(await page.getAttribute('.exodus-updates-link', 'href'), `https://github.com/JairoTheGyro/Exodus/compare/${OLD}...${NEW}`);
  assert.equal(await page.isEnabled('[data-updates="install"]'), true);

  await page.click('[data-updates="install"]');
  await page.waitForFunction(() => document.querySelector('#rows').textContent.includes('Exodus is up to date. Reload the page.'));
  const approve = (await page.evaluate(() => window.__calls)).find(c => c[1] === '/api/updates/approve');
  assert.deepEqual(JSON.parse(approve[2]), { target: NEW });
  assert.match((await page.evaluate(() => window.__confirms))[0], /backed up first/);
  await page.click('[data-updates="reload"]');
  assert.equal(await page.evaluate(() => window.__reloads), 1);

  // Not tested yet, and no helper: no install button that works, setup steps shown.
  const other = await page.evaluate(async ({ OLD, NEW }) => {
    const { renderUpdates } = await import('/static/js/settings/exodusUpdates.js');
    const a = document.createElement('div');
    renderUpdates(a, { installed: { revision: OLD }, update_available: true, latest: { revision: NEW, tested: 'failed', date: '' }, helper: { online: false }, status: {} });
    const b = document.createElement('div');
    renderUpdates(b, { installed: { revision: OLD }, update_available: true, latest: { revision: NEW, tested: 'passed', date: '' }, helper: { online: false }, status: {} });
    const c = document.createElement('div');
    renderUpdates(c, { installed: null, latest: null, helper: { online: true }, status: { state: 'failed', message: 'Update stopped: x', log: ['line 1'] } });
    return {
      failed: a.textContent, failedButton: !!a.querySelector('[data-updates="install"]'),
      offlineDisabled: b.querySelector('[data-updates="install"]').disabled, offline: b.textContent,
      unknown: c.textContent, log: !!c.querySelector('.exodus-updates-log'),
    };
  }, { OLD, NEW });
  assert.match(other.failed, /Some tests failed/);
  assert.equal(other.failedButton, false);
  assert.equal(other.offlineDisabled, true);
  assert.match(other.offline, /python3 scripts\/update_agent\.py install/);
  assert.match(other.unknown, /version isn’t known yet/);
  assert.match(other.unknown, /Update stopped: x/);
  assert.equal(other.log, true);

  await page.evaluate(async () => {
    window.__member = true;
    document.body.innerHTML = '<div class="admin-card" id="card2" hidden><div id="rows2"></div></div>';
    const { mountUpdates } = await import('/static/js/settings/exodusUpdates.js');
    await mountUpdates(document.getElementById('rows2'), { api: window.__api });
  });
  assert.equal(await page.isVisible('#card2'), false);
  console.log('PASS: updates card, install, progress, done, untested, no helper, member hidden');
} finally {
  await browser.close();
}
