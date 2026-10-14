import assert from 'node:assert/strict';
import test from 'node:test';
import { createRelocalizationConfigPicker } from '../src/relocalizationConfigPicker.js';

class Element {
  constructor() { this.hidden = false; this.disabled = false; this.value = ''; this.children = []; this.listeners = {}; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  focus() { this.focused = true; }
  setAttribute() {}
  async fire(name) { return this.listeners[name]?.(); }
}
function fixture(request) {
  const ids = ['Mode', 'Manual', 'Selected', 'Browse', 'Browser', 'Directory', 'Up', 'Root', 'Close', 'Entries', 'Message'];
  const elements = Object.fromEntries(ids.map(id => [`relocalizationConfig${id}`, new Element()]));
  const root = { querySelector: id => elements[id.slice(1)], ownerDocument: { createElement: () => new Element() } };
  let changes = 0;
  const picker = createRelocalizationConfigPicker({ root, request, onChange: () => changes++ });
  picker.setEditable(true);
  return { picker, elements, changed: () => changes };
}
const listing = { root: '/opt/ry/config/localization', path: '/opt/ry/config/localization', parent: null,
  directories: [{ name: 'config', path: '/opt/ry/config/localization/config' }],
  files: [{ name: 'floor.yaml', path: '/opt/ry/config/localization/floor.yaml' }] };
const pose = { x: 1, y: 2, yaw: .3 };
const flush = () => new Promise(resolve => setImmediate(resolve));

test('automatic is the default; a manual file applies once and reset discards it', async () => {
  const { picker, elements } = fixture(async () => listing);
  assert.deepEqual(picker.payload(pose), pose);
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  assert.equal(picker.ready(), false);
  assert.throws(() => picker.payload(pose), /选择/);
  await elements.relocalizationConfigEntries.children[1].fire('click');
  assert.deepEqual(picker.payload(pose), { ...pose, config_path: listing.files[0].path });
  assert.equal(elements.relocalizationConfigBrowser.hidden, true);
  assert.match(picker.summary(), /floor.yaml/);
  picker.reset();
  assert.deepEqual(picker.payload(pose), pose);
  assert.equal(elements.relocalizationConfigMode.value, 'auto');
});

test('only user configuration changes mark a new draft; automatic reset is distinguished',async()=>{
  const {picker,elements}=fixture(async()=>listing);
  const changes=[];
  const root={querySelector:id=>elements[id.slice(1)],ownerDocument:{createElement:()=>new Element()}};
  const tracked=createRelocalizationConfigPicker({root,request:async()=>listing,onChange:user=>changes.push(user)});
  tracked.setEditable(true);
  elements.relocalizationConfigMode.value='manual';await elements.relocalizationConfigMode.fire('change');
  await elements.relocalizationConfigEntries.children[1].fire('click');
  tracked.reset();
  assert.deepEqual(changes,[true,true,false]);
});

test('late browsing responses cannot reopen the browser after resetting to automatic', async () => {
  let resolve;
  const { picker, elements } = fixture(() => new Promise(done => { resolve = done; }));
  elements.relocalizationConfigMode.value = 'manual';
  const pending = elements.relocalizationConfigMode.fire('change');
  await flush();
  picker.reset();
  resolve(listing);
  await pending;
  assert.equal(elements.relocalizationConfigBrowser.hidden, true);
  assert.deepEqual(picker.payload(pose), pose);
});

test('browse failure is visible and switching back to automatic remains usable', async () => {
  const { picker, elements } = fixture(async () => { throw Error('目录不可读取'); });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  assert.match(elements.relocalizationConfigMessage.textContent, /目录不可读取/);
  assert.equal(picker.ready(), false);
  elements.relocalizationConfigMode.value = 'auto';
  await elements.relocalizationConfigMode.fire('change');
  assert.deepEqual(picker.payload(pose), pose);
});

test('a pending submit locks selection and invalidates a browser request', async () => {
  let resolve;
  const { picker, elements } = fixture(() => new Promise(done => { resolve = done; }));
  elements.relocalizationConfigMode.value = 'manual';
  const pending = elements.relocalizationConfigMode.fire('change');
  await flush();
  picker.setEditable(false);
  resolve(listing);
  await pending;
  assert.equal(elements.relocalizationConfigMode.disabled, true);
  assert.equal(elements.relocalizationConfigBrowse.disabled, true);
  assert.equal(elements.relocalizationConfigBrowser.hidden, true);
});

test('directory navigation sends encoded paths and can return to the root', async () => {
  const calls = [];
  const nested = { ...listing, path: listing.root + '/config', parent: listing.root, directories: [] };
  const { elements } = fixture(async (url) => {
    calls.push(url);
    const path = new URL(url, 'http://localhost').searchParams.get('path');
    return path === nested.path ? nested : listing;
  });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await elements.relocalizationConfigEntries.children[0].fire('click');
  assert.equal(elements.relocalizationConfigDirectory.textContent, nested.path);
  assert.equal(elements.relocalizationConfigUp.disabled, false);
  assert.match(calls[1], /path=%2Fopt%2Fry%2Fconfig%2Flocalization%2Fconfig/);
  await elements.relocalizationConfigUp.fire('click');
  assert.equal(elements.relocalizationConfigDirectory.textContent, listing.root);
  assert.equal(elements.relocalizationConfigUp.disabled, true);
});

test('repeated open while loading shares one request and still renders the listing', async () => {
  const calls = [];
  let resolve;
  const { elements } = fixture(url => {
    calls.push(url);
    return new Promise(done => { resolve = done; });
  });
  elements.relocalizationConfigMode.value = 'manual';
  const first = elements.relocalizationConfigMode.fire('change');
  const second = elements.relocalizationConfigBrowse.fire('click');
  await flush();
  assert.equal(calls.length, 1);
  resolve({ ...listing, directories: [] });
  await Promise.all([first, second]);
  assert.equal(elements.relocalizationConfigEntries.children[0].textContent, 'floor.yaml');
});

test('child prefetch is reused on navigation and returning to a recent parent needs no network', async () => {
  const calls = [];
  let childDone;
  const nested = { ...listing, path: listing.root + '/config', parent: listing.root, directories: [] };
  const { elements, picker } = fixture((url, options) => {
    calls.push({ url, options });
    return calls.length === 1 ? Promise.resolve(listing) : new Promise(done => { childDone = done; });
  });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await flush();
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /config$/);
  assert.equal(picker.ready(), false);
  const navigation = elements.relocalizationConfigEntries.children[0].fire('click');
  await flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.signal.aborted, false);
  childDone(nested);
  await navigation;
  await elements.relocalizationConfigUp.fire('click');
  assert.equal(calls.length, 2);
  assert.equal(elements.relocalizationConfigDirectory.textContent, listing.root);
  await elements.relocalizationConfigClose.fire('click');
  await elements.relocalizationConfigBrowse.fire('click');
  assert.equal(calls.length, 2);
  assert.equal(elements.relocalizationConfigEntries.children[1].textContent, 'floor.yaml');
});

test('old directory listings expire so newly added files appear on reopening', async () => {
  let calls = 0;
  const now = Date.now();
  const { elements } = fixture(async () => ({ ...listing, directories: [], files: [
    { name: ++calls === 1 ? 'floor.yaml' : 'new-floor.yaml', path: listing.root + '/floor.yaml' },
  ] }));
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await elements.relocalizationConfigClose.fire('click');
  const original = Date.now;
  try {
    Date.now = () => now + 60_000;
    await elements.relocalizationConfigBrowse.fire('click');
  } finally { Date.now = original; }
  assert.equal(calls, 2);
  assert.equal(elements.relocalizationConfigEntries.children[0].textContent, 'new-floor.yaml');
});

test('reset aborts directory reads and a late response cannot seed the next operation cache', async () => {
  const calls = [];
  const { elements, picker } = fixture((url, options) => new Promise(resolve => calls.push({ options, resolve })));
  elements.relocalizationConfigMode.value = 'manual';
  const oldRead = elements.relocalizationConfigMode.fire('change');
  await flush();
  picker.reset();
  assert.equal(calls[0].options.signal.aborted, true);
  calls[0].resolve({ ...listing, directories: [], files: [{ name: 'stale.yaml', path: listing.root + '/stale.yaml' }] });
  await oldRead;
  elements.relocalizationConfigMode.value = 'manual';
  const nextRead = elements.relocalizationConfigMode.fire('change');
  await flush();
  assert.equal(calls.length, 2);
  calls[1].resolve({ ...listing, directories: [] });
  await nextRead;
  assert.equal(elements.relocalizationConfigEntries.children[0].textContent, 'floor.yaml');
  assert.equal(picker.ready(), false);
});

test('prefetch only reads a bounded immediate next level with one background request at a time', async () => {
  let calls = 0, active = 0, maximum = 0;
  const pending = [];
  const { elements, picker } = fixture(async url => {
    calls++;
    if (calls === 1) return { ...listing, directories: Array.from({ length: 30 }, (_, i) =>
      ({ name: `d${i}`, path: `${listing.root}/d${i}` })) };
    active++; maximum = Math.max(maximum, active);
    return new Promise(done => pending.push(() => {
      active--;
      done({ ...listing, path: new URL(url, 'http://localhost').searchParams.get('path'),
        directories: [{ name: 'deeper', path: listing.root + '/not-requested' }] });
    }));
  });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await flush();
  for (let i = 0; i < 30 && pending.length; i++) { pending.shift()(); await flush(); }
  assert.equal(maximum, 1);
  assert.ok(calls > 1 && calls <= 9, `unbounded prefetch: ${calls} requests`);
  assert.equal(picker.ready(), false);
  assert.equal(elements.relocalizationConfigDirectory.textContent, listing.root);
});

test('moving elsewhere aborts a speculative read and its late result cannot replace the chosen directory', async () => {
  let slow;
  const other = { name: 'other', path: listing.root + '/other' };
  const { elements } = fixture((url, options) => {
    const path = new URL(url, 'http://localhost').searchParams.get('path');
    if (!path) return Promise.resolve({ ...listing, directories: [...listing.directories, other] });
    if (path.endsWith('/config')) return new Promise(resolve => { slow = { resolve, options }; });
    return Promise.resolve({ ...listing, path: other.path, directories: [] });
  });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await flush();
  await elements.relocalizationConfigEntries.children[1].fire('click');
  assert.equal(slow.options.signal.aborted, true);
  slow.resolve({ ...listing, path: listing.root + '/config', directories: [] });
  await flush();
  assert.equal(elements.relocalizationConfigDirectory.textContent, other.path);
});

test('a stalled read times out visibly and can be retried without leaving manual mode', async () => {
  let expire;
  let calls = 0;
  const originalTimer = globalThis.setTimeout;
  const { elements, picker } = fixture((url, { signal }) => {
    if (++calls > 1) return Promise.resolve({ ...listing, directories: [] });
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason)));
  });
  elements.relocalizationConfigMode.value = 'manual';
  let pending;
  try {
    globalThis.setTimeout = callback => { expire = callback; return 0; };
    pending = elements.relocalizationConfigMode.fire('change');
    await flush();
    expire();
    await pending;
  } finally { globalThis.setTimeout = originalTimer; }
  assert.match(elements.relocalizationConfigMessage.textContent, /超时/);
  assert.equal(elements.relocalizationConfigBrowse.disabled, false);
  assert.equal(picker.ready(), false);
  await elements.relocalizationConfigBrowse.fire('click');
  assert.equal(elements.relocalizationConfigEntries.children[0].textContent, 'floor.yaml');
});

test('a failed speculative read stops prefetch but leaves current files usable', async () => {
  let calls = 0;
  const { elements, picker } = fixture(async () => {
    if (++calls > 1) throw Error('network offline');
    return { ...listing, directories: [...listing.directories, { name: 'other', path: listing.root + '/other' }] };
  });
  elements.relocalizationConfigMode.value = 'manual';
  await elements.relocalizationConfigMode.fire('change');
  await flush();
  assert.equal(calls, 2);
  assert.equal(elements.relocalizationConfigMessage.textContent, '');
  await elements.relocalizationConfigEntries.children[2].fire('click');
  assert.deepEqual(picker.payload(pose), { ...pose, config_path: listing.root + '/floor.yaml' });
});
