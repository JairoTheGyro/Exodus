// Controlled DOM/transport tests of the actual event module (no real SSE claim).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source = readFileSync('static/js/workspaceEvents.js', 'utf8');
const window = new EventTarget(), document = new EventTarget();
document.hidden = false;
const sources = [];
class FakeSource extends EventTarget {
  constructor(url) { super(); this.url = url; this.closed = false; sources.push(this); }
  close() { this.closed = true; }
  change(topic) { const e = new Event('change'); e.data = JSON.stringify({topic}); this.dispatchEvent(e); }
}
const context = vm.createContext({window, document, EventSource:FakeSource, Map, Set, Promise, TypeError});
vm.runInContext(source.replaceAll('export ', '') + '\nglobalThis.bus={subscribe,publish,start,stop};', context);
const bus = context.bus;
let noteChanges = 0, reconnects = 0, calendarChanges = 0;
const off = bus.subscribe('notes', () => noteChanges++);
bus.subscribe('reconnect', () => reconnects++);
bus.subscribe('calendar', () => calendarChanges++);
bus.start(); bus.start();
assert.equal(sources.length, 1, 'One stream per page regardless of repeated start');
assert.equal(sources[0].url, '/api/workspace/events');
sources[0].dispatchEvent(new Event('ready'));
assert.equal(reconnects, 1);
sources[0].change('notes'); assert.equal(noteChanges, 1);
sources[0].change('unknown'); assert.equal(noteChanges, 1);
window.dispatchEvent(new Event('calendar-changed'));
window.dispatchEvent(new Event('calendar-refresh'));
assert.equal(calendarChanges, 2, 'UI and existing agent signals use same bus');
window.dispatchEvent(new Event('focus')); assert.equal(reconnects, 2);
off(); sources[0].change('notes'); assert.equal(noteChanges, 1);
document.hidden = true; document.dispatchEvent(new Event('visibilitychange'));
assert.equal(sources[0].closed, true);
sources[0].change('calendar'); assert.equal(calendarChanges, 2, 'Closed stale streams ignored');
document.hidden = false; document.dispatchEvent(new Event('visibilitychange'));
assert.equal(sources.length, 2); assert.equal(reconnects, 3);
sources[1].dispatchEvent(new Event('ready')); assert.equal(reconnects, 4);
window.dispatchEvent(new Event('online'));
assert.equal(sources[1].closed, true); assert.equal(sources.length, 3);
bus.stop();
assert.equal(sources[2].closed, true);
window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('focus'));
window.dispatchEvent(new Event('calendar-refresh'));
assert.equal(sources.length, 3); assert.equal(calendarChanges, 2); assert.equal(reconnects, 4);
assert.equal(source.includes('setInterval'), false, 'No interval data polling');
console.log('Workspace bus: owner stream connection, invalidation, unsubscribe, bridges, visibility/focus/reconnect lifecycle passed.');
