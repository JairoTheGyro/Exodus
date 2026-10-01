import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = readFileSync('static/js/settings.js', 'utf8');
const helper = source.slice(source.indexOf('function bindEmailPortSecurity('), source.indexOf('async function initEmailAccountsSettings('));
for (const prefix of ['uf', 'eaf']) {
  const fields = {};
  for (const suffix of ['imap-port', 'imap-starttls', 'smtp-port', 'smtp-security']) {
    fields[`${prefix}-${suffix}`] = Object.assign(new EventTarget(), { value: '', checked: true });
  }
  const context = vm.createContext({ el: id => fields[id] });
  vm.runInContext(helper, context);
  const sync = vm.runInContext(`bindEmailPortSecurity('${prefix}')`, context);
  const field = suffix => fields[`${prefix}-${suffix}`];
  sync();
  assert.equal(field('imap-starttls').checked, false, 'Default 993 uses implicit TLS');
  assert.equal(field('smtp-security').value, 'ssl');
  for (const event of ['input', 'change']) {
    for (const port of [143, 993]) {
      field('imap-port').value = String(port);
      field('imap-port').dispatchEvent(new Event(event));
      assert.equal(field('imap-starttls').checked, port === 143);
    }
    for (const [port, security] of [[587, 'starttls'], [465, 'ssl']]) {
      field('smtp-port').value = String(port);
      field('smtp-port').dispatchEvent(new Event(event));
      assert.equal(field('smtp-security').value, security);
    }
  }
  field('imap-port').value = '1993';
  field('imap-starttls').checked = true;
  field('smtp-port').value = '1587';
  field('smtp-security').value = 'starttls';
  sync();
  assert.equal(field('imap-starttls').checked, true, 'Custom ports retain the chosen TLS transport');
  assert.equal(field('smtp-security').value, 'starttls');
}
console.log('Both Email forms: defaults, typed/selected standard ports, and custom TLS ports passed.');
