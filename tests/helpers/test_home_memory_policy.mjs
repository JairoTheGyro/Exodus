import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../../static/js/home.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function syncMemoryPolicySetting(){'),source.indexOf('function greeting(){'));
const refresh=source.slice(source.indexOf('let profileSequence=0;'),source.indexOf('async function loadTasks('));
const nodes=new Map();
let toggle, message, response;
const makeElement=()=>({
 children:[], textContent:'',
 set innerHTML(value){this.html=value;if(value.includes('workspace-archived-memory')){
  message={textContent:''};toggle={checked:false,disabled:false,closest:()=>this};
  nodes.set('workspace-archived-memory',toggle);
 }},
 append(child){this.children.push(child);if(child.id)nodes.set(child.id,child);},
 querySelector(selector){return selector==='input'?toggle:message;},
});
const anchor={before:node=>{
 nodes.set(node.id,node);
 for(const id of ['workspace-mode-label','workspace-mode-change','workspace-home-settings'])nodes.set(id,makeElement());
}};
nodes.set('settings-modal',{querySelector:()=>anchor});
nodes.set('home-availability',{value:'available'});
const context=vm.createContext({
 profile:{mode:'full',ai_include_archived_notes:false},
 $:id=>nodes.get(id), document:{createElement:makeElement,activeElement:null},
 api:async(...args)=>response(...args), renderGrid:()=>{},status:()=>{},
 location:{reload:()=>assert.fail('A consent update must not reload the page')},
});
vm.runInContext(code+'\n'+refresh,context);
vm.runInContext('installSettings()',context);
assert.equal(toggle.checked,false);

// A profile event from a second tab updates the already installed control.
response=()=>({profile:{mode:'full',ai_include_archived_notes:true}});
await vm.runInContext('refreshProfile()',context);
assert.equal(toggle.checked,true);
assert.match(message.textContent,/saved account settings/);
response=()=>({profile:{mode:'full',ai_include_archived_notes:false}});
await vm.runInContext('refreshProfile()',context);
assert.equal(toggle.checked,false);

// An older GET cannot revert the choice after our PATCH completes.
let finishRead;
response=()=>new Promise(resolve=>{finishRead=resolve;});
const staleRead=vm.runInContext('refreshProfile()',context);
response=(_path,options)=>{
 assert.equal(options.method,'PATCH');
 assert.deepEqual(JSON.parse(options.body),{ai_include_archived_notes:true});
 return {profile:{mode:'full',ai_include_archived_notes:true}};
};
toggle.checked=true;
await toggle.onchange();
finishRead({profile:{mode:'full',ai_include_archived_notes:false}});
await staleRead;
assert.equal(toggle.checked,true);
assert.equal(vm.runInContext('profile.ai_include_archived_notes',context),true);

// In-flight editing keeps its visible choice; failed saves restore server state.
let failWrite;
response=()=>new Promise((_resolve,reject)=>{failWrite=reject;});
toggle.checked=false;
const pendingWrite=toggle.onchange();
assert.equal(toggle.disabled,true);
vm.runInContext('installSettings()',context);
assert.equal(toggle.checked,false);
failWrite(new Error('offline'));
await pendingWrite;
assert.equal(toggle.disabled,false);
assert.equal(toggle.checked,true);
assert.match(message.textContent,/Could not save/);
console.log('Home memory consent: cross-tab refresh, stale GET guard, pending choice, and failed save passed');
