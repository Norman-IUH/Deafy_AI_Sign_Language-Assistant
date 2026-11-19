import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import * as ort from 'onnxruntime-web/wasm';
import { createGru } from './gru.mjs';

const directory = process.argv[2];
const read = name => readFile(join(directory, name));
const { rows, checkpoint } = JSON.parse(await read('parity.json'));
const manifest = JSON.parse(await read('model2.json'));
assert.equal(checkpoint, manifest.sha256);
assert.ok(rows.length > 0);
const loadFloats = bytes => Float32Array.from({length:bytes.length / 4}, (_, i) => bytes.readFloatLE(i * 4));
const gru = createGru(loadFloats(await read('model2-gru.bin')), manifest.labels.length);
ort.env.wasm.numThreads = 1;
ort.env.wasm.wasmBinary = new Uint8Array(await read('ort-wasm-simd-threaded.wasm'));
const ortSession = await ort.InferenceSession.create(new Uint8Array(await read('model2.onnx')), { executionProviders:['wasm'] });
const top = values => values.map((_, i) => i).sort((a,b) => values[b]-values[a]).slice(0,3);
function softmax(values) {
  const max = Math.max(...values);
  const scores = values.map(value => Math.exp(value-max));
  const total = scores.reduce((sum, value) => sum+value,0);
  return scores.map(value => value/total);
}
const results = {};
try {
  for (const row of rows) {
    const input = loadFloats(Buffer.from(row.tensor, 'base64'));
    assert.equal(input.length, 30 * 126);
    const { logits } = await ortSession.run({sequence:new ort.Tensor('float32', input, [1,30,126])});
    for (const [runtime, values] of [['ONNX WASM',Array.from(logits.data)],['GRU JavaScript',gru(input)]]) {
      const key = `${row.group} · ${runtime}`;
      const result = results[key] ??= {samples:0, sameTop1:0, sameTop3:0, correct:0, maxLogitDelta:0, maxProbabilityDelta:0, maxConfidenceDelta:0};
      const expected = top(row.logits), actual = top(values);
      const baseline = softmax(row.logits), probability = softmax(values);
      assert.equal(values.length, manifest.labels.length);
      assert.ok(values.every(Number.isFinite));
      result.samples++;
      result.sameTop1 += Number(expected[0] === actual[0]);
      result.sameTop3 += Number(expected.every((index,i) => index === actual[i]));
      result.correct += Number(actual[0] === row.label);
      result.maxLogitDelta = Math.max(result.maxLogitDelta, ...values.map((value,i) => Math.abs(value-row.logits[i])));
      result.maxProbabilityDelta = Math.max(result.maxProbabilityDelta, ...probability.map((value,i) => Math.abs(value-baseline[i])));
      result.maxConfidenceDelta = Math.max(result.maxConfidenceDelta, Math.abs(probability[actual[0]]-baseline[expected[0]]));
    }
  }
} finally { await ortSession.release(); }
console.log(JSON.stringify(results,null,2));
for (const result of Object.values(results)) {
  assert.equal(result.sameTop1,result.samples);
  assert.equal(result.sameTop3,result.samples);
  assert.ok(result.maxLogitDelta < 1e-4 && result.maxProbabilityDelta < 1e-5);
}
