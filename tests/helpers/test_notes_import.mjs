import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync('static/js/notes.js', 'utf8');
const start = source.indexOf("  const importBtn = pane.querySelector('#notes-import-select');");
const end = source.indexOf('  // Search\n', start);
assert.ok(start > 0 && end > start);
const code = source.slice(start, end);
assert.match(source, /id="notes-import-file" type="file" accept="\.json,application\/json" hidden/);
assert.match(source, /id="notes-import-status" role="status" aria-live="polite"/);

function fixture({editing=false, response={ok:true, json:async()=>({imported:2,archived:1,warnings:[{message:'Images omitted.',count:1}]})}}={}) {
  const element = () => ({events:{},disabled:false,textContent:'',value:'selected',
    addEventListener(name, handler){this.events[name]=handler;},click(){this.clicked=true;}});
  const button=element(), input=element(), status=element();
  const calls=[], toasts=[];
  let fetched=0, rendered=0;
  const pane={querySelector(selector){return {'#notes-import-select':button,'#notes-import-file':input,
    '#notes-import-status':status,'.note-form':editing?{}:null}[selector];}};
  vm.runInNewContext(code,{pane,API_BASE:'http://local.test',_open:true,
    fetch:async(url,options)=>{calls.push({url,options});return response;},
    _fetchNotes:async()=>{fetched++;},_renderNotes:()=>{rendered++;},
    uiModule:{showToast:text=>toasts.push(text)},Error});
  return {button,input,status,calls,toasts,counts:()=>({fetched,rendered})};
}

const normal=fixture();
assert.equal(normal.calls.length,0,'No import or network request before file selection');
normal.button.events.click();assert.equal(normal.input.clicked,true);
const file={size:300,name:'exodus-notes.json'};normal.input.files=[file];
await normal.input.events.change();
assert.equal(normal.calls[0].url,'http://local.test/api/notes/import/json');
assert.equal(normal.calls[0].options.body,file,'Send the selected file directly, not an unbounded parsed copy');
assert.equal(normal.calls[0].options.credentials,'same-origin');
assert.equal(normal.calls[0].options.method,'POST');
assert.match(normal.status.textContent,/Imported 2 notes as new copies \(1 archived\)/);
assert.match(normal.status.textContent,/Images omitted/);
assert.deepEqual(normal.counts(),{fetched:1,rendered:1});
assert.equal(normal.input.value,'');assert.equal(normal.button.disabled,false);

const editing=fixture({editing:true});editing.input.files=[file];await editing.input.events.change();
assert.deepEqual(editing.counts(),{fetched:1,rendered:0},'Do not destroy an unsaved note editor');

const large=fixture();large.input.files=[{size:10*1024*1024+1}];await large.input.events.change();
assert.equal(large.calls.length,0);assert.match(large.status.textContent,/10 MiB/);
assert.equal(large.button.disabled,false);

const invalid=fixture({response:{ok:false,json:async()=>({detail:'Note 2: Invalid checklist.'})}});
invalid.input.files=[file];await invalid.input.events.change();
assert.match(invalid.status.textContent,/Note 2/);assert.deepEqual(invalid.counts(),{fetched:0,rendered:0});
assert.equal(invalid.toasts.length,0);
console.log('PASS: Notes import explicit file choice, direct bounded upload, authenticated endpoint, counts/warnings, local refresh, draft preservation, size/error handling.');
