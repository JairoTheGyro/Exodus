import test from 'node:test';
import assert from 'node:assert/strict';
import {createScratchpad} from '../../static/js/homeScratchpad.js';
const revision = n => n.toString(16).padStart(64,'0');
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const turn = () => new Promise(resolve=>setImmediate(resolve));
function fixture({request,storage=new Map(),owner='alice',recoveryId='tab-1'}={}) {
 let server={text:'',revision:revision(0)}, serial=0;const calls=[];let job;const receipts=new Map();
 const transport=async(path,options={})=>{
  calls.push({path,...options});if(request)return request(path,options);
  if(!options.method)return {...server};
  if(options.method==='PUT'){
   if(options.body.revision!==server.revision)throw Object.assign(Error('Conflict'),{status:409,detail:{current:{...server}}});
   server={text:options.body.text,revision:revision(++serial)};return {...server};
  }
  const id=options.body.request_id;
  if(receipts.has(id))return {...receipts.get(id),replayed:true};
  assert.equal(options.body.revision,server.revision);
  server={text:'',revision:revision(++serial)};const result={id:'note-'+id,...server,cleared:true,replayed:false};receipts.set(id,result);return result;
 };
 const controller=createScratchpad({request:transport,owner,recoveryId,storage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},schedule:fn=>{job=fn;return fn;},cancel:()=>{job=null;},uuid:()=>`request-${calls.length}`});
 return {controller,calls,storage,get server(){return server;},set server(value){server=value;},fire:()=>job?.()};
}

test('debounced editing saves only latest text and does not call the model',async()=>{
 const f=fixture();await f.controller.refresh();f.controller.input('One');f.controller.input('One thought');assert.equal(f.calls.length,1);f.fire();await turn();assert.equal(f.server.text,'One thought');assert.equal(f.calls.filter(c=>c.method==='PUT').length,1);assert.equal(f.controller.getState().dirty,false);assert.equal(f.storage.size,0);
});
test('serialized writes preserve new text typed during an in-flight save',async()=>{
 const first=deferred();let serial=0;const f=fixture({request:async(path,o)=>{if(!o.method)return {text:'',revision:revision(0)};if(++serial===1){await first.promise;}return {text:o.body.text,revision:revision(serial)};}});
 await f.controller.refresh();f.controller.input('first');const saving=f.controller.flush();await turn();f.controller.input('latest');first.resolve();await saving;
 assert.deepEqual(f.calls.filter(c=>c.method==='PUT').map(c=>c.body.text),['first','latest']);assert.equal(f.controller.getState().text,'latest');assert.equal(f.controller.getState().dirty,false);
});
test('offline edits survive reload and another window cannot overwrite their recovery record',async()=>{
 const storage=new Map();const f=fixture({storage,request:async()=>{throw Error('Offline');}});f.controller.input('Recover me');await assert.rejects(f.controller.flush());
 const other=fixture({storage,recoveryId:'other-tab'});await other.controller.refresh();other.controller.input('Different draft');await other.controller.flush();
 const restored=fixture({storage});assert.equal(restored.controller.getState().text,'Recover me');await restored.controller.refresh();await restored.controller.flush();assert.equal(restored.server.text,'Recover me');
 const otherOwner=fixture({storage,owner:'bob'});assert.equal(otherOwner.controller.getState().text,'');
});
test('cross-window conflict preserves draft until an explicit resolution',async()=>{
 const f=fixture();await f.controller.refresh();f.controller.input('my draft');f.server={text:'other window',revision:revision(2)};await assert.rejects(f.controller.flush(),/another window/);assert.equal(f.controller.getState().text,'my draft');assert.equal(f.controller.getState().conflict.text,'other window');await f.controller.resolve('local');assert.equal(f.server.text,'my draft');assert.equal(f.controller.getState().dirty,false);
});
test('choosing the saved version explicitly replaces only the conflicted draft',async()=>{
 const f=fixture();await f.controller.refresh();f.controller.input('local');f.server={text:'remote',revision:revision(2)};await f.controller.refresh();await f.controller.resolve('remote');assert.equal(f.controller.getState().text,'remote');assert.equal(f.calls.filter(c=>c.method==='PUT').length,0);
});
test('conversion flushes, reuses uncertain request id after reload, and preserves in-flight typing',async()=>{
 const storage=new Map(), response=deferred();let server={text:'',revision:revision(0)}, first=true;const requests=[];
 const request=async(path,o)=>{if(!o.method)return {...server};if(o.method==='PUT'){server={text:o.body.text,revision:revision(1)};return {...server};}requests.push(o.body);if(first){first=false;server={text:'',revision:revision(2)};await response.promise;throw Error('Response lost');}return {id:'one-note',...server,cleared:true,replayed:true};};
 const f=fixture({storage,request});await f.controller.refresh();f.controller.input('note contents');const converting=f.controller.convert();await turn();f.controller.input('next thought');response.resolve();await assert.rejects(converting,/Response lost/);assert.equal(f.controller.getState().text,'next thought');
 const restored=fixture({storage,request});await restored.controller.convert();assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);assert.equal(restored.controller.getState().text,'next thought');await restored.controller.flush();assert.equal(server.text,'next thought');
});
test('lost successful save response is acknowledged instead of creating a false conflict',async()=>{
 let server={text:'',revision:revision(0)},first=true;
 const f=fixture({request:async(path,o)=>{if(!o.method)return server;if(first){first=false;server={text:o.body.text,revision:revision(1)};throw Error('Lost response');}throw Object.assign(Error('Conflict'),{status:409,detail:{current:server}});}});
 await f.controller.refresh();f.controller.input('saved');await assert.rejects(f.controller.flush());await f.controller.flush();assert.equal(f.controller.getState().dirty,false);assert.equal(f.controller.getState().conflict,null);
});
test('deleted converted note releases pending operation without discarding local edits',async()=>{
 let server={text:'',revision:revision(0)},convertCalls=0;
 const f=fixture({request:async(path,o)=>{if(!o.method)return server;if(o.method==='PUT'){server={text:o.body.text,revision:revision(1)};return server;}convertCalls++;server={text:'',revision:revision(2)};throw Object.assign(Error('Converted note was deleted'),{status:410});}});
 await f.controller.refresh();f.controller.input('keep me');await assert.rejects(f.controller.convert(),/deleted/);assert.equal(f.controller.getState().pending,null);assert.equal(f.controller.getState().text,'keep me');await f.controller.resolve('local');assert.equal(server.text,'keep me');assert.equal(convertCalls,1);
});
test('browser storage failure is visible while server saving still works',async()=>{
 const c=createScratchpad({owner:'alice',storage:{getItem(){throw Error('Denied');},setItem(){throw Error('Denied');},removeItem(){throw Error('Denied');}},request:async(_,o)=>({text:o?.body?.text||'',revision:revision(1)}),schedule:()=>0,cancel:()=>{}});c.input('unsaved');assert.equal(c.getState().recoveryAvailable,false);await c.flush();assert.equal(c.getState().dirty,false);
});

test('typing the same content anew during conversion is still a new draft',async()=>{
 const response=deferred();let server={text:'',revision:revision(0)};
 const f=fixture({request:async(path,o)=>{if(!o.method)return server;if(o.method==='PUT'){server={text:o.body.text,revision:revision(1)};return server;}await response.promise;server={text:'',revision:revision(2)};return {id:'saved',...server,cleared:true,replayed:false};}});
 await f.controller.refresh();f.controller.input('repeatable thought');const converting=f.controller.convert();await turn();f.controller.input('');f.controller.input('repeatable thought');response.resolve();await converting;assert.equal(f.controller.getState().text,'repeatable thought');assert.equal(f.controller.getState().dirty,true);
});
