import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, webcrypto } from 'node:crypto';
import { findPi, verifyPi } from './discovery.mjs';

const token = 'paired-test-token';
function probe({badKey = false, redirectOrigin = false} = {}) {
  return async (url, options) => {
    assert.equal(options.headers, undefined);
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    const parsed = new URL(url), nonce = parsed.searchParams.get('challenge');
    const origin = redirectOrigin ? 'http://192.168.137.99:8001' : parsed.origin;
    const proof = createHmac('sha256', badKey ? 'wrong' : token)
      .update(`deafy-discovery-v1\napi\n${nonce}\n${origin}\n1883`).digest('hex');
    return {ok: true, json: async () => ({service:'DAKT-Nc', origin, mqtt_port:1883, proof})};
  };
}
test('discovery verifies paired server before any token is sent', async () => {
  assert.equal(await verifyPi('http://192.168.137.122:8001', token, probe(), webcrypto), true);
  assert.equal(await verifyPi('http://192.168.137.122:8001', token, probe({badKey:true}), webcrypto), false);
  assert.equal(await verifyPi('http://192.168.137.122:8001', token, probe({redirectOrigin:true}), webcrypto), false);
  assert.equal(await verifyPi('http://8.8.8.8:8001', token, () => {throw Error('Must not probe public addresses');}, webcrypto), false);
});
test('IP change finds a new verified candidate, rejecting a fake advertisement', async () => {
  const calls = [];
  const next = await findPi({token, previous:'http://192.168.137.122:8001',
    discover:async()=>({origins:['http://192.168.137.99:8001','http://192.168.137.125:8001']}),
    verify:async origin => {calls.push(origin);return origin.includes('.125:');}});
  assert.equal(next, 'http://192.168.137.125:8001');
  assert.equal(calls.length, 3);
});
test('an old challenge response cannot be replayed for a new connection', async () => {
  let captured;
  const firstProbe = async (...args) => {
    const response = await probe()(...args);
    captured = await response.json();
    return {ok:true, json:async()=>captured};
  };
  assert.equal(await verifyPi('http://192.168.137.122:8001', token, firstProbe, webcrypto), true);
  assert.equal(await verifyPi('http://192.168.137.122:8001', token,
    async()=>({ok:true,json:async()=>captured}), webcrypto), false);
});
test('missing pairing token never starts discovery; no verified candidate stays offline', async () => {
  await assert.rejects(findPi({token:'',discover:()=>{throw Error('Must not run');}}), /mã truy cập/);
  await assert.rejects(findPi({token,discover:async()=>({origins:[]})}), /Chưa tìm thấy Pi/);
});
