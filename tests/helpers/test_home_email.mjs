// Run the production Inbox loader with controlled responses; no mailbox changes.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=readFileSync('static/js/home.js','utf8');
const library=readFileSync('static/js/emailLibrary.js','utf8');
const calls=[], opened=[], notices=[];
let responses, accountFailure=false;
const accounts=[{id:'a',name:'Account A'},{id:'b',name:'Account B'}];
const rows=[{dataset:{email:'0'}},{dataset:{email:'1'}}];
const inboxButton={};
const w={isConnected:true,innerHTML:'',setAttribute(){},insertAdjacentHTML(_,html){this.innerHTML+=html;},querySelector(){return inboxButton;},querySelectorAll(){return rows;}};
const ctx=vm.createContext({URLSearchParams,Date,Promise,w,console,
 api:async url=>{calls.push(url);if(url==='/api/email/accounts'){if(accountFailure)throw Error('Offline');return {accounts};}return responses(new URL(url,'http://test'));},
 status:text=>notices.push(text), action:(_,fn)=>fn(), launch:(kind,email)=>opened.push({kind,email}),
});
vm.runInContext(source.slice(source.indexOf('const esc ='),source.indexOf('const dayKey =')),ctx);
vm.runInContext(source.slice(source.indexOf('function empty('),source.indexOf('function widget(')),ctx);
vm.runInContext(source.slice(source.indexOf('let inboxLoadSequence'),source.indexOf('async function loadFiles')),ctx);
responses=async url=>({emails:[{uid:'7',subject:url.searchParams.get('account_id')==='a'?'Test <&>':'  ',folder:'INBOX'}]});
await vm.runInContext('loadInbox(w)',ctx);
assert(calls.slice(1).every(u=>new URL(u,'http://test').searchParams.get('cached_only')==='1'));
assert(w.innerHTML.includes('Test &lt;&amp;&gt;'));
assert(w.innerHTML.includes('(No Subject)'));
await rows[1].onclick();
assert.equal(opened[0].email.account_id,'b');
assert.equal(opened[0].email.uid,'7');
assert.equal(opened[0].email.folder,'INBOX');
await inboxButton.onclick();assert.equal(opened.at(-1).kind,'email');assert.equal(opened.at(-1).email,undefined);
calls.length=0;
await vm.runInContext('loadInbox(w,{refresh:true})',ctx);
assert(calls.slice(1).every(u=>{const p=new URL(u,'http://test').searchParams;return p.has('_')&&!p.has('cached_only');}));
const saved=w.innerHTML;accountFailure=true;
await vm.runInContext('loadInbox(w,{refresh:true})',ctx);
assert.equal(w.innerHTML,saved);assert.match(notices.at(-1),/failed/);accountFailure=false;
// An older response must not replace a newer refresh, even if it arrives last.
let release;
responses=url=>url.searchParams.has('_')?{emails:[{uid:'8',subject:'Fresh'}]}:new Promise(resolve=>{(release??=[]).push(resolve);});
const old=vm.runInContext('loadInbox(w)',ctx);
await new Promise(resolve=>setImmediate(resolve));
await vm.runInContext('loadInbox(w,{refresh:true})',ctx);
release.forEach(r=>r({emails:[{uid:'9',subject:'Stale'}]}));await old;
assert(w.innerHTML.includes('Fresh'));assert(!w.innerHTML.includes('Stale'));
responses=()=>({error:'IMAP offline'});await vm.runInContext('loadInbox(w,{refresh:true})',ctx);
assert.match(notices.at(-1),/could not be refreshed/);
// Execute the real direct-open branch. No list request is needed to find a UID.
const start=library.indexOf('    if (opts.uid) {',library.indexOf('const fastAccountAtOpen'));
const end=library.indexOf('    if (!fastAccountAtOpen',start);
let read,cardAdded;
const direct=vm.createContext({opts:{uid:'999',account_id:'b',folder:'Archive',message:{subject:'Test'}},state:{_libAccountId:'b'},grid:{innerHTML:'',appendChild:c=>cardAdded=c},_createCard:e=>({email:e}),_toggleCardPreview:async(c,e)=>{read=e;}});
await vm.runInContext('(async()=>{'+library.slice(start,end)+'})()',direct);
assert.equal(read.uid,'999');assert.equal(read.account_id,'b');assert.equal(read.folder,'Archive');assert.equal(cardAdded.email.subject,'Test');
read=null;direct.state._libAccountId='a';
await vm.runInContext('(async()=>{'+library.slice(start,end)+'})()',direct);
assert.equal(read,null,'Missing account must never fall back to another mailbox');
assert.match(direct.grid.innerHTML,/unavailable/);
console.log('PASS: cached loading, explicit polling, row identity, escaping, empty subjects, failure status, stale responses, direct reader and account mismatch.');
