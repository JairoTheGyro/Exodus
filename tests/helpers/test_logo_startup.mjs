import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const images=[{dataset:{},pending:true,src:'',removeAttribute(name){if(name==='data-logo-pending')this.pending=false;}}];
const favicon={dataset:{},href:'blank'};
const decodes=[];
let failSource=false;
let nextURL=0;
const status={textContent:''};
globalThis.Image=class {
  set src(value){this.url=value;if(this.onload)queueMicrotask(()=>failSource?this.onerror():this.onload());}
  decode(){return new Promise((resolve,reject)=>decodes.push({resolve,reject,url:this.url}));}
};
globalThis.document={
  querySelectorAll:selector=>selector==='img.exodus-logo'?images:[],
  querySelector:selector=>selector==='link[rel="icon"]'?favicon:null,
  getElementById:id=>id==='exodus-logo-status'?status:null,
  createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>({width:1,height:1,data:new Uint8ClampedArray([0,255,255,255])}),createImageData:()=>({data:new Uint8ClampedArray(4)}),putImageData(){}}),toDataURL:()=>`data:themed-${++nextURL}`}),
};
globalThis.window={addEventListener(){}};
globalThis.Storage={get:()=> 'auto',getJSON:()=>({colors:{panel:'#000000',red:'#ff0000'}})};
let source=await readFile(new URL('../../static/js/settings/brand.js',import.meta.url),'utf8');
source=source.replace("import Storage from '../storage.js';",'const Storage = globalThis.Storage;')
 .replace("new URL('../../icons/exodus.png', import.meta.url).href", "'original-logo'");
const module=await import('data:text/javascript,'+encodeURIComponent(source));
await tick();
assert.equal(images[0].pending,true,'Logo remains hidden while decoding');
assert.equal(images[0].src,'','No original-color image is assigned at startup');
assert.equal(favicon.href,'blank');
assert.equal(decodes.length,1);
decodes.shift().resolve();await tick();
assert.equal(images[0].pending,false);
assert(images[0].src.startsWith('data:themed-'));
assert.equal(favicon.href,images[0].src);
const previous=images[0].src;
const failure=module.applyExodusLogo();await tick();
decodes.shift().reject(new Error('synthetic decode failure'));await failure;
assert.equal(images[0].src,previous,'Failure must not substitute the original colors');
assert(status.textContent.includes('Reload to retry'));
const first=module.applyExodusLogo();await tick();
const second=module.applyExodusLogo();await tick();
const stale=decodes.shift(),current=decodes.shift();
current.resolve();await second;stale.resolve();await first;
assert.equal(images[0].src,current.url,'A late render must not overwrite the current choice');
for (const file of ['login.html','index.html']) {
 const html=await readFile(new URL('../../static/'+file,import.meta.url),'utf8');
 const marks=html.match(/<img[^>]*class="[^"]*exodus-logo[^>]*>/g);
 assert(marks.length>0);
 for(const mark of marks){assert(mark.includes('data-logo-pending'));assert(!mark.includes(' src='));}
 assert(!html.includes('rel="icon" type="image/png" href="/static/icons/exodus.png"'));
}
console.log('Themed logo first-paint, decode failure, stale render, and login/home markup checks passed.');
