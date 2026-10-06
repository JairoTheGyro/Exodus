// DOM contract regression: form controls named "id" shadow HTMLFormElement.id.
// Use the production renderer with a minimal DOM rather than requiring a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/js/home.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function renderWidget('),source.indexOf('let profile ='));

test('targeted widget refresh retains the goal form despite a control named id',()=>{
 const active={value:'Typed goal',selectionStart:2,selectionEnd:7,focus(o){this.focused=o;},setSelectionRange(a,b){this.selection=[a,b];}};
 const form={id:{nodeName:'INPUT',name:'id'},getAttribute:name=>name==='id'?'home-goal-form':null};
 const details={open:true},replacementDetails={open:false};let retained,lookedUp;
 const replacement={replaceWith:node=>{retained=node;}};
 const content={getElementById:id=>{lookedUp=id;return id==='home-goal-form'?replacement:null;}};
 let rendered=false;
 const w={querySelectorAll:selector=>selector==='details'?(rendered?[replacementDetails]:[details]):[form],replaceChildren:node=>{assert.equal(node,content);rendered=true;},contains:node=>node===active};
 const context=vm.createContext({w,document:{activeElement:active,createElement:()=>({content})}});
 vm.runInContext(code+'\nrenderWidget(w,"<form id=home-goal-form><input name=id></form>");',context);
 assert.equal(lookedUp,'home-goal-form');assert.equal(retained,form);assert.equal(active.value,'Typed goal');assert.equal(replacementDetails.open,true);assert.deepEqual(active.selection,[2,7]);assert.equal(active.focused.preventScroll,true);
});
