// Exercise the real shared service launcher without a vault, model or credentials.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync('static/js/settings/vaultwarden.js', 'utf8').replace('export function ', 'function ');
const config = {
  vault_url: 'http://localhost:8092/vault/', launch_path: '/vault',
  access_mode: 'local', registration_allowed: false, embedded: false,
  admin_enabled: true,
  start_command: 'docker compose -p sovereign-hub up -d --no-deps vaultwarden vaultwarden-gateway',
};
const running = {status: 'running', reachable: true, checked_at: '2026-10-01T12:00:00Z', sync: {status: 'unknown'}};
function node() {
  return {
    hidden: false, textContent: '', href: undefined, target: '_self', style: {}, attributes: {}, listeners: {},
    setAttribute(k, v) { this.attributes[k] = v; },
    removeAttribute(k) { delete this[k]; },
    addEventListener(k, v) { this.listeners[k] = v; },
    removeEventListener(k, v) { if (this.listeners[k] === v) delete this.listeners[k]; },
    querySelector() { return this.code ||= node(); },
  };
}
function fixture(options = {}) {
  const elements = new Map();
  const body = {querySelector(selector) { if (!elements.has(selector)) elements.set(selector, node()); return elements.get(selector); }};
  const calls = [], timers = new Map();
  let cfg = options.config || config, health = options.health || running, failure = false, deferred = false;
  const context = vm.createContext({body, URL, Date, AbortController, console,
    window: {location: {hostname: options.hostname || 'localhost'}},
    setTimeout: fn => {const id = Symbol(); timers.set(id, fn); return id;}, clearTimeout: id => timers.delete(id),
    fetch: async (url, init) => {
      calls.push({url, init});
      if (deferred) return new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
      if (failure) return {ok: false, status: failure, json: async () => ({detail: 'secret not for display'})};
      return {ok: true, json: async () => url.endsWith('/config') ? cfg : health};
    },
  });
  vm.runInContext(source, context);
  const close = vm.runInContext('initVaultwardenDetails(body)', context);
  return {close, elements, calls, timers,
    element: id => body.querySelector('#vaultwarden-' + id),
    set: next => {if (next.config) cfg = next.config; if (next.health) health = next.health; if ('failure' in next) failure = next.failure; if ('deferred' in next) deferred = next.deferred;},
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

const f = fixture(); await settle();
assert.equal(f.calls.length, 2);
assert(f.calls.every(({init}) => init.credentials === 'same-origin' && init.cache === 'no-store' && !init.method));
assert.equal(f.element('launch').href, '/vault');
assert.equal(f.element('launch').hidden, false);
assert.equal(f.element('launch').target, '_self', 'Preserve the shared tab-opening preference');
assert.match(f.element('status').textContent, /running/);
assert.match(f.element('sync').textContent, /inside the vault/);
assert.match(f.element('registration').textContent, /disabled/);
assert.equal(f.element('diagnostics').hidden, true);
assert.match(f.element('checked').textContent, /Last checked:/);
assert.equal(f.timers.size, 0, 'Clear timeout after successful completion');

f.set({health: {...running, status: 'offline', reachable: false}});
await f.element('refresh').listeners.click();
assert.equal(f.element('launch').hidden, true);
assert.equal(f.element('launch').href, undefined, 'An old reachable result must not leave an active URL');
assert.match(f.element('status').textContent, /offline/);
assert.equal(f.element('diagnostics').hidden, false);
assert.equal(f.element('start-command').textContent, config.start_command);
f.set({health: {...running, status: 'degraded'}});
await f.element('refresh').listeners.click();
assert.match(f.element('status').textContent, /not ready/);
assert.equal(f.element('launch').hidden, true);
f.set({failure: 401}); await f.element('refresh').listeners.click();
assert.match(f.element('status').textContent, /Sign in/);
assert(!f.element('status').textContent.includes('secret'));
assert.equal(f.element('refresh').disabled, false);
f.close(); assert.equal(f.element('refresh').listeners.click, undefined);

for (const [hostname, overrides, allowed] of [
  ['192.168.1.3', {}, false],
  ['exodus.example', {access_mode: 'https', vault_url: 'https://vault.example/vault/'}, true],
  ['localhost', {access_mode: 'https', vault_url: 'http://vault.example/vault/'}, false],
  ['localhost', {vault_url: 'javascript:alert(1)'}, false],
  ['localhost', {vault_url: 'http://user:password@localhost:8092/vault/'}, false],
  ['localhost', {launch_path: '//untrusted.example'}, false],
  ['127.0.0.1', {}, true],
]) {
  const check = fixture({hostname, config: {...config, ...overrides}}); await settle();
  assert.equal(check.element('launch').hidden, !allowed, hostname + JSON.stringify(overrides));
  assert.equal(check.element('address').hidden, !allowed, 'Do not render unsafe URLs or URL credentials');
  if (!allowed) assert.equal(check.element('address').querySelector('code').textContent, '');
  check.close();
}

const aborted = fixture(); await settle(); aborted.set({deferred: true});
const pending = aborted.element('refresh').listeners.click();
const callsBefore = aborted.calls.length;
await aborted.element('refresh').listeners.click();
assert.equal(aborted.calls.length, callsBefore, 'Ignore duplicate clicks while checking');
const statusBeforeClose = aborted.element('status').textContent;
aborted.close(); await pending;
assert(aborted.calls.slice(-2).every(({init}) => init.signal.aborted));
assert.equal(aborted.element('status').textContent, statusBeforeClose, 'No detached UI updates');
assert.equal(aborted.timers.size, 0);

const timeout = fixture(); await settle(); timeout.set({deferred: true});
const timed = timeout.element('refresh').listeners.click();
[...timeout.timers.values()][0](); await timed;
assert.match(timeout.element('status').textContent, /timed out/);
assert.equal(timeout.element('launch').hidden, true);
assert.equal(timeout.element('refresh').disabled, false);
timeout.close();

const shared = readFileSync('static/js/settings/localServices.js', 'utf8');
const home = readFileSync('static/js/home.js', 'utf8');
assert.match(shared, /service === 'vaultwarden' \? initVaultwardenDetails\(body\)/);
assert.match(home, /openLocalServices\(kind==='vault'\?'vaultwarden'/, 'Home must share the same launcher');
console.log('PASS: Vaultwarden status, protected launch, closed registration, sync honesty, offline/degraded diagnosis, tab preference, URL safety, auth failure, request cancellation, duplicate clicks, timeout and shared Home launcher.');
