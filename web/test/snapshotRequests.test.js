import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/utils/api.js', import.meta.url), 'utf8')
  .replace("import request from './request';", 'const request = (...args) => globalThis.snapshotRequest(...args);');
const { getMarketSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('duplicate and refresh requests share the pending computation, then permit a fresh request', async () => {
  const calls = []; let resolve;
  globalThis.snapshotRequest = config => { calls.push(config); return new Promise(done => { resolve = done; }); };
  const first = getMarketSnapshot('cn', 'all', '2026-10-30', 'qfq');
  const duplicate = getMarketSnapshot('cn', 'all', '2026-10-30', 'qfq', true);
  assert.equal(first, duplicate);
  assert.equal(calls.length, 1);
  resolve({ data: [{ symbol: 'TEST.SZ' }] });
  await first;
  const fresh = getMarketSnapshot('cn', 'all', '2026-10-30', 'qfq', true);
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /refresh=1/);
  resolve({ data: [] }); await fresh;
});

test('different dates remain separate and rejected requests can be retried', async () => {
  const calls = [];
  globalThis.snapshotRequest = config => { calls.push(config); return Promise.reject(new Error('unavailable')); };
  await Promise.allSettled([
    getMarketSnapshot('cn', 'all', '2026-10-30', 'qfq'),
    getMarketSnapshot('cn', 'all', '2026-10-29', 'qfq'),
  ]);
  assert.equal(calls.length, 2);
  globalThis.snapshotRequest = config => { calls.push(config); return Promise.resolve({ data: [] }); };
  await getMarketSnapshot('cn', 'all', '2026-10-30', 'qfq');
  assert.equal(calls.length, 3);
});
