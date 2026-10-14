import test from 'node:test';
import assert from 'node:assert/strict';

const moduleUrl = '../../autodrive_console/web/software-inventory-export.js';
const generatedAt = new Date('2026-10-10T09:12:21Z');

function documentFixture() {
  return { createElement() {
    const canvas = { width: 0, height: 0, text: [] };
    const context = {
      font: '20px sans-serif', textAlign: 'left',
      measureText(value) { return { width: Array.from(value).length * Number(this.font.match(/(\d+)px/)[1]) * .6 }; },
      fillText(value, x, y) { canvas.text.push({ value, x, y, width: this.measureText(value).width }); },
      fillRect() {}, beginPath() {}, roundRect() {}, fill() {}, stroke() {},
      moveTo() {}, lineTo() {},
    };
    canvas.getContext = () => context;
    return canvas;
  } };
}

function snapshot(count = 20) {
  return {
    vehicle: { vehicle_number: '12', vin: 'QA-CHASSIS-001', model: 'R6S', project: '测试项目', location: '测试地点' },
    packages: Array.from({ length: count }, (_, index) => ({
      package_name: `ry-package-${index}`, package_filename: `ry-package-${index}_1.2.3_amd64.deb`,
      version: '1.2.3', architecture: 'amd64', maintainer: 'Hidden person', description: 'Hidden note',
    })),
  };
}

test('export wraps uninterrupted identifiers and Chinese without dropping characters', async () => {
  const { wrapInventoryText } = await import(moduleUrl);
  const context = documentFixture().createElement('canvas').getContext('2d');
  for (const value of ['ry-' + 'verylong'.repeat(12) + '_amd64.deb', '测试项目'.repeat(20)]) {
    const lines = wrapInventoryText(context, value, 140);
    assert.ok(lines.length > 1);
    assert.equal(lines.join(''), value);
    assert.ok(lines.every(line => context.measureText(line).width <= 140));
  }
});

test('export includes all package facts and Beijing time while omitting removed metadata', async () => {
  const { createInventoryExportPages } = await import(moduleUrl);
  const pages = [...createInventoryExportPages({ document: documentFixture(), snapshot: snapshot(), generatedAt })];
  const text = pages.flatMap(page => page.text.map(item => item.value));
  for (let index = 0; index < 20; index++) {
    assert.equal(text.filter(value => value === `ry-package-${index}`).length, 1);
    assert.equal(text.filter(value => value === `ry-package-${index}_1.2.3_amd64.deb`).length, 1);
  }
  assert.ok(text.some(value => value.includes('2026-10-10 17:12:21')));
  for (const value of ['维护人', '说明', 'Hidden person', 'Hidden note']) assert.ok(!text.includes(value));
  assert.equal(pages.length, 1);
});

test('pagination keeps every row once and each page within the image height limit', async () => {
  const { createInventoryExportPages } = await import(moduleUrl);
  const pages = [...createInventoryExportPages({ document: documentFixture(), snapshot: snapshot(90), generatedAt, maxHeight: 1800 })];
  assert.ok(pages.length > 1);
  const text = pages.flatMap(page => page.text.map(item => item.value));
  for (let index = 0; index < 90; index++) assert.equal(text.filter(value => value === `ry-package-${index}`).length, 1);
  for (const page of pages) {
    assert.ok(page.height <= 1800);
    assert.ok(page.text.every(item => item.y > 0 && item.y < page.height));
  }
});

test('long vehicle fields expand the header and an empty inventory has an explicit empty state', async () => {
  const { createInventoryExportPages } = await import(moduleUrl);
  const data = snapshot(0);
  data.vehicle.project = '项目'.repeat(48);
  data.vehicle.vin = 'LONG-'.repeat(12);
  const [page] = createInventoryExportPages({ document: documentFixture(), snapshot: data, generatedAt });
  assert.ok(page.text.some(item => item.value.includes('未发现已安装')));
  assert.ok(page.text.every(item => item.x >= 0 && item.x + item.width < page.width));
  assert.ok(page.text.every(item => item.y < page.height));
});
