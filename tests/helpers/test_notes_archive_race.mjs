import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync('static/js/notes.js','utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const functions=section('function _archiveNoteById(','async function _saveNote(')+
  section('async function _patchNote(','// ---- Helpers ----')+
  section('export async function refreshDueBadge(','// ---- Panel ----').replace('export async','async');
function fixture(){
  const requests=[],badges=[],renders=[];
  let api;
  const context={API_BASE:'http://local.test',console,
    fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
    _renderNotes:()=>renders.push(api.ids()),_updateRailBadge:notes=>badges.push(notes),
    _pushUndo:()=>{},_undoArchive:()=>{},_hasItems:()=>false,
    uiModule:{showToast:()=>{},showError:()=>{}},
    document:{querySelector:()=>null}};
  vm.runInNewContext(`let _notes=[],_showingArchived=false,_open=true,_editingId=null,_loading=false;
    let _notesFetchSequence=0,_archiveRefreshRunning=false,_archiveRefreshPending=false;
    const _NOTE_UNDO_ICON='';
    ${functions}
    globalThis.api={fetch:_fetchNotes,archive:_archiveNoteById,badge:refreshDueBadge,
      ids:()=>_notes.map(n=>n.id).join(','),view:()=>_showingArchived,
      setView:value=>{_showingArchived=value;},setNotes:value=>{_notes=value;}};`,context);
  api=context.api;
  return {api,requests,badges,renders};
}
const response=(data)=>({ok:true,json:async()=>data});
const flush=()=>new Promise(resolve=>setImmediate(resolve));

// Late active-list GET must not replace a newer Archive result.
const a=fixture();const first=a.api.fetch();a.api.setView(true);const second=a.api.fetch();
a.requests[1].resolve(response({notes:[{id:'archived',archived:true}]}));await second;
a.requests[0].resolve(response({notes:[{id:'active'}]}));await first;
assert.equal(a.api.ids(),'archived');assert.equal(a.api.view(),true);

// Most recent request wins even within the same view.
const b=fixture();const older=b.api.fetch(),newer=b.api.fetch();
b.requests[1].resolve(response({notes:[{id:'new'}]}));await newer;
b.requests[0].resolve(response({notes:[{id:'old'}]}));await older;
assert.equal(b.api.ids(),'new');

// Archive toggled before PUT completes: pre-write empty GET then post-write refresh.
const c=fixture();c.api.setNotes([{id:'groceries',title:'Groceries'}]);
assert.equal(c.api.archive('groceries'),true);
assert.equal(c.requests[0].options.method,'PUT');
c.api.setView(true);const prematurelyRead=c.api.fetch();
c.requests[1].resolve(response({notes:[]}));await prematurelyRead;
assert.equal(c.api.ids(),'');
c.requests[0].resolve(response({id:'groceries',archived:true}));await flush();
assert.equal(c.requests[2].url,'http://local.test/api/notes?archived=true');
c.requests[2].resolve(response({notes:[{id:'groceries',archived:true}]}));await flush();
assert.equal(c.api.ids(),'groceries');assert.equal(c.renders.at(-1),'groceries');

// Badge refresh fetches active reminders without changing/replacing Archive.
const d=fixture();d.api.setView(true);d.api.setNotes([{id:'keep-archived',archived:true}]);
const badge=d.api.badge({force:true});assert.equal(d.api.view(),true);
d.requests[0].resolve(response({notes:[{id:'active-reminder'}]}));await badge;
assert.equal(d.api.view(),true);assert.equal(d.api.ids(),'keep-archived');
assert.equal(d.badges[0][0].id,'active-reminder');
console.log('PASS: Archive post-save refresh, stale list request protection, same-view ordering, badge/view independence.');
