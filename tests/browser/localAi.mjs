// Settings → Account → Local AI, in a real browser against the real module.
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const origin = process.env.ODYSSEUS_TEST_STATIC_ORIGIN;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${origin}/static/manifest.json`);
  await page.evaluate(() => {
    document.body.innerHTML = '<div class="admin-card" id="card" hidden><div id="rows"></div></div>';
    window.__calls = [];
    window.__opened = [];
    window.__mode = 'docker';
    const docker = { total_ram_gb: 7.7, cpu_name: 'VM', has_gpu: false, probe_scope: 'container', backend: 'cpu_arm' };
    const mac = { total_ram_gb: 36, cpu_name: 'Apple M3 Pro', has_gpu: true, gpu_vram_gb: 27, unified_memory: true, backend: 'metal', probe_scope: 'host_snapshot', host_measured_at: '2026-10-24T20:00:00Z' };
    const models = [{ name: 'Qwen/Qwen3-30B-A3B', quant: 'Q4_K_M', required_gb: 18.2, speed_tps: 41.3 }, { name: 'google/gemma-3-27b-it', quant: 'Q4_K_M', required_gb: 17 }];
    window.__api = async url => {
      window.__calls.push(url);
      if (window.__mode === 'member') return new Response('{"detail":"Admin only"}', { status: 403 });
      const manual = url.includes('manual_mode');
      const system = window.__mode === 'docker' && !manual ? docker : mac;
      return new Response(JSON.stringify({ system, models: window.__mode === 'docker' && !manual ? [] : models }));
    };
  });
  await page.evaluate(async () => {
    const { mountLocalAi } = await import('/static/js/settings/localAi.js');
    await mountLocalAi(document.getElementById('rows'), {
      api: window.__api, openSettings: async tab => window.__opened.push(tab), openCookbook: () => window.__opened.push('cookbook'),
    });
  });
  const text = () => page.textContent('#rows');
  assert.equal(await page.isVisible('#card'), true);
  assert.match(await text(), /VM: 8 GB memory/);
  assert.match(await text(), /only sees 8 GB, Docker’s share/);
  assert.match(await text(), /python3 scripts\/host_hardware\.py/);
  assert.match(await text(), /No model fits comfortably/);
  const first = new URL((await page.evaluate(() => window.__calls))[0], origin);
  assert.equal(first.pathname, '/api/hwfit/models');
  assert.equal(first.searchParams.get('recommended'), 'true');

  // Measured with scripts/host_hardware.py: the whole Mac.
  await page.evaluate(() => { window.__mode = 'mac'; });
  await page.click('[data-local-ai="check"]');
  await page.waitForFunction(() => document.querySelector('#rows').textContent.includes('Apple M3 Pro: 36 GB memory'));
  assert.match(await text(), /Whole computer, measured on 2026-10-24\./);
  assert.match(await text(), /About 27 GB usable by the graphics chip\./);
  assert.match(await text(), /up to about 32 billion parameters/);
  assert.equal(await page.locator('.local-ai-models li').count(), 2);
  assert.match(await page.textContent('.local-ai-models li'), /Qwen\/Qwen3-30B-A3B · Q4_K_M · needs 18.2 GB · about 41 words\/s/);
  assert.equal(new URL((await page.evaluate(() => window.__calls)).at(-1), origin).searchParams.get('fresh'), 'true');

  // Another computer: a PC with a 24 GB NVIDIA card and 64 GB memory.
  await page.evaluate(() => { window.__mode = 'docker'; });
  await page.click('.local-ai-other summary');
  await page.selectOption('.local-ai-kind', 'nvidia');
  assert.equal(await page.isVisible('.local-ai-graphics'), true);
  await page.fill('.local-ai-memory', '64');
  await page.fill('.local-ai-graphics', '24');
  await page.click('[data-local-ai="manual"]');
  await page.waitForFunction(() => document.querySelector('#rows').textContent.includes('Using the computer you described.'));
  assert.match(await text(), /That computer: 36 GB memory/);
  const manual = new URL((await page.evaluate(() => window.__calls)).at(-1), origin).searchParams;
  assert.deepEqual(['manual_mode', 'manual_backend', 'manual_vram_gb', 'manual_ram_gb'].map(k => manual.get(k)), ['gpu', 'cuda', '24', '64']);
  assert.equal(await page.inputValue('.local-ai-memory'), '64');

  await page.click('[data-local-ai="cookbook"]');
  await page.click('[data-local-ai="connect"]');
  assert.deepEqual(await page.evaluate(() => window.__opened), ['cookbook', 'added-models']);

  const helpers = await page.evaluate(async () => {
    const m = await import('/static/js/settings/localAi.js');
    return {
      mac8: m.manualQuery({ kind: 'mac', memory: 8 }), mac36: m.appleUsableGb(36), mac128: m.appleUsableGb(128),
      cpu: m.manualQuery({ kind: 'cpu', memory: 32 }), small: m.sizeAdvice(5), big: m.sizeAdvice(100),
      cpuUsable: m.usableMemory({ total_ram_gb: 32, has_gpu: false }),
    };
  });
  assert.equal(helpers.mac8.manual_vram_gb, '5.4');
  assert.equal(helpers.mac36, 27);
  assert.equal(helpers.mac128, 102.4);
  assert.deepEqual(helpers.cpu, { manual_mode: 'ram', manual_ram_gb: '32' });
  assert.match(helpers.small, /only just fit/);
  assert.match(helpers.big, /100 billion/);
  assert.deepEqual(helpers.cpuUsable, { gb: 19.2, where: 'processor' });

  // Model list not downloaded yet: plain message, and Update model list asks the server to fetch it.
  await page.evaluate(async () => {
    window.__firstApi = window.__api;
    window.__api = async url => {
      window.__calls.push(url);
      const refreshed = url.includes('refresh_catalog=true');
      return new Response(JSON.stringify(refreshed
        ? { system: { total_ram_gb: 16, cpu_name: 'Apple M2', has_gpu: true, gpu_vram_gb: 10.7, unified_memory: true, probe_scope: 'native' }, models: [{ name: 'google/gemma-3-12b-it', quant: 'Q4_K_M', required_gb: 8 }] }
        : { system: { total_ram_gb: 16, cpu_name: 'Apple M2', has_gpu: true, gpu_vram_gb: 10.7, unified_memory: true, probe_scope: 'native' }, models: [], catalog_empty: true, error: 'Model catalog is empty.' }));
    };
    document.body.innerHTML = '<div class="admin-card" id="card3" hidden><div id="rows3"></div></div>';
    const { mountLocalAi } = await import('/static/js/settings/localAi.js');
    await mountLocalAi(document.getElementById('rows3'), { api: window.__api });
  });
  assert.match(await page.textContent('#rows3'), /hasn’t been downloaded yet/);
  assert.doesNotMatch(await page.textContent('#rows3'), /catalog|No model fits/);
  await page.click('#rows3 [data-local-ai="refresh"]');
  await page.waitForFunction(() => document.querySelector('#rows3 .local-ai-models li'));
  assert.match(await page.textContent('#rows3'), /google\/gemma-3-12b-it/);

  // Members can't check hardware: the card stays hidden.
  await page.evaluate(async () => {
    window.__mode = 'member';
    document.body.innerHTML = '<div class="admin-card" id="card2" hidden><div id="rows2"></div></div>';
    const { mountLocalAi } = await import('/static/js/settings/localAi.js');
    await mountLocalAi(document.getElementById('rows2'), { api: window.__firstApi });
  });
  assert.equal(await page.isVisible('#card2'), false);
  console.log('PASS: local ai card, docker share, whole computer, other computer, links, member hidden');
} finally {
  await browser.close();
}
