// Exercise real Calendar mutation functions and Home listeners without a model.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const calendar = readFileSync('static/js/calendar.js', 'utf8');
const bus = await import('../../static/js/workspaceEvents.js');
const {createHomeUpdates} = await import('../../static/js/homeUpdates.js');
const events = new EventTarget();
const refreshes = [];
let respond;
const context = vm.createContext({
  window: events, CustomEvent, console, Math, Date, encodeURIComponent,
  API_BASE: '', _allEvents: {}, _events: [], _fetchedRanges: [], LS_KEY: 'test',
  _open: false, _optimisticEvent: (data, uid) => ({...data, uid}),
  _saveCache() {}, _render() {}, _updateBadge() {},
  localStorage: {removeItem() {}}, document: {getElementById: () => null},
  home: {hidden: false}, loadWidgets: kind => refreshes.push(kind),
  fetch: () => new Promise(resolve => { respond = resolve; }),
});
vm.runInContext(calendar.slice(calendar.indexOf('async function _createEvent('), calendar.indexOf('// ── Date helpers')), context);
globalThis.window=events;
globalThis.document=Object.assign(new EventTarget(),{hidden:false});
const updates=createHomeUpdates({subscribe:bus.subscribe,refresh:kind=>{if(kind==='schedule')refreshes.push(kind);},refreshProfile:async()=>{},allWidgets:['schedule'],schedule:()=>0,cancel:()=>{}});
bus.start();

let pending = vm.runInContext('_createEvent({summary:"Saved event"})', context);
assert.deepEqual(refreshes, [], 'Do not refresh before persistence succeeds');
respond({ok:true, json:async () => ({uid:'saved'})});
assert.equal((await pending).uid, 'saved');
await updates.flush();
assert.deepEqual(refreshes, ['schedule']);

pending = vm.runInContext('_updateEvent("saved", {summary:"Edited"})', context);
respond({ok:true});
await pending;await updates.flush();
assert.equal(refreshes.length, 2);

pending = vm.runInContext('_createEvent({summary:"Failed event"})', context);
respond({ok:false, status:503});
await assert.rejects(pending);
assert.equal(refreshes.length, 2, 'Failed saves must not announce a change');
assert.deepEqual(Object.keys(context._allEvents), ['saved'], 'Failed optimistic row is removed');

vm.runInContext('_deleteEvent("saved")',context);
respond({ok:false,status:503});
await new Promise(setImmediate);
await updates.flush();
assert.deepEqual(Object.keys(context._allEvents),['saved'],'Failed delete restores the event');
assert.equal(refreshes.length,2,'Failed deletes must not announce a change');

vm.runInContext('_deleteEvent("saved")',context);
respond({ok:true});
await new Promise(setImmediate);
await updates.flush();
assert.deepEqual(Object.keys(context._allEvents),[]);
assert.equal(refreshes.length,3,'Confirmed deletion refreshes Home');

// The agent stream already emits this event on manage_calendar completion.
events.dispatchEvent(new CustomEvent('calendar-refresh'));
await updates.flush();
assert.deepEqual(refreshes, ['schedule','schedule','schedule','schedule']);
updates.stop();bus.stop();
console.log('Calendar create/edit/delete, failure rollback, and agent → Home signals passed.');
