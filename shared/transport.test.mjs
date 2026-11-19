import test from 'node:test';
import assert from 'node:assert/strict';
import { createApi } from './api/client.mjs';
import { websocketUrl, parsePacket } from './websocket/protocol.mjs';

test('retry preserves request body and destination even when settings change', async () => {
  let base = 'http://pi.local:8001';
  const calls = [];
  const api = createApi(() => ({ base, token: 'test' }), async (url, options) => {
    calls.push({ url, body: options.body, token: options.headers.Authorization });
    base = 'http://other.local';
    if (calls.length === 1) throw new TypeError('response lost');
    return { ok: true, json: async () => ({ saved: true }) };
  });
  assert.deepEqual(await api('/api/commands', { method: 'POST', body: '{"request_id":"same"}' }), { saved: true });
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], calls[1]);
});

test('HTTP failures and GET network failures are not retried', async () => {
  let calls = 0;
  const api = createApi(() => ({ base: 'http://pi.local' }), async () => {
    calls++;
    return { ok: false, status: 409, json: async () => ({ detail: 'conflict' }) };
  });
  await assert.rejects(api('/api/commands', { body: '{}' }), { status: 409 });
  assert.equal(calls, 1);
  const offline = createApi(() => ({ base: 'http://pi.local' }), async () => { calls++; throw new TypeError(); });
  await assert.rejects(offline('/api/state'));
  assert.equal(calls, 2);
});

test('shared WebSocket URLs omit credentials in query and ignore invalid packets', () => {
  assert.equal(websocketUrl('https://pi.local:8001'), 'wss://pi.local:8001/ws');
  assert.equal(websocketUrl('http://pi.local'), 'ws://pi.local/ws');
  assert.throws(() => websocketUrl('file:///tmp'));
  for (const value of ['oops', 'null', '{}', '{"type":"state"}']) assert.equal(parsePacket(value), null);
  const packet = { type: 'state', state: { sentence: 'Xin chào', sentence_revision: 1, ai: {}, camera: {}, recognition: {} } };
  assert.deepEqual(parsePacket(JSON.stringify(packet)), packet);
});
