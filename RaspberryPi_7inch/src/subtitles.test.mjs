import test from 'node:test';
import assert from 'node:assert/strict';
import { createSubtitles } from './subtitles.mjs';

test('stable subtitle is selectable once while pending and its lifetime is not extended by render', async () => {
  let now = 0, timer, expires, finish;
  const picks = [];
  const element = { firstElementChild: {}, lastElementChild: {} };
  const clock = { performance: { now: () => now }, clearTimeout() { timer = null; },
    setTimeout(fn, ms) { timer = fn; expires = now + ms; } };
  const controller = createSubtitles(element, item => {
    picks.push(item.id);
    return new Promise(resolve => { finish = resolve; });
  }, clock);
  const state = { camera: { running: true }, recognition: { status: 'stabilizing' },
    pi: { mode: 'ai', enabled: true, caption: null } };
  controller.update(state);
  assert.equal(element.disabled, true);
  assert.equal(element.firstElementChild.textContent, 'Đang nhận diện…');
  state.pi.caption = { id: 'one', text: 'Xin chào', remaining_ms: 10000 };
  controller.update(state);
  assert.equal(element.disabled, false);
  const pending = element.onclick();
  await element.onclick();
  assert.deepEqual(picks, ['one']);
  now = 2000;
  controller.update(state);
  assert.equal(expires, 10000);
  assert.equal(element.disabled, true);
  finish();
  await pending;
  now = 10000;
  timer();
  controller.update(state);
  assert.equal(element.disabled, true);
  state.pi.caption = { ...state.pi.caption, id: 'two' };
  controller.update(state);
  assert.equal(element.disabled, false);
  controller.reset();
  assert.equal(element.hidden, true);
});
