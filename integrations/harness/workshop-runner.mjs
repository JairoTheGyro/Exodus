// One disposable headless Harness task. Never loads the user's Web profile.
import {mkdtemp, mkdir, writeFile, readFile, rm} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {modelPatch} from './supervisor.mjs';

export async function runWorkshop({model, instructions, prompt}, token, signal, {gateway = 'http://odysseus:7000/api/code/bridge/v1', timeout = 300000} = {}) {
  const root = await mkdtemp(join(tmpdir(), 'exodus-workshop-'));
  let child;
  try {
    signal?.throwIfAborted();
    const home = join(root, 'home'), workspace = join(root, 'workspace');
    await mkdir(workspace);
    const config = modelPatch([{id: model, name: 'Selected Exodus model'}]).filter(x => x.id !== 'webserver');
    config[0].config.providers.exodus.baseURL = gateway;
    config[0].config.providers.exodus.defaultMaxTokens = 4096;
    config.push({id: 'agent-default-model', config: {provider: 'exodus', model}},
      {id: 'tools', config: {mode: 'native'}},
      ...['tool-bash', 'tool-pwsh', 'tool-fs', 'tool-fs-search', 'tool-jobs', 'tool-web',
        'tool-plugin-manager', 'tool-skill', 'tool-subagent', 'tool-subagent-fork', 'tool-subagent-control',
        'tool-subagent-list-agents', 'tool-workflow', 'tool-todo', 'tool-goal', 'tool-ralph',
        'agent-instructions', 'skill-filesystem', 'session-title-llm', 'session-telemetry-otel']
        .map(id => ({id, disabled: true})),
      {insert: [{id: 'exodus-workshop-tools', name: new URL('./workshop-tools.mjs', import.meta.url).pathname}]},
      {id: 'headless-runner', inject: ['headlessStartup', 'workshopReady']});
    await writeFile(join(root, 'patch.yml'), JSON.stringify(config));
    await writeFile(join(root, 'instructions.txt'), instructions);
    const resultPath = join(root, 'result.html');
    child = spawn('dsh', ['--profile', 'headless', '--patch', join(root, 'patch.yml'), '-'], {
      cwd: workspace, detached: true, stdio: ['pipe', 'pipe', 'pipe'],
      // Do not inherit the user's Web profile, provider keys, or plugin settings.
      env: {PATH: process.env.PATH, HOME: home, DSH_HOME: home, DSH_TELEMETRY_DISABLED: '1',
        EXODUS_CODE_TOKEN: token, EXODUS_WORKSHOP_RESULT: resultPath,
        EXODUS_WORKSHOP_INSTRUCTIONS: join(root, 'instructions.txt')},
    });
    let stopped = false, bytes = 0;
    const stop = () => { stopped = true; try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
    const timer = setTimeout(stop, timeout);
    signal?.addEventListener('abort', stop, {once: true});
    if (signal?.aborted) stop();
    // Drain without logging model content, reasoning, or credentials.
    for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
      bytes += chunk.length; if (bytes > 4000000) stop();
    });
    child.stdin.on('error', () => {});
    child.stdin.end(prompt);
    let code;
    try {
      code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', stop); }
    if (stopped) throw new Error('Workshop build stopped or exceeded its time/output limit. Nothing was saved.');
    if (code !== 0) throw new Error('Harness could not finish this build. Check the selected model connection.');
    let source;
    try { source = await readFile(resultPath, 'utf8'); } catch { throw new Error('Harness did not submit a complete app. Try a smaller brief or another tool-capable model.'); }
    if (Buffer.byteLength(source) > 200000) throw new Error('The generated app exceeds the Workshop size limit.');
    return {source, engine: 'harness', checks: ['HTML document structure', 'Inline JavaScript syntax']};
  } finally { await rm(root, {recursive: true, force: true}); }
}
