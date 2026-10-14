import test from 'node:test';
import assert from 'node:assert/strict';

import { classifyLogLevel, sanitizeLogText, splitLogLine } from '../../../autodrive_console/web/platform/log-format.js';

test('sanitizeLogText removes terminal escape sequences without changing log meaning', () => {
  assert.equal(
    sanitizeLogText('\u001b[31m[ERROR]\u001b[0m motor timeout\r\n'),
    '[ERROR] motor timeout',
  );
});

test('classifyLogLevel identifies an error before a non-semantic word in the same line', () => {
  assert.equal(classifyLogLevel('[ERROR] warning cache unavailable'), 'error');
  assert.equal(classifyLogLevel('[WARN] battery low'), 'warning');
  assert.equal(classifyLogLevel('[INFO] navigation ready'), 'info');
  assert.equal(classifyLogLevel('plain supervisor output'), 'plain');
});

test('splitLogLine exposes timestamp and level while preserving the message text', () => {
  assert.deepEqual(
    splitLogLine('2026-09-29 13:46:55 [WARN] lidar frame delayed'),
    { timestamp: '2026-09-29 13:46:55', level: 'WARN', message: 'lidar frame delayed', tone: 'warning' },
  );
});
