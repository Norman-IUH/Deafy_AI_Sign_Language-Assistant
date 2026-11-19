import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deviceStatus} from './device-status.mjs';
test('broker connection must not imply ESP presence or relay success', () => {
  const state = {pi:{mqtt:{connected:true},iot:{status:'idle'},speech:{status:'idle'}}};
  assert.match(deviceStatus(state,true).espStatus, /Chưa có phản hồi/);
  state.pi.speech.status = 'DONE';
  assert.match(deviceStatus(state,true).espStatus, /lệnh gần nhất/);
  assert.match(deviceStatus(state,false).espStatus, /Chưa xác minh/);
  state.pi.iot.error = 'ESP32 không phản hồi đúng hạn';
  assert.equal(deviceStatus(state,true).espStatus, state.pi.iot.error);
});
