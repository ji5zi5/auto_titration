const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Execute the actual navigation bootstrap, without starting backend connections.
const source = fs.readFileSync('website/app.js', 'utf8').split('const LOCAL_COLLECTOR_BACKEND')[0];
function load(href, { narrow = false, native = false } = {}) {
  const links = new Map(['viewFullLink', 'viewCompactLink'].map((id) => [id, {
    setAttribute(name, value) { this[name] = value; },
  }]));
  const events = new Map();
  const classes = new Set();
  const window = {
    location: new URL(href),
    matchMedia: () => ({ matches: narrow }),
    addEventListener: (name, callback) => events.set(name, callback),
  };
  if (native) window.AutoTitrationAndroid = {};
  const context = vm.createContext({ URL, window, document: {
    getElementById: (id) => links.get(id),
    body: { classList: { add: (name) => classes.add(name) } },
  } });
  vm.runInContext(source, context);
  events.get('DOMContentLoaded')();
  return { links, window, events, remote: classes.has('remote-control-mode'), controller: vm.runInContext('remoteControlMode', context) };
}

for (const narrow of [false, true]) {
  for (const query of ['', '?remote=0', '?remote=1', '?remote=1&remote=0']) {
    const initial = `https://100.64.0.2:8765/dashboard${query}${query ? '&' : '?'}backend=%2Fproxy&tag=a&tag=b&label=%ED%95%9C%EA%B8%80#roi`;
    const app = load(initial, { narrow });
    assert.equal(app.remote, !query.includes('remote=0') && (query.includes('remote=1') || narrow));
    for (const [id, mode] of [['viewFullLink', '0'], ['viewCompactLink', '1']]) {
      const link = app.links.get(id);
      const url = new URL(link.href);
      assert.equal(url.origin, 'https://100.64.0.2:8765');
      assert.equal(url.pathname, '/dashboard');
      assert.equal(url.hash, '#roi');
      assert.equal(url.searchParams.get('backend'), '/proxy');
      assert.equal(url.searchParams.get('label'), '한글');
      assert.deepEqual(url.searchParams.getAll('tag'), ['a', 'b']);
      assert.deepEqual(url.searchParams.getAll('remote'), [mode]);
      assert.equal(link.hidden, false);
      assert.equal(link['aria-current'], app.remote === (mode === '1') ? 'page' : 'false');
      assert.equal(load(link.href, { narrow }).remote, mode === '1');
    }
    const full = load(app.links.get('viewFullLink').href, { narrow });
    const compact = load(full.links.get('viewCompactLink').href, { narrow });
    assert.equal(compact.remote, true);
    assert.equal(load(compact.links.get('viewFullLink').href, { narrow }).remote, false);
    app.window.location.hash = '#results';
    app.events.get('hashchange')();
    assert.equal(new URL(app.links.get('viewCompactLink').href).hash, '#results');
  }
}
const withoutLinks = load('https://example.test/');
withoutLinks.links.clear();
assert.doesNotThrow(() => withoutLinks.events.get('hashchange')());

for (const narrow of [false, true]) {
  const native = load('https://example.test/?remote=1#roi', { narrow, native: true });
  assert.equal(native.remote, false);
  for (const link of native.links.values()) {
    assert.equal(link.hidden, true);
    assert.equal(link.href, undefined);
  }
}
console.log('view navigation: query/hash preservation, round trips, explicit modes, native exclusion OK');

const fullPhone = load('https://example.test/?remote=0', { narrow: true });
assert.equal(fullPhone.remote, false);
assert.equal(fullPhone.controller, true, 'full phone must retain server-owned settings');
const desktopCompact = load('https://example.test/?remote=1');
const desktopReturn = load(desktopCompact.links.get('viewFullLink').href);
assert.equal(desktopReturn.remote, false);
assert.equal(desktopReturn.controller, true, 'full return must not become a settings writer');
assert.equal(load('https://example.test/').controller, false, 'notebook full remains settings owner');
