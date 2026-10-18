// Home uses existing content APIs. No model, embedding, or AI classification calls.
import * as WorkspaceEvents from './workspaceEvents.js';
import {createScratchpad} from './homeScratchpad.js';
import {createHomeUpdates, createResponseGuard} from './homeUpdates.js';
let scratchpad, homeUpdates, captureUnsubscribe;
const beginResponse = createResponseGuard();
// Preserve actual form nodes (and focus), not just a snapshot of their values.
function renderWidget(w, html) {
 const forms = [...w.querySelectorAll('form[id],#home-task-filter')];
 const details = [...w.querySelectorAll('details')].map(d=>d.open);
 const active = document.activeElement, selection = active && {start:active.selectionStart,end:active.selectionEnd};
 const template = document.createElement('template'); template.innerHTML = html;
 for(const form of forms) { const replacement=template.content.getElementById(form.getAttribute('id')); if(replacement)replacement.replaceWith(form); }
 w.replaceChildren(template.content);
 w.querySelectorAll('details').forEach((d,i)=>{if(details[i]!==undefined)d.open=details[i];});
 if(active && w.contains(active)){active.focus({preventScroll:true});if(selection.start!=null)active.setSelectionRange?.(selection.start,selection.end);}
}
let profile = {}, owner = '', tasks = null, focus = {}, home, timers = [], searchController;
const widgetNames = {capture:'Quick capture',tasks:'Your tasks',schedule:'Today’s schedule',focus:'Time to focus',inbox:'Inbox',files:'Recent & pinned',apps:'Your workspace',metrics:'Progress',team:'System diagnostics',weather:'Local weather'};
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dayKey = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const safeUrl = value => {try {const u=new URL(value);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}};
const status = text => {if($('home-status')) $('home-status').textContent=text;};
async function api(path, options={}) {const r=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...options.headers}}); const b=await r.json().catch(()=>({})); if(!r.ok) {const error=Error(typeof b.detail==='string'?b.detail:typeof b.detail?.message==='string'?b.detail.message:typeof b.error==='string'?b.error:`Could not load (${r.status})`);error.status=r.status;error.detail=b.detail;throw error;} return b;}
const post = (path, body, method='POST') => api(path,{method,body:JSON.stringify(body)});
async function patch(values) {profile=(await post('/api/home/profile',values,'PATCH')).profile; syncMemoryPolicySetting(); return profile;}
async function action(button, fn) {if(button) button.disabled=true;try{await fn();}catch(e){status(e.message);}finally{if(button)button.disabled=false;}}
function empty(text){return `<p class="home-empty">${esc(text)}</p>`;}
function widget(id){return home?.querySelector(`[data-widget="${id}"] .home-widget-body`);}
function showHome(){if(window.documentModule?.isPanelOpen())window.documentModule.closePanel();home.hidden=false;document.body.classList.add('home-active');document.title='Home · Exodus'; homeUpdates ? homeUpdates.enqueue('reconnect') : loadWidgets();}
function hideHome(){home.hidden=true;document.body.classList.remove('home-active');}
async function launch(kind,id){
  if(kind==='home')return showHome();
  if(kind==='settings'){const m=await import('./settings.js?v=20260912writingstyle3'); m.default.open(profile.mode==='ai-free'?'appearance':'services'); return;}
  if(kind==='theme'){ $('tool-theme-btn')?.click(); return; }
  if(kind==='file'){ const m=await import('./document.js?v=20260916docctx2'); await m.default.loadDocument(id);return;}
  if(kind==='note'||kind==='task'){const m=await import('./notes.js?v=20260911notesselectioncancel1');await m.openNote(id);return;}
  const targets={notes:'tool-notes-btn',calendar:'tool-calendar-btn',library:'tool-library-btn',email:'email-section-title',code:'tool-code-btn',workshop:'tool-workshop-btn',vault:'privacy-vaultwarden-btn',search:'local-searxng-btn'};
  if(kind==='library'){const m=await import('./document.js?v=20260916docctx2');m.default.openLibrary();return;}
  if(kind==='email'){const m=await import('./emailLibrary.js?v=20260915trashmove2');m.openEmailLibrary(id&&typeof id==='object'?{uid:id.uid,folder:id.folder||'INBOX',account_id:id.account_id,message:id}:{});return;}
  if(kind==='vault'||kind==='search'){const m=await import('./settings/localServices.js');m.openLocalServices(kind==='vault'?'vaultwarden':'searxng');return;}
  const btn=$(targets[kind]); if(btn){if(kind==='code'||kind==='workshop')hideHome();btn.click();}
}
function enforceMode(){
  document.documentElement.dataset.workspaceMode=profile.mode||'choose';
  if(profile.mode!=='ai-free')return;
  document.querySelectorAll('.vis-row').forEach(row=>{
    const key=row.querySelector('[data-ui-key]')?.dataset.uiKey||'';
    if (/chat|session|search|brain|memory|compare|cookbook|research|gallery|persona|thinking|censor|incognito|shell|agent/i.test(key)) row.classList.add('home-ai-feature');
  });
  document.querySelectorAll('[data-settings-panel="appearance"] .admin-card').forEach(card=>{
    if (/^Chat (Area|Bar)/.test(card.querySelector('h2')?.textContent.trim()||''))card.classList.add('home-ai-feature');
  });
  const selectors='button,[role="button"],summary,label,.settings-nav-item';
  document.querySelectorAll(selectors).forEach(el=>{
    if(el.closest('#workspace-home,#workspace-mode-settings,.note-memory-policy,#tasks-modal,[data-settings-panel="reminders"],[data-settings-panel="integrations"]'))return;
    const text=[el.getAttribute('title'),el.getAttribute('aria-label'),el.textContent].filter(Boolean).join(' ');
    if(text.length<220 && /\b(AI|LLM|agent|agents|model|models|summarize|summarise|translate|deep research|nobody mode|voice chat|ask exodus|new chat)\b/i.test(text)) el.classList.add('home-ai-feature');
  });
}
function syncMemoryPolicySetting(){
 const toggle=$('workspace-archived-memory');
 if(!toggle||toggle.disabled)return;
 const selected=profile.ai_include_archived_notes===true;
 if(toggle.checked!==selected){
  toggle.checked=selected;
  const message=toggle.closest('.home-memory-policy')?.querySelector('[role="status"]');
  if(message)message.textContent='Updated from your saved account settings.';
 }
}
function installSettings(){
 const anchor=$('settings-modal')?.querySelector('.settings-view-bar');
 if(anchor&&!$('workspace-mode-settings')){
  const bar=document.createElement('div');bar.id='workspace-mode-settings';
  bar.innerHTML='<strong>Workspace mode</strong><span id="workspace-mode-label"></span><button type="button" id="workspace-mode-change">Change my mode</button><button type="button" id="workspace-home-settings">Home layout</button>';
  anchor.before(bar);$('workspace-mode-label').textContent=profile.mode==='ai-free'?'AI-free · this account':'Full Exodus · this account';
  $('workspace-mode-change').onclick=async()=>{(await import('./settings.js?v=20260912writingstyle3')).close();showHome();$('home-choice').hidden=false;};
  $('workspace-home-settings').onclick=async()=>{(await import('./settings.js?v=20260912writingstyle3')).close();showHome();$('home-customize').hidden=false;renderCustomize();};
  const policy=document.createElement('div');policy.className='home-memory-policy';
  policy.innerHTML='<label><input type="checkbox" id="workspace-archived-memory"> Allow AI to use my archived notes</label><small>Off by default. Applies only in Full mode, and only to notes with automatic AI memory enabled.</small><span role="status"></span>';
  bar.append(policy);
  const toggle=policy.querySelector('input'),status=policy.querySelector('[role="status"]');
  toggle.checked=profile.ai_include_archived_notes===true;
  toggle.onchange=async()=>{const selected=toggle.checked;toggle.disabled=true;++profileSequence;try{profile=(await api('/api/home/profile',{method:'PATCH',body:JSON.stringify({ai_include_archived_notes:selected})})).profile;status.textContent='Saved for your account.';}catch{toggle.checked=profile.ai_include_archived_notes===true;status.textContent='Could not save. Try again.';}finally{++profileSequence;toggle.disabled=false;syncMemoryPolicySetting();}};
 }
 syncMemoryPolicySetting();
}
function greeting(){const now=new Date();$('home-greeting').textContent=`Good ${now.getHours()<12?'morning':now.getHours()<18?'afternoon':'evening'}${owner?', '+owner:''}.`;$('home-date').textContent=now.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'})+' · '+now.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});}
function renderShell(){
 home=document.createElement('main');home.id='workspace-home';home.setAttribute('aria-label','Workspace Home');
 home.innerHTML=`<div class="home-topbar"><div class="home-row"><img class="exodus-logo" src="/static/icons/exodus.png" alt=""><strong>EXODUS</strong><span class="home-badge" id="home-mode-label"></span></div><div class="home-actions"><button id="home-menu">Menu</button><button id="home-theme">Theme</button><button id="home-refresh">Refresh</button><button id="home-layout">Customize</button><button id="home-settings">Settings</button></div></div>
 <header class="home-hero"><span class="home-eyebrow">A little clarity for your day</span><h1 id="home-greeting">Your workspace.</h1><div class="home-row"><span id="home-date" class="home-subtitle"></span><label>My status <select id="home-availability"><option value="available">Available</option><option value="focus">In focus mode</option><option value="meeting">In a meeting</option><option value="lunch">Out for lunch</option><option value="away">Away</option></select></label></div></header>
 <form id="home-search-form" class="home-search-form"><input id="home-search" type="search" minlength="2" maxlength="200" placeholder="Search files, tasks, notes, email and contacts…" aria-label="Search workspace" required><button>Search</button></form><div id="home-search-results" aria-live="polite"></div>
 <p class="home-muted">Demo workspace · use non-sensitive information only.</p><p id="home-status" role="status" aria-live="polite"></p>
 <section id="home-customize" hidden aria-label="Customize Home"></section><div class="home-grid" id="home-grid"></div>
 <section id="home-choice" hidden aria-label="Choose your workspace"><div class="home-choice-inner"><span class="home-eyebrow">Welcome to Exodus</span><h1>Your workspace.<br>Your choice.</h1><p>Choose the experience for <strong>${esc(owner||'your account')}</strong>. You can change it in Settings anytime.</p><div class="home-choices"><button data-mode="full"><strong>Full Exodus</strong><span>Your complete workspace, with AI chat, agents, Workshop and Code available whenever you want them.</span></button><button data-mode="ai-free"><strong>AI-free workspace</strong><span>Tasks, calendar, email, files and focus. AI features are hidden and AI operations are blocked for your account.</span></button></div><p class="home-muted">This affects only your account. Saved chats and model settings are retained for switching back. Other accounts and independently opened services keep their own settings.</p><p id="home-choice-status" role="status"></p></div></section>`;
 document.body.append(home);
 import('./settings/brand.js').then(m=>m.applyExodusLogo()).catch(()=>{});
 $('home-choice').hidden=!!profile.mode;
 $('home-mode-label').textContent=profile.mode==='ai-free'?'AI-free':'Full workspace';
 home.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>action(b,async()=>{try{await patch({mode:b.dataset.mode});location.href='/';}catch(e){$('home-choice-status').textContent=e.message;throw e;}}));
 $('home-availability').value=profile.status||'available';$('home-availability').onchange=()=>action(null,async()=>{await patch({status:$('home-availability').value});loadTeam();});
 $('home-menu').onclick=()=>$('hamburger-btn')?.click();$('home-theme').onclick=()=>launch('theme');$('home-settings').onclick=()=>launch('settings');
 $('home-refresh').onclick=()=>homeUpdates.enqueue('reconnect');
 $('home-layout').onclick=()=>{$('home-customize').hidden=!$('home-customize').hidden;renderCustomize();};
 $('home-search-form').onsubmit=searchAll;
 const sidebar=$('sidebar-new-chat-btn');const button=document.createElement('button');button.id='home-sidebar-button';button.textContent='⌂  Home';button.onclick=showHome;if(sidebar)sidebar.before(button);else $('sidebar')?.prepend(button);
 const rail=document.createElement('button');rail.id='home-rail-button';rail.textContent='⌂';rail.title='Home';rail.setAttribute('aria-label','Home');rail.onclick=showHome;$('rail-calendar')?.before(rail);
 document.querySelectorAll('#sidebar [id^="tool-"],#sidebar-new-chat-btn,#email-section-title').forEach(b=>b.addEventListener('click',()=>{if(['sidebar-new-chat-btn','tool-workshop-btn','tool-code-btn'].includes(b.id))hideHome();},true));
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('home-choice').hidden&&profile.mode){$('home-choice').hidden=true;}});
 greeting();renderGrid();installSettings();
}
function renderGrid(){
 const order=[...new Set([...(profile.order||[]),...Object.keys(widgetNames)])].filter(id=>widgetNames[id]);
 const grid=$('home-grid');let position=0;
 for(const id of order){
  let card=grid.querySelector(`[data-widget="${id}"]`);
  if(!card){
   card=document.createElement('section');card.className='home-card';card.dataset.widget=id;
   card.innerHTML=`<header><h2>${widgetNames[id]}</h2><div class="home-card-actions">${id==='inbox'?'<button type="button" data-refresh-inbox aria-label="Refresh inbox" title="Check for new email">↻</button>':''}${id==='team'?'<button type="button" data-refresh-diagnostics aria-label="Refresh system diagnostics" title="Refresh system diagnostics">↻</button>':''}<button aria-label="Collapse ${widgetNames[id]}" data-collapse="${id}">−</button></div></header><div class="home-widget-body">${empty('Loading…')}</div>`;
  }
  card.hidden=(profile.hidden||[]).includes(id);card.dataset.collapsed=String((profile.collapsed||[]).includes(id));
  const toggle=card.querySelector('[data-collapse]');toggle.setAttribute('aria-expanded',String(card.dataset.collapsed!=='true'));toggle.textContent=card.dataset.collapsed==='true'?'+':'−';
  if(grid.children[position]!==card)grid.insertBefore(card,grid.children[position]||null);position++;
 }
 const refresh=home.querySelector('[data-refresh-inbox]');
 if(refresh)refresh.onclick=()=>action(refresh,()=>loadInbox(widget('inbox'),{refresh:true}));
 const diagnostics=home.querySelector('[data-refresh-diagnostics]');
 if(diagnostics)diagnostics.onclick=()=>action(diagnostics,()=>load('team',loadTeam));
 home.querySelectorAll('[data-collapse]').forEach(b=>b.onclick=()=>action(b,async()=>{const id=b.dataset.collapse;const set=new Set(profile.collapsed||[]);set.has(id)?set.delete(id):set.add(id);await patch({collapsed:[...set]});b.closest('section').dataset.collapsed=String(set.has(id));b.setAttribute('aria-expanded',String(!set.has(id)));b.textContent=set.has(id)?'+':'−';}));
}
function renderCustomize(){
 const panel=$('home-customize');const order=[...new Set([...(profile.order||[]),...Object.keys(widgetNames)])];
 panel.innerHTML=`<h2>Make room for what matters</h2><p class="home-muted">Role presets change layout only, never permissions.</p><label>Starting layout <select id="home-role">${['personal','developer','sales','team'].map(r=>`<option ${profile.role===r?'selected':''}>${r}</option>`).join('')}</select></label><div>${order.map((id,i)=>`<div class="home-row"><label><input type="checkbox" data-show="${id}" ${!(profile.hidden||[]).includes(id)?'checked':''}>${widgetNames[id]}</label><button data-move="${id}" data-step="-1" ${i===0?'disabled':''} aria-label="Move ${widgetNames[id]} up">↑</button><button data-move="${id}" data-step="1" ${i===order.length-1?'disabled':''} aria-label="Move ${widgetNames[id]} down">↓</button></div>`).join('')}</div><button id="home-customize-close">Done</button>`;
 $('home-customize-close').onclick=()=>panel.hidden=true;
 panel.querySelectorAll('[data-show]').forEach(b=>b.onchange=()=>action(b,async()=>{const hidden=new Set(profile.hidden||[]);b.checked?hidden.delete(b.dataset.show):hidden.add(b.dataset.show);await patch({hidden:[...hidden]});renderGrid();loadWidgets();}));
 panel.querySelectorAll('[data-move]').forEach(b=>b.onclick=()=>action(b,async()=>{const i=order.indexOf(b.dataset.move),j=i+Number(b.dataset.step);[order[i],order[j]]=[order[j],order[i]];await patch({order});renderGrid();renderCustomize();loadWidgets();}));
 $('home-role').onchange=()=>action(null,async()=>{const role=$('home-role').value;const presets={personal:['capture','tasks','schedule','focus','files','apps','inbox','metrics','weather','team'],developer:['tasks','apps','focus','files','schedule','capture','inbox','metrics','team','weather'],sales:['schedule','inbox','metrics','tasks','files','apps','capture','focus','team','weather'],team:['team','tasks','schedule','inbox','files','metrics','apps','focus','capture','weather']};await patch({role,order:presets[role],hidden:[]});renderGrid();renderCustomize();loadWidgets();});
}
const loadVersions = new Map();
async function load(id,fn){const w=widget(id);if(!w||w.closest('[data-widget]').hidden)return;const revision=(loadVersions.get(id)||0)+1;loadVersions.set(id,revision);try{await fn(w);if(loadVersions.get(id)===revision)w.querySelector(':scope > .home-load-error')?.remove();}catch(e){if(loadVersions.get(id)!==revision||!w.isConnected)return;w.querySelector(':scope > .home-load-error')?.remove();const box=document.createElement('p');box.className='home-load-error';box.setAttribute('role','status');box.textContent=e.message+' ';const retry=document.createElement('button');retry.textContent='Retry';retry.onclick=()=>loadWidgets(id);box.append(retry);w.append(box);}}
function loadWidgets(only){const jobs={tasks:loadTasks,schedule:loadSchedule,focus:loadFocus,inbox:loadInbox,files:loadFiles,capture:loadCapture,apps:loadApps,metrics:loadMetrics,team:loadTeam,weather:loadWeather};for(const [id,fn]of Object.entries(jobs))if(!only||only===id)load(id,fn);}
let profileSequence=0;
async function refreshProfile(){const sequence=++profileSequence;try{const data=await api('/api/home/profile');if(sequence!==profileSequence)return;if(data.profile.mode!==profile.mode){location.reload();return;}profile=data.profile;syncMemoryPolicySetting();renderGrid();if(document.activeElement!==$('home-availability'))$('home-availability').value=profile.status||'available';}catch(e){status('Workspace preferences could not refresh. '+e.message);}}
async function loadTasks(w=widget('tasks')){if(!w)return;const current=beginResponse(w);const data=await api('/api/home/tasks');if(!current())return;tasks=data.tasks;renderWidget(w,`<label>Show <select id="home-task-filter"><option value="open">Open tasks</option><option value="today">Due today</option><option value="overdue">Overdue</option><option value="high">High priority</option><option value="done">Completed</option></select></label><ul class="home-list" id="home-task-list"></ul><details><summary>Add a task</summary><form class="home-form" id="home-task-form"><input name="text" aria-label="Task" placeholder="What needs doing?" maxlength="500" required><input name="project" aria-label="Project" placeholder="Project or area (optional)" maxlength="100"><label>Due date<input name="due" type="date"></label><label>Priority<select name="priority"><option value="normal">Normal</option><option value="high">High</option></select></label><button>Add task</button></form></details><p class="home-muted">Shared with Notes checklists · latest 500 checklists.</p>`);
 const render=()=>{const filter=$('home-task-filter').value,today=dayKey(new Date());const rows=tasks.filter(t=>filter==='done'?t.done:!t.done&&(filter==='open'||filter==='high'&&t.priority==='high'||filter==='today'&&t.due?.slice(0,10)===today||filter==='overdue'&&t.due&&t.due.slice(0,10)<today));$('home-task-list').innerHTML=rows.length?rows.map((t)=>`<li><div class="home-row"><input type="checkbox" data-task="${tasks.indexOf(t)}" aria-label="Complete ${esc(t.text)}" ${t.done?'checked':''}><div class="home-title">${esc(t.text)}<small>${esc(t.project)}${t.due?' · '+esc(t.due.slice(0,10)):''}${t.priority==='high'?' · High priority':''}</small></div></div></li>`).join(''):empty('Nothing here. A little breathing room.');$('home-task-list').querySelectorAll('[data-task]').forEach(b=>b.onchange=()=>action(b,async()=>{const t=tasks[Number(b.dataset.task)];try{await post(`/api/home/tasks/${encodeURIComponent(t.note_id)}/${t.index}`,{text:t.text,done:b.checked},'PUT');t.done=b.checked;render();WorkspaceEvents.publish('notes');}catch(e){b.checked=t.done;throw e;}}));};$('home-task-filter').onchange=render;render();
 $('home-task-form').onsubmit=e=>{e.preventDefault();const f=e.currentTarget,data=Object.fromEntries(new FormData(f));data.due=data.due||null;action(f.querySelector('button'),async()=>{await post('/api/home/tasks',data);f.reset();WorkspaceEvents.publish('notes');status('Task saved in Notes.');});};
}
let scheduleRevision=0;
async function loadSchedule(w){const revision=++scheduleRevision;const start=new Date();start.setHours(0,0,0,0);const end=new Date(start);end.setDate(end.getDate()+1);const result=await api('/api/calendar/events?'+new URLSearchParams({start:start.toISOString(),end:end.toISOString(),local_start:dayKey(start),local_end:dayKey(end)}));if(revision!==scheduleRevision||!w.isConnected)return;const events=result.events||[];w.innerHTML=events.length?`<ul class="home-list">${events.map(e=>{const url=(String(e.location||'')+' '+String(e.description||'')).match(/https?:\/\/[^\s<>"']+/g)?.map(safeUrl).find(u=>u&&/^(meet\.google\.com|([a-z0-9-]+\.)?zoom\.us|teams\.microsoft\.com)$/i.test(new URL(u).hostname));return `<li><strong>${esc(e.summary||'Untitled event')}</strong><small>${e.all_day?'All day':esc(new Date(e.dtstart).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}))} · ${esc(e.location||'')}</small>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Join meeting ↗</a>`:''}</li>`;}).join('')}</ul>`:empty('No events today. Leave space for something good.');w.insertAdjacentHTML('beforeend','<button data-calendar>Open Calendar</button>');w.querySelector('button').onclick=()=>launch('calendar');}
async function loadFocus(w=widget('focus')){if(!w)return;const current=beginResponse(w);const data=await api('/api/home/focus');if(!current())return;focus=data;renderWidget(w,`<div class="home-clock" id="home-focus-clock">25:00</div><p class="home-muted" id="home-focus-note"></p><form id="home-focus-form" class="home-form"><input name="project" placeholder="Project or task" aria-label="Timer project" maxlength="100"><div class="home-row"><select name="kind" aria-label="Timer type"><option value="pomodoro">Pomodoro</option><option value="timer">Project timer</option></select><label>Minutes<input name="minutes" type="number" min="1" max="180" value="25" style="width:70px"></label></div><button id="home-focus-button">${focus.active?'Stop & save time':'Start focus'}</button></form>`);w.querySelectorAll('input,select').forEach(e=>e.disabled=!!focus.active);$('home-focus-button').textContent=focus.active?'Stop & save time':'Start focus';tickFocus();$('home-focus-form').onsubmit=e=>{e.preventDefault();action($('home-focus-button'),async()=>{const b=Object.fromEntries(new FormData(e.target));b.minutes=Number(b.minutes||25);b.action=focus.active?'stop':'start';focus=await post('/api/home/focus',b);WorkspaceEvents.publish('focus');});};}
function tickFocus(){if(!$('home-focus-clock'))return;const active=focus.active;if(!active){$('home-focus-clock').textContent='25:00';$('home-focus-note').textContent='One thing at a time. Time is saved when you stop.';return;}const elapsed=Math.max(0,Date.now()/1000-active.started),seconds=Math.round(active.kind==='pomodoro'?Math.max(0,active.minutes*60-elapsed):elapsed);$('home-focus-clock').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;$('home-focus-note').textContent=seconds===0&&active.kind==='pomodoro'?`${active.project} · Time’s up. Stop to save this session.`:`${active.project} · ${active.kind==='pomodoro'?'Focus session':'Project timer'}`;}
let inboxLoadSequence = 0;
async function loadInbox(w, {refresh = false} = {}) {
 const sequence = ++inboxLoadSequence;
 const current = () => sequence === inboxLoadSequence && w.isConnected;
 w.setAttribute('aria-busy', 'true');
 try {
  const result = await api('/api/email/accounts');
  const accounts = (result.accounts || []).filter(a => a.enabled !== false).slice(0, 10);
  const results = await Promise.allSettled(accounts.map(a => {
   const params = new URLSearchParams({filter:'unread', folder:'INBOX', limit:'5', account_id:a.id});
   if(refresh) params.set('_', String(Date.now()));
   else params.set('cached_only', '1');
   return api('/api/email/list?' + params);
  }));
  if(!current())return;
  const emails = results.flatMap((r,i) => r.status === 'fulfilled' && !r.value.error
   ? (r.value.emails || []).map(e => ({...e, account_id:accounts[i].id, folder:e.folder || 'INBOX', account:accounts[i].name})) : []).slice(0,10);
  const failed = results.some(r => r.status === 'rejected' || r.value.error);
  w.innerHTML = emails.length ? `<ul class="home-list">${emails.map((e,i) => `<li><button type="button" class="home-link home-email" data-email="${i}">${esc(String(e.subject || '').trim() || '(No Subject)')}<small>${esc(e.from_name || e.from_address || e.from || '')} · ${esc(e.account)}</small></button></li>`).join('')}</ul>`
   : empty(!accounts.length ? 'No email account connected.' : failed ? 'Inbox could not be refreshed. Try again.' : refresh ? 'No unread messages.' : 'No unread messages in the local email cache. Refresh to check for new email.');
  if(failed && emails.length)w.insertAdjacentHTML('beforeend',empty('Some accounts could not be refreshed.'));
  w.insertAdjacentHTML('beforeend','<button data-inbox>Open Inbox</button><p class="home-muted">Email accounts connected to Exodus. Slack, Teams and document-comment integrations are not connected.</p>');
  w.querySelector('[data-inbox]').onclick = () => action(null, () => launch('email'));
  w.querySelectorAll('[data-email]').forEach(b => b.onclick = () => action(b, () => launch('email', emails[Number(b.dataset.email)])));
  if(refresh)status(failed ? 'Some email accounts could not be refreshed.' : accounts.length ? 'Inbox refreshed.' : 'No email account connected.');
 } catch(e) {
  if(current()) {
   // Keep usable cached rows on a failed refresh.
   if(refresh)status('Inbox refresh failed. ' + e.message);
   else {w.innerHTML=empty(e.message)+'<button data-inbox-retry>Retry</button>';w.querySelector('button').onclick=()=>loadInbox(w);}
  }
 } finally {if(current())w.setAttribute('aria-busy','false');}
}

async function loadFiles(w){
 const current=beginResponse(w);const {files}=await api('/api/home/files');if(!current())return;
 w.innerHTML=files.length?`<ul class="home-list">${files.map((f,i)=>`<li><div class="home-row"><button class="home-link home-title" data-file="${i}">${esc(f.title||"Untitled document")}<small>${esc(f.kind==='note'?'Note':f.kind==='upload'?'Uploaded file':f.language||'Document')} · ${esc(new Date(f.updated).toLocaleDateString())}</small></button><button data-pin="${esc(f.id)}" aria-label="${f.pinned?'Unpin':'Pin'} ${esc(f.title||"Untitled document")}">${f.pinned?'★':'☆'}</button></div></li>`).join('')}</ul>`:empty('Your recent notes and files will appear here.');
 w.insertAdjacentHTML('beforeend','<button data-library>Open Library</button>');w.querySelector('[data-library]').onclick=()=>launch('library');
 w.querySelectorAll('[data-file]').forEach(b=>b.onclick=()=>action(b,async()=>{const f=files[Number(b.dataset.file)];if(f.kind==='upload'){const a=document.createElement('a');a.href='/api/documents/'+encodeURIComponent(f.source_id)+'/download';a.download='';document.body.append(a);a.click();a.remove();}else await launch(f.kind==='note'?'note':'file',f.source_id||f.id);}));
 w.querySelectorAll('[data-pin]').forEach(b=>b.onclick=()=>action(b,async()=>{const set=new Set(profile.pins||[]);set.has(b.dataset.pin)?set.delete(b.dataset.pin):set.add(b.dataset.pin);await patch({pins:[...set]});WorkspaceEvents.publish('documents');}));
}
function loadCapture(w){
 if(!$('home-capture-form')){
  w.innerHTML='<p class="home-muted">Catch the thought. Keep your flow. Automatically saved on this Exodus server.</p><form id="home-capture-form" class="home-form"><textarea id="home-capture" placeholder="An idea, a link, a reminder…" aria-label="Quick note" maxlength="20000"></textarea><p id="home-capture-status" class="home-muted" role="status"></p><div class="home-row"><button id="home-capture-save" type="submit">Save to Notes</button><button id="home-capture-retry" type="button" hidden>Retry save</button></div><div id="home-capture-conflict" hidden><p>Another window saved a different version. Your draft is still above.</p><details><summary>View the saved version</summary><pre id="home-capture-remote"></pre></details><div class="home-row"><button type="button" data-draft-local>Keep my draft</button><button type="button" data-draft-remote>Use saved version</button></div></div></form>';
  $('home-capture').oninput=e=>scratchpad.input(e.target.value);
  captureUnsubscribe?.();captureUnsubscribe=scratchpad.subscribe(state=>{
   const input=$('home-capture');if(!input)return;if(input.value!==state.text)input.value=state.text;
   $('home-capture-status').textContent=state.pending?(state.busy?'Saving to Notes…':'Save to Notes needs confirmation. Retry with the same note request. '+state.error):state.conflict?'Choose which version to keep.':state.busy?'Saving…':state.revision===null?'Loading saved scratchpad…':state.dirty?'Unsaved changes'+(state.recoveryAvailable?' · draft kept in this browser.':' · browser recovery is unavailable. Keep this page open.'):'Saved on this Exodus server.';
   // Error text takes precedence, except for an uncertain note conversion.
   if(state.error&&!state.pending)$('home-capture-status').textContent=state.error;
   if(!state.recoveryAvailable&&(state.dirty||state.pending||state.conflict))$('home-capture-status').textContent+=' Browser recovery is unavailable; keep this page open.';
   $('home-capture-save').disabled=state.busy||!!state.conflict||(!state.text.trim()&&!state.pending);$('home-capture-save').textContent=state.pending?(state.busy?'Saving…':'Retry Save to Notes'):'Save to Notes';
   $('home-capture-retry').hidden=!state.error||!!state.pending||!!state.conflict;$('home-capture-retry').disabled=state.busy;
   $('home-capture-conflict').hidden=!state.conflict;$('home-capture-remote').textContent=state.conflict?.text||'';
  });
  $('home-capture-form').onsubmit=e=>{e.preventDefault();action(null,async()=>{await scratchpad.convert();status('Saved to Notes with the #quick-capture tag.');WorkspaceEvents.publish('notes');});};
  $('home-capture-retry').onclick=()=>action(null,()=>scratchpad.flush());
  w.querySelector('[data-draft-local]').onclick=()=>action(null,()=>scratchpad.resolve('local'));
  w.querySelector('[data-draft-remote]').onclick=()=>action(null,()=>scratchpad.resolve('remote'));
 }
 return scratchpad.refresh();
}
function loadApps(w){const apps=[['notes','Notes'],['calendar','Calendar'],['library','Library'],['email','Email'],['vault','Vaultwarden'],['search','Private search']];if(profile.mode!=='ai-free')apps.push(['workshop','AI Workshop'],['code','Code']);renderWidget(w,`<div class="home-apps">${apps.map(([id,label])=>`<button data-app="${id}">${label} ↗</button>`).join('')}${(profile.shortcuts||[]).map(s=>`<a href="${esc(safeUrl(s.url)||'#')}" rel="noopener noreferrer" target="_blank">${esc(s.title)} ↗</a>`).join('')}</div><details><summary>Add or manage shortcuts</summary><form class="home-form" id="home-shortcut-form"><input name="title" placeholder="Name" aria-label="Shortcut name" required maxlength="80"><input name="url" type="url" placeholder="https://…" aria-label="Shortcut address" required><button>Add shortcut</button></form>${(profile.shortcuts||[]).map(s=>`<p>${esc(s.title)} <button data-remove-link="${esc(s.id)}">Remove</button></p>`).join('')}</details>`);w.querySelectorAll('[data-app]').forEach(b=>b.onclick=()=>launch(b.dataset.app));$('home-shortcut-form').onsubmit=e=>{e.preventDefault();action(e.target.querySelector('button'),async()=>{profile.shortcuts=(await post('/api/home/shortcuts',Object.fromEntries(new FormData(e.target)))).shortcuts;e.target.reset();WorkspaceEvents.publish('profile');});};w.querySelectorAll('[data-remove-link]').forEach(b=>b.onclick=()=>action(b,async()=>{await api('/api/home/shortcuts/'+encodeURIComponent(b.dataset.removeLink),{method:'DELETE'});profile.shortcuts=profile.shortcuts.filter(s=>s.id!==b.dataset.removeLink);WorkspaceEvents.publish('profile');}));}
async function loadMetrics(w){const current=beginResponse(w);const [taskData,focusData]=await Promise.all([api('/api/home/tasks'),api('/api/home/focus')]);if(!current())return;const metricTasks=taskData.tasks,metricFocus=focusData;const today=dayKey(new Date()),minutes=Math.round((metricFocus.sessions||[]).filter(s=>dayKey(new Date(s.started*1000))===today).reduce((n,s)=>n+s.seconds,0)/60);renderWidget(w,`<div class="home-stats"><div><div class="home-stat">${metricTasks?metricTasks.filter(t=>!t.done).length:'—'}</div><small>Open checklist items</small></div><div><div class="home-stat">${metricFocus.sessions?minutes:'—'}</div><small>Minutes tracked today</small></div></div><p class="home-muted">From your checklists and stopped timers. Goals below are manually maintained.</p>${(profile.goals||[]).map(g=>`<div class="home-goal"><div class="home-row"><strong>${esc(g.title)}</strong><span>${g.current} / ${g.target}</span><button data-edit-goal="${g.id}">Update</button><button data-remove-goal="${g.id}">Remove</button></div><progress value="${Math.min(g.current,g.target)}" max="${g.target}" aria-label="${esc(g.title)}"></progress></div>`).join('')}<details id="home-goal-details"><summary>Add a goal</summary><form id="home-goal-form" class="home-form"><input name="id" type="hidden"><input name="title" placeholder="Goal (e.g. books read)" aria-label="Goal name" maxlength="80" required><label>Current<input type="number" name="current" min="0" max="1000000000000" step="any" value="0" required></label><label>Target<input type="number" name="target" min="0.01" max="1000000000000" step="any" value="1" required></label><button>Save goal</button></form></details>`);$('home-goal-form').onsubmit=e=>{e.preventDefault();action(e.target.querySelector('button'),async()=>{const b=Object.fromEntries(new FormData(e.target));b.current=Number(b.current);b.target=Number(b.target);b.id=b.id||null;profile.goals=(await post('/api/home/goals',b)).goals;e.target.reset();WorkspaceEvents.publish('goals');});};w.querySelectorAll('[data-edit-goal]').forEach(b=>b.onclick=()=>{const g=profile.goals.find(g=>g.id===b.dataset.editGoal);$('home-goal-details').open=true;for(const k of ['id','title','current','target'])$('home-goal-form').elements[k].value=g[k];});w.querySelectorAll('[data-remove-goal]').forEach(b=>b.onclick=()=>action(b,async()=>{await api('/api/home/goals/'+b.dataset.removeGoal,{method:'DELETE'});profile.goals=profile.goals.filter(g=>g.id!==b.dataset.removeGoal);WorkspaceEvents.publish('goals');}));}
const formatBytes = bytes => Number.isFinite(bytes) ? `${(bytes/1024/1024/1024).toFixed(1)} GB` : 'Unavailable';
async function loadTeam(w=widget('team')){
 if(!w)return;
 if(!w.querySelector('[data-system-values]'))w.innerHTML='<div data-system-values aria-live="polite">'+empty('Checking local services…')+'</div><details class="home-team-details"><summary>Team presence & announcements</summary><div data-team-values></div></details>';
 const diagnostics=w.querySelector('[data-system-values]'),team=w.querySelector('[data-team-values]');
 const current=beginResponse(diagnostics),teamCurrent=beginResponse(team);
 const systemJob=(async()=>{try{
  const data=await api('/api/home/diagnostics');if(!current())return;
  const names={notes:'Notes database',calendar:'Calendar database',mail_cache:'Email cache',vaultwarden:'Vaultwarden'};
  const labels={ok:'Available',unavailable:'Unavailable',not_initialized:'Not initialized',running:'Running',offline:'Offline',degraded:'Needs attention'};
  diagnostics.innerHTML=`<div class="home-stats"><div><div class="home-stat">${Number.isFinite(data.memory?.rss_bytes)?`${Math.round(data.memory.rss_bytes/1024/1024)} MB`:'Unavailable'}</div><small>Exodus process memory</small></div><div><div class="home-stat">${formatBytes(data.disk?.free_bytes)}</div><small>Free on data volume</small></div></div><p class="home-muted">Memory is this app process only. Disk space is from the filesystem holding Exodus data.</p><ul class="home-list home-diagnostics-list">${Object.entries(data.databases||{}).map(([id,value])=>`<li><div class="home-row"><strong>${esc(names[id]||id)}</strong><span>${esc(labels[value.status]||'Unknown')}</span></div><small>${esc(value.detail||'')}${id==='vaultwarden'?' Device sync is not checked here.':''}</small></li>`).join('')}</ul><p class="home-muted">Checked ${esc(new Date(data.checked_at).toLocaleTimeString())}. Refresh for a new reading.</p>`;
 }catch(e){if(current())diagnostics.innerHTML=empty('System diagnostics are unavailable. Use Refresh to try again.');}})();
 const teamJob=(async()=>{try{
  const data=await api('/api/home/team');if(!teamCurrent())return;
  renderWidget(team,`<label><input id="home-presence-share" type="checkbox" ${profile.share_presence?'checked':''}>Share my presence with this workspace</label><p class="home-muted">Only opted-in accounts appear. Online means recorded activity in the last 90 seconds; availability is self-reported.</p><ul class="home-list">${data.people.map(p=>`<li>${p.online?'●':'○'} ${esc(p.name)} <small>${p.online?'Online':'Offline'} · ${esc(p.status)}</small></li>`).join('')||empty('No shared presence yet.')}</ul><h3>Shared updates</h3><ul class="home-list">${data.activity.map(a=>`<li>${esc(a.body)}<small>${esc(a.owner)} · ${esc(new Date(a.created*1000).toLocaleString())}</small></li>`).join('')||empty('No announcements yet. Private work is not automatically shared.')}</ul><details><summary>Post an announcement</summary><form id="home-announcement-form" class="home-form"><textarea name="body" aria-label="Shared announcement" maxlength="2000" required></textarea><p class="home-muted">Visible to signed-in members of this Exodus installation.</p><button>Post to workspace</button></form></details>`);
  $('home-presence-share').onchange=()=>action(null,async()=>{await patch({share_presence:$('home-presence-share').checked});await post('/api/home/presence',{});WorkspaceEvents.publish('team');});
  $('home-announcement-form').onsubmit=e=>{e.preventDefault();action(e.target.querySelector('button'),async()=>{await post('/api/home/announcements',Object.fromEntries(new FormData(e.target)));e.target.reset();WorkspaceEvents.publish('team');});};
 }catch(e){if(teamCurrent()&&!team.querySelector('form'))team.innerHTML=empty('Team updates could not be loaded.');}})();
 await Promise.all([systemJob,teamJob]);
}
async function loadWeather(w){const current=beginResponse(w);renderWidget(w,'<div id="home-weather-value"></div>'+`<details><summary>Weather settings</summary><form id="home-weather-form" class="home-form"><input name="city" aria-label="Weather city" maxlength="100" placeholder="City" value="${esc(profile.city||'')}"><label><input name="enabled" type="checkbox" ${profile.weather_enabled?'checked':''}>Enable online weather</label><p class="home-muted">Sends your city to Open-Meteo. No precise device location is requested. The free API is for noncommercial use; business deployments need an appropriate weather service plan.</p><a href="https://open-meteo.com/en/terms" target="_blank" rel="noopener noreferrer">Provider terms</a><button>Save weather settings</button></form></details>`);$('home-weather-form').onsubmit=e=>{e.preventDefault();action(e.target.querySelector('button'),async()=>{await patch({city:e.target.elements.city.value,weather_enabled:e.target.elements.enabled.checked});await loadWeather(w);});};if(!profile.weather_enabled){$('home-weather-value').innerHTML=empty('Weather is off. Your location stays private.');return;}const data=await api('/api/home/weather');if(!current())return;$('home-weather-value').innerHTML=data.configured?`<div class="home-stat">${esc(data.current.temperature_2m)}${esc(data.units.temperature_2m)}</div><p>${esc(data.place)}</p><p class="home-muted">As of ${esc(data.current.time)} · <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo</a></p>`:empty('Set a city to see current weather.');}
async function searchEmail(q,options){
 const {accounts=[]}=await api('/api/email/accounts',options);
 const results=await Promise.all(accounts.filter(a=>a.enabled!==false).map(async a=>{
   const result=await api('/api/email/search?'+new URLSearchParams({local_only:'true',q,limit:'10',account_id:a.id}),options);
   if(result.error)throw Error('Some email accounts could not be searched.');
   return (result.emails||[]).map(e=>({...e,account_id:a.id}));
 }));return {emails:results.flat().slice(0,30)};
}
async function searchAll(e){e.preventDefault();searchController?.abort();searchController=new AbortController();const q=$('home-search').value.trim();const box=$('home-search-results');box.textContent='Searching…';const options={signal:searchController.signal};const jobs=[['Workspace',api('/api/home/search?q='+encodeURIComponent(q),options)],['Email',searchEmail(q,options)],['Contacts',api('/api/contacts/search?q='+encodeURIComponent(q),options)]];const result=await Promise.allSettled(jobs.map(([,promise])=>promise));if(options.signal.aborted)return;box.innerHTML='';result.forEach((r,i)=>{const section=document.createElement('section');section.innerHTML=`<h3>${jobs[i][0]}</h3>`;box.append(section);if(r.status==='rejected'){section.insertAdjacentHTML('beforeend',empty(i===2?'Contacts unavailable for this account or not connected.':r.reason.message));return;}const rows=i===0?r.value.results:i===1?r.value.emails||[]:r.value.results||[];section.insertAdjacentHTML('beforeend',rows.length?'<ul class="home-list"></ul>':empty('No matching results.'));rows.forEach(row=>{const li=document.createElement('li'),b=document.createElement('button');b.className='home-link';b.textContent=i===0?`${row.title} · ${row.kind}`:i===1?row.subject:row.name;b.onclick=()=>i===0?launch(row.kind,row.id):i===1?launch('email',row):launch('settings');li.append(b);if(i===2){b.disabled=true;li.append(document.createTextNode(' · '+(row.emails||[]).map(x=>typeof x==='string'?x:x.value||x.email||'').join(', ')));}section.querySelector('ul').append(li);});});const note=document.createElement('p');note.className='home-muted';note.textContent='Email search uses the local cache. Contacts follow the existing account permissions. No semantic/AI search is used.';box.append(note);}
async function init(){
 try {const data=await api('/api/home/profile');profile=data.profile;owner=data.owner;let storage,recoveryId;try{storage=window.localStorage;recoveryId=window.sessionStorage.getItem('exodus-scratchpad-window');if(!recoveryId){recoveryId=crypto.randomUUID();window.sessionStorage.setItem('exodus-scratchpad-window',recoveryId);}}catch{storage=undefined;recoveryId=crypto.randomUUID();}scratchpad=createScratchpad({owner,storage,recoveryId,request:(path,options={})=>api(path,{...options,body:options.body?JSON.stringify(options.body):undefined})});renderShell();enforceMode();
 let wasDocumentOpen=document.body.classList.contains('doc-view'), returnToHome=false;
 new MutationObserver(()=>{const open=document.body.classList.contains('doc-view');if(open&&!wasDocumentOpen&&!home.hidden){returnToHome=true;hideHome();}if(!open&&wasDocumentOpen&&returnToHome){returnToHome=false;showHome();}wasDocumentOpen=open;}).observe(document.body,{attributes:true,attributeFilter:['class']});
 const observer=new MutationObserver(()=>{if(profile.mode==='ai-free')enforceMode();installSettings();});observer.observe(document.body,{childList:true,subtree:true});
 homeUpdates=createHomeUpdates({subscribe:WorkspaceEvents.subscribe,refresh:id=>loadWidgets(id),refreshProfile,allWidgets:Object.keys(widgetNames)});
 const dedicated=location.pathname!=='/'||!!location.hash;
 if(profile.mode==='ai-free'||!dedicated||!profile.mode)showHome();else hideHome();
 let shownDay=dayKey(new Date());timers.push(setInterval(()=>{greeting();tickFocus();const today=dayKey(new Date());if(today!==shownDay){shownDay=today;['calendar','notes','focus'].forEach(topic=>homeUpdates.enqueue(topic));}},1000));
 WorkspaceEvents.start();
 if(profile.share_presence)post('/api/home/presence',{}).catch(()=>{});
 window.addEventListener('focus',()=>{if(profile.share_presence&&!document.hidden)post('/api/home/presence',{}).catch(()=>{});});
 window.addEventListener('beforeunload',e=>{const draft=scratchpad.getState();if((draft.dirty||draft.pending||draft.conflict)&&!draft.recoveryAvailable){e.preventDefault();e.returnValue='';}});

 }catch(e){const failure=document.createElement('main');failure.id='workspace-home';failure.innerHTML='<h1>Home could not load</h1><p>Your workspace mode could not be verified. Please reload to try again.</p><button>Reload</button>';failure.querySelector('button').onclick=()=>location.reload();document.body.append(failure);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
