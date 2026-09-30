import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const nodes = new Map();
const properties = new Map();
const classes = new Set();
const listeners = new Map();
function node() { return { children: [], hidden: false, append(...children) { this.children.push(...children); for (const c of children) if(c.id) nodes.set(c.id,c); }, setAttribute() {} }; }
let opened = 0;
nodes.set('tool-theme-btn', {click() { opened++; }});
globalThis.document = {
  documentElement: { classList: {toggle(name, active) { active ? classes.add(name) : classes.delete(name); }}, style: {setProperty(k,v) {properties.set(k,v);},removeProperty(k) {properties.delete(k);}} },
  body: node(), createElement: node, getElementById: id => nodes.get(id),
};
globalThis.window = { innerWidth:1280, innerHeight:960, addEventListener:(name,cb)=>listeners.set(name,cb) };
const source = await readFile(new URL('../../static/js/temple.js',import.meta.url),'utf8');
const {applyTemplePresentation} = await import('data:text/javascript,'+encodeURIComponent(source));
applyTemplePresentation(true);
assert(classes.has('theme-temple'));
assert.equal(properties.get('--temple-scale'),'2');
assert.equal(document.body.children.length,1);
applyTemplePresentation(true);
assert.equal(document.body.children.length,1,'Repeated color application must not duplicate controls');
document.body.children[0].children[2].onclick();
assert.equal(opened,1,'Theme control must reuse the existing picker');
window.innerWidth=513; window.innerHeight=784; listeners.get('resize')();
assert.equal(Number(properties.get('--temple-scale')),513/640);
applyTemplePresentation(false);
assert(!classes.has('theme-temple'));
assert.equal(document.body.children[0].hidden,true);
assert(!properties.has('--temple-scale'));
listeners.get('resize')();
assert(!properties.has('--temple-scale'),'Normal themes must not retain Temple geometry');
console.log('Temple layout, scaling, control reuse, and restoration: 10 assertions passed');
