import test from 'node:test';
import assert from 'node:assert/strict';
import { createFramePresenter } from './presenter.mjs';
test('decode first, preserve last good frame, revoke replaced and cancelled frames', async () => {
  const image = { hidden: true, removeAttribute() { delete this.src; } }, empty = { hidden: false };
  const revoked = []; let id = 0, reject = false;
  const presenter = createFramePresenter(image, empty, () => ({ async decode() { if (reject) throw Error('bad frame'); } }), {
    createObjectURL: () => String(++id), revokeObjectURL: value => revoked.push(value)
  });
  await presenter.present({}); assert.equal(image.src, '1');
  reject = true;
  await assert.rejects(presenter.present({})); assert.equal(image.src, '1');
  reject = false;
  await presenter.present({}, () => false); assert.equal(image.src, '1');
  await presenter.present({}); assert.equal(image.src, '4');
  presenter.clear(); assert.equal(image.hidden, true); assert.equal(empty.hidden, false);
  assert.deepEqual(revoked, ['2', '3', '1', '4']);
});
test('clear invalidates a frame that is still decoding', async () => {
  let resolve;
  const image = { hidden: true, removeAttribute() {} }, empty = {};
  const revoked = [];
  const presenter = createFramePresenter(image, empty, () => ({ decode: () => new Promise(done => { resolve = done; }) }), {
    createObjectURL: () => 'pending', revokeObjectURL: url => revoked.push(url)
  });
  const pending = presenter.present({}); presenter.clear(); resolve(); await pending;
  assert.equal(image.hidden, true); assert.deepEqual(revoked, ['pending']);
});
