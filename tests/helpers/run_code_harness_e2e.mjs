// Run inside the Harness container while tests/code_e2e_fixture.py runs in
// Exodus's container. Uses only a disposable home, project, and fake provider.
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {modelPatch} from '/opt/exodus/supervisor.mjs';
const token = 'exodus_code_disposable_fixture_only';
const root = await mkdtemp('/tmp/exodus-code-e2e-');
try {
  const r = await fetch('http://odysseus:7094/api/code/bridge/v1/models', {headers:{Authorization:`Bearer ${token}`}});
  assert.equal(r.status, 200);
  const models = (await r.json()).data;
  const config = modelPatch(models).filter(x => x.id !== 'webserver');
  config[0].config.providers.exodus.baseURL = 'http://odysseus:7094/api/code/bridge/v1';
  config.push({id:'agent-default-model',config:{provider:'exodus',model:models[0].id}});
  await mkdir(root + '/workspace');
  await writeFile(root + '/patch.yml', JSON.stringify(config));
  const child = spawn('dsh', ['--profile','headless','--patch',root+'/patch.yml',
    'This is an explicit test fixture. Read the working directory and report success.'], {
      cwd: root+'/workspace', stdio:['ignore','pipe','pipe'],
      env:{...process.env, DSH_HOME:root+'/home', DSH_TELEMETRY_DISABLED:'1', EXODUS_CODE_TOKEN:token},
  });
  let output = '';
  child.stdout.on('data', b => output += b);
  child.stderr.on('data', b => output += b);
  const timer = setTimeout(()=>child.kill('SIGTERM'),60000);
  const code = await new Promise((resolve,reject)=>{child.once('exit',resolve); child.once('error',reject);});
  clearTimeout(timer);
  assert.equal(code,0,output);
  assert.match(output,/model and tool-result round trip succeeded/);
  const report = await (await fetch('http://odysseus:7094/test/report')).json();
  assert.equal(report.tool_result_received,true);
  assert.ok(report.tool_results.some(x=>x.includes(root+'/workspace')));
  console.log('PASS: real Harness → Exodus gateway → fixture provider → bash pwd → tool result → completion.');
} finally {
  await rm(root,{recursive:true,force:true});
}
