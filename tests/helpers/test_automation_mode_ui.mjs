import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../../static/js/tasks.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('function startNotificationPolling()'),source.indexOf('const tasksModule ='));
for(const mode of ['full','ai-free']){
 const timers=[],cancelled=[];let polls=0;
 const context=vm.createContext({
  document:{documentElement:{dataset:{workspaceMode:mode}}},
  _notifInterval:null,_pollTaskNotifications:()=>{polls++;},
  setTimeout:(fn,ms)=>{timers.push({fn,ms});return 1;},
  setInterval:(fn,ms)=>{timers.push({fn,ms});return 2;},
  clearInterval:id=>cancelled.push(id),
 });
 vm.runInContext(code+'\nstartNotificationPolling();startNotificationPolling();',context);
 assert.equal(timers.length,2,mode+' starts one listener');
 timers[0].fn();timers[1].fn();
 assert.equal(polls,2,mode+' receives ordinary Automation notices');
 vm.runInContext('stopNotificationPolling()',context);
 assert.deepEqual(cancelled,[2]);
}
assert.match(source,/Jobs <span id="tasks-tab-count"/);
assert.match(source,/Ongoing Jobs/);
console.log('Automations: Jobs labels and ordinary notification listener work in both modes');
