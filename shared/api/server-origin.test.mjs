import test from 'node:test';
import assert from 'node:assert/strict';
import { serverOrigin } from './server-origin.mjs';

test('native uses a LAN origin and web preview can use its own origin', () => {
  assert.equal(serverOrigin(''), '');
  assert.equal(serverOrigin('http://192.168.1.164:8001/', true), 'http://192.168.1.164:8001');
  assert.equal(serverOrigin('http://Deafy.local:8001', true), 'http://deafy.local:8001');
  for (const url of ['', 'http://localhost:8001', 'http://127.0.0.2:8001', 'http://[::1]:8001', 'http://0.0.0.0:8001']) {
    assert.throws(() => serverOrigin(url, true));
  }
  for (const url of ['http://user:password@host', 'http://host/api', 'http://host?key=secret', 'ftp://host']) {
    assert.throws(() => serverOrigin(url));
  }
});
