import test from 'node:test';
import assert from 'node:assert/strict';
import { suggestions } from './suggestions.mjs';
import { answerHTML } from './markdown.mjs';

test('suggestions use only supplied labels and match Vietnamese without accents', () => {
  const items = [{ label: 'xin_chao', text: 'Xin chào' }, { label: 'bat_den', text: 'Bật đèn' }];
  assert.deepEqual(suggestions(items, 'xin chao'), [items[0]]);
  assert.deepEqual(suggestions(items, 'den'), [items[1]]);
  assert.deepEqual(suggestions(items, ''), []);
  assert.deepEqual(suggestions(items, 'Xin chào bạn'), []);
});

test('AI Markdown renders formatting without executable HTML or image requests', () => {
  const html = answerHTML('## Chào\n\n**Mẹ** và [Pi](https://example.com)\n\n<script>alert(1)</script>\n\n![ảnh](https://example.com/track.png)\n\n[x](javascript:alert(1))');
  assert.match(html, /<h2>Chào<\/h2>/);
  assert.match(html, /<strong>Mẹ<\/strong>/);
  assert.match(html, /href="https:\/\/example.com"/);
  assert.ok(!html.includes('<script') && !html.includes('<img') && !html.includes('href="javascript:'));
});
