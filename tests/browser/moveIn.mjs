// Settings → Account → Move to Exodus, in a real browser against the real module.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(async () => {
    document.body.innerHTML = '<div id="rows"></div>';
    window.__calls = [];
    window.__uploads = [];
    const scan = {
      token: 'tok123', filename: 'takeout-001.zip',
      summary: { calendars: ['Takeout/Calendar/Family.ics'], contacts: 1, contacts_need_admin: true, keep_notes: 3,
        files: 1, files_bytes: 2048, mail: 1, photos: 4, office: 1, skipped: [{ name: 'x', reason: 'y' }] },
    };
    const report = { calendars: [{ file: 'Family.ics', calendar: 'Family', imported: 2 }], contacts: null,
      notes: { imported: 3 }, files: { imported: 0, skipped: [] }, messages: ['Contacts were found, but only the admin can import them.'] };
    const { mountMoveIn } = await import('/static/js/settings/moveIn.js');
    mountMoveIn(document.getElementById('rows'), {
      upload: async (file, onProgress) => { window.__uploads.push(file.name); onProgress(100); return scan; },
      api: async (url, init = {}) => {
        window.__calls.push([init.method || 'GET', url, init.body ? JSON.parse(init.body) : null]);
        return new Response(JSON.stringify(url.endsWith('/import') ? report : { ok: true }));
      },
    });
  });
  assert.equal(await page.locator('.move-in-guides details').count(), 3);
  await page.click('[data-move-in="scan"]');
  assert.equal(await page.textContent('.move-in-msg'), 'Choose your export file first.');

  await page.setInputFiles('.move-in-file', { name: 'takeout-001.zip', mimeType: 'application/zip', buffer: Buffer.from('PK') });
  await page.click('[data-move-in="scan"]');
  await page.waitForSelector('.move-in-found');
  const found = await page.textContent('.move-in-found');
  assert.match(found, /Calendars: 1/);
  assert.match(found, /only the admin can import contacts/);
  assert.match(found, /Mail archives aren’t imported/);
  assert.equal(await page.isDisabled('[data-choose="contacts"]'), true);
  assert.equal(await page.isChecked('[data-choose="notes"]'), true);
  await page.uncheck('[data-choose="files"]');

  await page.click('[data-move-in="import"]');
  await page.waitForSelector('.move-in-done');
  const done = await page.textContent('#rows');
  assert.match(done, /Calendar “Family”: 2 events added/);
  assert.match(done, /Notes: 3 added/);
  assert.match(done, /only the admin can import them/);
  const calls = await page.evaluate(() => window.__calls);
  assert.deepEqual(calls[0], ['POST', '/api/move-in/import',
    { token: 'tok123', calendars: true, contacts: false, notes: true, files: false }]);

  await page.click('[data-move-in="again"]');
  await page.waitForSelector('.move-in-file');
  await page.setInputFiles('.move-in-file', { name: 'outlook.ics', mimeType: 'text/calendar', buffer: Buffer.from('BEGIN') });
  await page.click('[data-move-in="scan"]');
  await page.waitForSelector('.move-in-found');
  await page.click('[data-move-in="cancel"]');
  await page.waitForSelector('.move-in-file');
  assert.deepEqual((await page.evaluate(() => window.__calls)).at(-1).slice(0, 2), ['DELETE', '/api/move-in/tok123']);
  assert.deepEqual(await page.evaluate(() => window.__uploads), ['takeout-001.zip', 'outlook.ics']);
  console.log('PASS: move in card, scan summary, chosen import, results, cancel');
} finally {
  await browser.close();
}
