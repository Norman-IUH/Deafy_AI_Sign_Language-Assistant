import test from 'node:test';
import assert from 'node:assert/strict';
import { createAudioRouter } from './routing.mjs';
test('microphone, partial signs and duplicate confirmed events never echo', async () => {
  const spoken = [];
  const route = createAudioRouter(text => spoken.push(text), () => true);
  for (const source of ['speech', 'microphone', 'sign.partial']) await route({ source, id: source, text: 'Không đọc' });
  const event = { source: 'sign_confirmed', id: 'confirmed-1', text: 'Xin chào' };
  await route(event); await route(event);
  await route({ source: 'manual_message_sent', id: 'manual-1', text: 'Tôi cần giúp' });
  assert.deepEqual(spoken, ['Xin chào', 'Tôi cần giúp']);
});
test('disabled output consumes the event without replaying it later', async () => {
  let enabled = false, count = 0;
  const route = createAudioRouter(() => count++, () => enabled);
  const event = { source: 'sign_confirmed', id: 'one', text: 'Xin chào' };
  await route(event); enabled = true; await route(event);
  assert.equal(count, 0);
});
