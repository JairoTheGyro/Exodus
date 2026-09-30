import assert from 'node:assert/strict';
import {mkdtemp, writeFile, readFile, rm, access} from 'node:fs/promises';
import {checkSource, apply} from '/opt/exodus/workshop-tools.mjs';
const root = await mkdtemp('/tmp/ws-tools-test-');
try {
  const html = code => `<html><body><script type="module">${code}</script></body></html>`;
  assert.deepEqual(await checkSource(html('await Promise.resolve();')), []);
  assert.ok((await checkSource(html('const = ;'))).some(x => x.includes('SyntaxError')));
  assert.ok((await checkSource('<html><script src="https://example.com"></script></html>')).length);
  assert.ok((await checkSource('<html>' + 'x'.repeat(200000) + '</html>')).length);
  assert.deepEqual(await checkSource(html(`import {writeFileSync} from 'node:fs'; writeFileSync(${JSON.stringify(root+'/must-not-exist')}, 'bad');`)), []);
  await assert.rejects(access(root+'/must-not-exist'));
  process.env.EXODUS_WORKSHOP_RESULT = root+'/result.html';
  process.env.EXODUS_WORKSHOP_INSTRUCTIONS = root+'/instructions';
  await writeFile(root+'/instructions', 'test instructions');
  let guard, tool, ready;
  apply({systemPrompt:{section(){}}, on(){}, provide(n,v){ready = v;}, tools:{guard(fn){guard=fn;}, register(t){tool=t;}}});
  assert.equal(ready, true);
  assert.ok(guard({name:'bash'}));
  assert.equal(guard({name:'submit_workshop_app'}), undefined);
  const good=html('let count = 0;');
  assert.equal(JSON.parse(await tool.execute({source:good})).accepted, true);
  assert.equal(await readFile(root+'/result.html','utf8'),good);
  assert.equal(JSON.parse(await tool.execute({source:html('const = ;')})).accepted, false);
  await assert.rejects(access(root+'/result.html'));
  for(let i=0;i<11;i++) assert.equal(guard({name:'submit_workshop_app'}),undefined);
  assert.ok(guard({name:'submit_workshop_app'}));
  console.log('PASS: syntax-only checks never execute code, limits, tool guard, revision cap, invalid revision clears previous candidate.');
} finally {await rm(root,{recursive:true,force:true});}
