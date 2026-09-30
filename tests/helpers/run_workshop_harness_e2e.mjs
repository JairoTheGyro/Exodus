// Run inside Harness while tests/code_e2e_fixture.py runs in Exodus.
import assert from 'node:assert/strict';
import {readdir} from 'node:fs/promises';
import {runWorkshop} from '/opt/exodus/workshop-runner.mjs';
const token = 'exodus_code_disposable_fixture_only';
const gateway = 'http://odysseus:7094/api/code/bridge/v1';
const models = await (await fetch(gateway + '/models', {headers: {Authorization: `Bearer ${token}`}})).json();
const before = (await readdir('/tmp')).filter(x => x.startsWith('exodus-workshop-')).sort();
const result = await runWorkshop({model: models.data[0].id,
  instructions: 'This is an explicit test fixture. Submit an HTML app with submit_workshop_app, repair issues and finish after acceptance.',
  prompt: 'Build the explicit test fixture counter.'}, token, new AbortController().signal, {gateway, timeout: 45000});
assert.match(result.source, /Explicit test fixture/);
assert.equal(result.engine, 'harness');
const report = await (await fetch('http://odysseus:7094/test/report')).json();
assert.deepEqual(report.tools, ['submit_workshop_app']);
assert.ok(report.tool_results.some(x => x.includes('false') && x.includes('SyntaxError')));
assert.ok(report.tool_results.some(x => x.includes('true')));
assert.deepEqual((await readdir('/tmp')).filter(x => x.startsWith('exodus-workshop-')).sort(), before);
await assert.rejects(runWorkshop({model: models.data[0].id, instructions:'Test', prompt:'Test'}, token,
  AbortSignal.timeout(20), {gateway}), /stopped|aborted/i);
assert.deepEqual((await readdir('/tmp')).filter(x => x.startsWith('exodus-workshop-')).sort(), before);
console.log('PASS: actual Harness, Exodus gateway, syntax rejection, repair, accepted app, tool allowlist, cancellation, cleanup. No paid provider.');
