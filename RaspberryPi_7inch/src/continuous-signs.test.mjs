import test from 'node:test';
import assert from 'node:assert/strict';
import { appendStableSign } from './continuous-signs.mjs';

test('joins stable captions to an editable draft, preserving intentional repeats', () => {
  const pick = text => ({text, remaining_ms: 9000});
  const draft = ['Xin chào', 'Ăn cơm', 'Ăn cơm'].map(pick).reduce(appendStableSign, '  ');
  assert.equal(draft, 'Xin chào Ăn cơm Ăn cơm');
  assert.equal(appendStableSign('Câu đã sửa  ', pick(' Tạm biệt ')), 'Câu đã sửa Tạm biệt');
  assert.equal(appendStableSign(draft, {text: 'Cũ', remaining_ms: 0}), draft);
  assert.equal(appendStableSign('x'.repeat(2000), pick('Thêm')), null);
});
