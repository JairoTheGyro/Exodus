// Manage only the Exodus provider in the profile; preserve other user settings.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { createInterface } from 'node:readline';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { networkInterfaces } from 'node:os';
const upstream = createRequire('/usr/local/lib/node_modules/@deepseek-ai/dsh/package.json');
const {parseDocument, isSeq, isMap} = upstream('yaml');
const {withFileLock, writeFileAtomic} = await import(pathToFileURL(upstream.resolve('@deepseek-ai/dsh-atomic-write')));

// dsh 0.2+ refuses wildcard binds. Use the container's own address: Docker
// publishes the host loopback port to it and Exodus reaches `harness` there.
export function containerAddress(interfaces = networkInterfaces()) {
  const found = Object.values(interfaces).flat().find(x => x && x.family === 'IPv4' && !x.internal);
  return found ? found.address : '127.0.0.1';
}

export function modelPatch(models) {
  return [{id: 'webserver', config: {host: containerAddress(), port: 3080, compression: 'gzip', compressionLevel: 1, compressionThresholdBytes: 1024}}, {id: 'llm-pi-ai', config: {providers: models.length ? {exodus: {
      displayName: 'Exodus', apiKeyEnv: 'EXODUS_CODE_TOKEN', api: 'openai-completions',
      baseURL: 'http://odysseus:7000/api/code/bridge/v1',
      defaultContextWindow: 8192, defaultMaxTokens: 2048,
      compat: {supportsDeveloperRole: false, maxTokensField: 'max_tokens'},
      retryPolicy: {mode: 'normal', maxRetries: 0},
      models: models.map(m => ({id: m.id, name: m.name, input: ['text']})),
    }} : {}}}];
}

export function mergeModelCatalog(original, models) {
  const managed = modelPatch(models)[1].config.providers.exodus;
  const doc = parseDocument(original);
  if (doc.errors.length || !isSeq(doc.contents)) throw new Error('Invalid profile patch');
  let row = doc.contents.items.filter(x => isMap(x) && x.get('id') === 'llm-pi-ai').at(-1);
  if (!row && !managed) return original;
  if (!row) { row = doc.createNode({id: 'llm-pi-ai', config: {providers: {}}}); doc.contents.add(row); }
  const old = row.getIn(['config', 'providers', 'exodus']);
  if (JSON.stringify(old?.toJSON()) === JSON.stringify(managed)) return original;
  if (managed) row.setIn(['config', 'providers', 'exodus'], doc.createNode(managed));
  else row.deleteIn(['config', 'providers', 'exodus']);
  return doc.toString();
}

async function main() {
  const home = process.env.DSH_HOME || '/home/node/.dsh';
  const overlay = `${home}/exodus-models.patch.yml`;
  await mkdir(home, {recursive: true});
  let child, childToken, launchToken, syncedCount = 0, stopping = false;
  let workshopBusy = false;
  const workshopControllers = new Set();
  const control = createServer(async (req, res) => {
    let requestToken;
    try { requestToken = JSON.parse(await readFile('/run/exodus/connection.json', 'utf8')).token; } catch {}
    const received = Buffer.from(req.headers.authorization || '');
    const expected = Buffer.from('Bearer ' + (requestToken || ''));
    if (!requestToken || received.length !== expected.length || !timingSafeEqual(received, expected)) {
      res.writeHead(401).end(); return;
    }
    if (req.method === 'POST' && req.url === '/workshop/build') {
      const reply = (code, body) => { if (!res.destroyed) { res.writeHead(code, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}); res.end(JSON.stringify(body)); } };
      if (workshopBusy) { reply(429, {detail: 'Another Workshop build is running.'}); return; }
      workshopBusy = true;
      const controller = new AbortController();
      workshopControllers.add(controller);
      res.once('close', () => controller.abort());
      const inputTimer = setTimeout(() => controller.abort(), 10000);
      controller.signal.addEventListener('abort', () => { if (!req.complete) req.destroy(); }, {once: true});
      try {
        const chunks = []; let bytes = 0;
        for await (const part of req) {
          bytes += part.length;
          if (bytes > 300000) { reply(413, {detail: 'Workshop brief is too large.'}); return; }
          chunks.push(part);
        }
        clearTimeout(inputTimer);
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { reply(400, {detail: 'Invalid Workshop build request.'}); return; }
        if (!body || typeof body.model !== 'string' || typeof body.prompt !== 'string' || typeof body.instructions !== 'string' || !body.prompt.trim()) {
          reply(400, {detail: 'Invalid Workshop build request.'}); return;
        }
        const catalog = await fetch('http://odysseus:7000/api/code/bridge/v1/models', {
          headers: {Authorization: `Bearer ${requestToken}`}, signal: AbortSignal.timeout(5000),
        });
        if (!catalog.ok || !(await catalog.json()).data?.some(m => m.id === body.model)) {
          reply(400, {detail: 'The selected model is no longer available in Exodus.'}); return;
        }
        const {runWorkshop} = await import('./workshop-runner.mjs');
        reply(200, await runWorkshop(body, requestToken, controller.signal));
      } catch {
        reply(502, {detail: 'Harness could not complete the app within its limits. Check the model connection or try a smaller brief. Nothing was saved.'});
      } finally {
        clearTimeout(inputTimer); workshopBusy = false; workshopControllers.delete(controller);
      }
      return;
    }
    if (req.method !== 'GET' || req.url !== '/status') { res.writeHead(404).end(); return; }
    res.writeHead(200, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
    res.end(JSON.stringify({ready: !!launchToken, launch_token: launchToken, model_count: syncedCount}));
  });
  control.listen(3081, '0.0.0.0');
  // Use the same profile lock as Harness Settings and update only our provider.
  // Other providers, plugin rows, comments, and custom YAML tags are preserved.
  const profile = `${home}/profiles/web`;
  await new Promise((resolve, reject) => {
    const init = spawn('dsh', ['web', '--dump-default-config'], {stdio: 'ignore', env: {...process.env, DSH_HOME: home}});
    init.once('error', reject); init.once('exit', code => code === 0 ? resolve() : reject(new Error('Profile initialization failed')));
  });
  await writeFile(overlay, JSON.stringify([modelPatch([])[0]]) + '\n', {mode: 0o600});
  async function patch(models) {
    const filename = `${profile}/cordis.patch.yml`;
    await withFileLock(`${profile}/package.json`, async () => {
      const original = await readFile(filename, 'utf8');
      const next = mergeModelCatalog(original, models);
      if (next === original) { syncedCount = models.length; return; }
      await writeFileAtomic(filename, next, {mode: 0o600});
      syncedCount = models.length;
      console.log(`Exodus Code: synchronized ${models.length} model(s).`);
    });
  }
  async function start(token) {
    if (child && childToken === token) return;
    if (child) {
      const prior = child;
      child = undefined;
      await new Promise(resolve => { prior.once('exit', resolve); prior.kill('SIGTERM'); });
    }
    if (stopping) return;
    childToken = token;
    launchToken = undefined;
    // Bind inside the isolated container through the supported webserver config;
    // Docker publishes only on host loopback. Browser trust checks stay enabled.
    child = spawn('dsh', ['web', '--patch', overlay, '--no-open'], {
      stdio: ['ignore', 'pipe', 'inherit'], env: {...process.env, EXODUS_CODE_TOKEN: token || '', DSH_TELEMETRY_DISABLED: '1'},
    });
    const current = child;
    createInterface({input: current.stdout}).on('line', line => {
      if (line.startsWith('dsh web: ')) {
        try { launchToken = new URL(line.slice(9).split(' ')[0]).searchParams.get('token'); } catch {}
        console.log('Exodus Code: web workspace ready. Open it from Exodus Tools → Code.');
      } else console.log(line);
    });
    current.on('exit', code => { if (child === current && !stopping) process.exit(code || 1); });
  }
  for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => {
    stopping = true;
    for (const controller of workshopControllers) controller.abort();
    if (child) { child.once('exit', () => process.exit(0)); child.kill(sig); }
    else process.exit(0);
  });
  while (!stopping) {
    let token;
    try { token = JSON.parse(await readFile('/run/exodus/connection.json', 'utf8')).token; } catch {}
    let models = [];
    if (token) {
      try {
        const r = await fetch('http://odysseus:7000/api/code/bridge/v1/models', {
          headers: {Authorization: `Bearer ${token}`}, signal: AbortSignal.timeout(5000),
        });
        if (!r.ok) throw new Error('Model gateway unavailable');
        const value = await r.json();
        if (!Array.isArray(value.data)) throw new Error('Invalid model catalog');
        models = value.data;
      } catch {
        // Remove stale offerings while disconnected. The gateway also rejects
        // removed models at request time, including already-open sessions.
      }
    }
    await patch(models);
    await start(token);
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { console.error('Exodus Code could not start. Check its Docker configuration.'); process.exit(1); });
}
