import { test } from 'node:test';
import assert from 'node:assert/strict';
import { timelineMessages } from './timeline.mjs';
test('history is chronological, speech stays left, saved replies right, latest live speech is not duplicated', () => {
  const result = timelineMessages([{id:3,kind:'speech',text:'Bây giờ'}, {id:2,kind:'conversation',text:'Xin chào',transcript:'Bạn cần gì?'}, {id:1,kind:'sign',text:'Cảm ơn'}], 'Bây giờ');
  assert.deepEqual(result.map(m=>[m.own,m.text]), [[true,'Cảm ơn'],[false,'Bạn cần gì?'],[true,'Xin chào'],[false,'Bây giờ']]);
  assert.equal(result.at(-1).live,true);
  assert.equal(timelineMessages([{id:4,kind:'speech',text:'Khác'}], 'Bây giờ')[0].own,false);
});

test('saved conversation transcript does not repeat the preceding speech event', () => {
 const result=timelineMessages([{id:2,kind:'conversation',text:'Cảm ơn',transcript:'Xin chào'},{id:1,kind:'speech',text:'Xin chào'}], 'Xin chào');
 assert.equal(result.filter(m=>!m.own).length,1);
});

test('shared AI replies have an AI sender and do not replace live speech', () => {
  const result = timelineMessages([{id:3,kind:'ai_answer',text:'Xin chào'}, {id:2,kind:'ai_question',text:'Bạn là ai?'}, {id:1,kind:'speech',text:'Lời nói'}], 'Lời nói');
  assert.equal(result[2].sender, 'AI');
  assert.equal(result[2].own, false);
  assert.equal(result[0].live, true);
});
