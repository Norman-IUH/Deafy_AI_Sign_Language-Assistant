import { test } from 'node:test';
import assert from 'node:assert/strict';
import { previewProxy } from './previewProxy.mjs';

test('remote previews use one authenticated HTTP/WebSocket destination', () => {
  const proxy = previewProxy({DAKT_PREVIEW_API:'http://192.168.1.2:8001',DAKT_API_TOKEN:'test-only'});
  assert.equal(proxy['/api'].target, 'http://192.168.1.2:8001');
  assert.equal(proxy['/ws'].target, 'ws://192.168.1.2:8001');
  assert.equal(proxy['/ws'].headers.authorization, 'Bearer test-only');
  assert.equal(previewProxy({})['/api'].target, 'http://127.0.0.1:8001');
  for (const url of ['file:///tmp', 'http://user:pass@host', 'http://host/path', 'http://host?token=x']) {
    assert.throws(() => previewProxy({DAKT_PREVIEW_API:url}));
  }
});

test('hostname previews discover and verify a changed Pi before HTTP or WS credentials', async () => {
  let address = '192.168.137.122', accept = true;
  const checked = [];
  const rules = previewProxy({DAKT_PREVIEW_API:'http://Deafy.local:8001', DAKT_API_TOKEN:'paired'},
    {discover:async()=>({origins:[`http://${address}:8001`]}),
      verify:async origin=>{checked.push(origin);return accept && origin === `http://${address}:8001`;}});
  const http = {options:{}}, ws = {options:{}};
  rules['/api'].configure(http); rules['/ws'].configure(ws);
  assert.deepEqual(rules['/api'].headers, {});
  assert.equal(await rules['/api'].bypass(), undefined);
  assert.equal(http.options.target, 'http://192.168.137.122:8001');
  await new Promise(resolve => setTimeout(resolve, 1050));
  address = '192.168.137.228';
  assert.equal(await rules['/ws'].bypass(), undefined);
  assert.equal(ws.options.target, 'ws://192.168.137.228:8001');
  assert.equal(ws.options.headers.authorization, 'Bearer paired');
  await new Promise(resolve => setTimeout(resolve, 1050));
  address = '192.168.137.99'; accept = false;
  assert.equal(await rules['/api'].bypass(), false);
  assert.deepEqual(http.options.headers, {});
  assert.ok(checked.length >= 3);
});
