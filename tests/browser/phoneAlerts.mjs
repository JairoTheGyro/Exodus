// Settings → Account → Phone alerts, in a real browser against the real module.
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
    window.__copied = [];
    window.__state = { enabled: true, personal: true, server: 'http://100.64.0.5:8091', topic: 'exodus-AAAAAAAAAAAAAAAAAAAAAAAA', subscribe_url: '' };
    window.__api = async (url, init = {}) => {
      window.__calls.push([init.method || 'GET', url]);
      if (url.endsWith('/test')) return new Response(JSON.stringify({ status: window.__testStatus || 'sent' }));
      if (url.endsWith('/reset')) { window.__state = { ...window.__state, topic: 'exodus-BBBBBBBBBBBBBBBBBBBBBBBB' }; }
      return new Response(JSON.stringify(window.__state));
    };
  });
  await page.evaluate(async () => {
    const { mountPhoneAlerts } = await import('/static/js/settings/phoneAlerts.js');
    await mountPhoneAlerts(document.getElementById('rows'), {
      api: window.__api, confirmFn: async () => true, copyFn: async text => { window.__copied.push(text); },
    });
  });
  const text = sel => page.textContent(sel);
  assert.equal(await text('.phone-alerts-server'), 'http://100.64.0.5:8091');
  assert.equal(await text('.phone-alerts-topic'), 'exodus-AAAAAAAAAAAAAAAAAAAAAAAA');
  assert.equal(await page.locator('.phone-alerts-steps li').count(), 4);

  await page.click('[data-alert-action="copy"]');
  await page.waitForFunction(() => document.querySelector('.phone-alerts-msg')?.textContent === 'Topic copied.');
  assert.deepEqual(await page.evaluate(() => window.__copied), ['exodus-AAAAAAAAAAAAAAAAAAAAAAAA']);

  await page.click('[data-alert-action="test"]');
  await page.waitForFunction(() => document.querySelector('.phone-alerts-msg')?.textContent.startsWith('Test sent'));
  await page.evaluate(() => { window.__testStatus = 'failed'; });
  await page.click('[data-alert-action="test"]');
  await page.waitForFunction(() => document.querySelector('.phone-alerts-msg')?.textContent.startsWith('The test could not be sent'));

  await page.click('[data-alert-action="reset"]');
  await page.waitForFunction(() => document.querySelector('.phone-alerts-topic')?.textContent === 'exodus-BBBBBBBBBBBBBBBBBBBBBBBB');
  assert.match(await text('.phone-alerts-msg'), /New address ready/);
  assert.deepEqual((await page.evaluate(() => window.__calls)).map(c => c.join(' ')), [
    'GET /api/alerts/phone', 'POST /api/alerts/phone/test', 'POST /api/alerts/phone/test', 'POST /api/alerts/phone/reset',
  ]);

  // Single-user installs: shared address, no "Get a new address"; turned off: just says so.
  const other = await page.evaluate(async () => {
    const { renderPhoneAlerts } = await import('/static/js/settings/phoneAlerts.js');
    const a = document.createElement('div');
    renderPhoneAlerts(a, { enabled: true, personal: false, server: 'http://localhost:8091', topic: 'exodus-alerts' });
    const b = document.createElement('div');
    renderPhoneAlerts(b, { enabled: false });
    return { shared: a.textContent, hasReset: !!a.querySelector('[data-alert-action="reset"]'), off: b.textContent };
  });
  assert.match(other.shared, /everyone shares this address/);
  assert.equal(other.hasReset, false);
  assert.equal(other.off, 'Phone alerts are turned off on this server.');
  console.log('PASS: phone alerts card, copy, test, new address, shared and off states');
} finally {
  await browser.close();
}
