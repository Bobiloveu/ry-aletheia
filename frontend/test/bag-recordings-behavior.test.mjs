import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../autodrive_console/web/bag_recordings.js', import.meta.url), 'utf8');

function harness(failArchives = false) {
  const nodes = new Map();
  const element = () => ({ children: [], hidden: false, disabled: false, textContent: '',
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener() {}, showModal() {}, close() {},
  });
  const archive = { archive_id: 'a'.repeat(32), display_name: '窄通道避障', source: 'manual', label: '窄通道避障',
    started_at: '2026-10-15T09:28:25+08:00', total_size_bytes: 1024, compression: 'Zstd（文件级）', audit_status: 'passed' };
  const requests = [];
  const context = vm.createContext({ document: {
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
    createElement: element, addEventListener() {}, visibilityState: 'visible',
  }, window: { setInterval() { return 1; }, clearInterval() {}, addEventListener() {},
    confirm() { return true; }, alert() {}, location: {} },
    requestJson: async (url, options = {}) => {
      requests.push([url, options.method || 'GET']);
      if (url === '/api/bag-recordings' && failArchives) throw new Error('列表暂不可用');
      if (url === '/api/bag-recordings') return { archives: [archive] };
      if (url === '/api/bag-recordings/manual') return { manual: { state: 'recording', label: '现场录制', topic_count: 2, remaining_seconds: 60 } };
      return { archive, manifest: { audit: { status: 'passed' } } };
    },
  });
  vm.runInContext(source.replace(/^import .*\n/, ''), context);
  return { context, nodes, requests, archive };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('bag cards keep scene titles and timestamps distinct, with UUID-backed actions', async () => {
  const { context, nodes, requests, archive } = harness();
  await settle();
  const card = nodes.get('archiveList').children[0];
  assert.equal(card.children[0].children[0].textContent, '窄通道避障');
  assert.equal(card.children[0].children[1].textContent, '手动录制 · 2026-10-15 09:28:25');
  const [details, download, remove] = card.children[1].children;
  await details.onclick();
  assert.equal(nodes.get('detailTitle').textContent, '窄通道避障');
  download.onclick();
  assert.equal(context.window.location.href, `/api/bag-recordings/${archive.archive_id}/download`);
  await remove.onclick();
  assert.ok(requests.some(([url, method]) => url === `/api/bag-recordings/${archive.archive_id}` && method === 'DELETE'));
  assert.equal(vm.runInContext('formatStartedAt(null)', context), '开始时间未知');
});

test('an archive list failure still exposes the active manual recording and stop control', async () => {
  const { nodes } = harness(true);
  await settle();
  assert.equal(nodes.get('stopManualRecording').hidden, false);
  assert.match(nodes.get('manualRecordingSummary').textContent, /现场录制/);
  assert.match(nodes.get('archiveList').textContent, /列表暂不可用/);
});
