// Isolated test fixture only: mock backend :8002, frontend previews :5173/:5174.
module.exports = async function checkDualPreview(page) {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const api = 'http://127.0.0.1:8002';
  const probe = await (await page.request.get(api + '/api/state')).json();
  assert(probe.pi.provider === 'mock', 'Use the isolated mock backend');
  const context = await page.context().browser().newContext();
  await context.addInitScript(server => localStorage.setItem('dakt.settings', JSON.stringify({server})), api);
  const pi = await context.newPage(), android = await context.newPage();
  try {
    await pi.setViewportSize({width:800,height:480});
    await android.setViewportSize({width:390,height:844});
    await pi.goto('http://127.0.0.1:5173');
    await android.goto('http://127.0.0.1:5174');
    await android.waitForFunction(() => document.querySelector('#connectionText').textContent === 'Đã kết nối Pi');
    await pi.waitForFunction(() => !document.querySelector('#modeAI').disabled);
    await pi.waitForFunction(() => document.querySelector('#connectionText').textContent === 'Đã kết nối Pi');
    // Pi may activate its existing default IoT mode after connecting; compare against current server state.
    const initial = await (await page.request.get(api+'/api/state')).json();
    await pi.waitForFunction(selected => document.querySelector('#modeIoT').getAttribute('aria-pressed') === String(selected), initial.pi.enabled && initial.pi.mode === 'iot');
    await android.locator('#mobileModeAI').click();
    await pi.waitForFunction(() => document.querySelector('#modeAI').getAttribute('aria-pressed') === 'true');
    const question = 'Đồng bộ thử nghiệm ' + Date.now();
    await android.locator('#sentenceInput').fill(question);
    await android.locator('.editing-tools').evaluate(element => { element.open = true; });
    await android.locator('#applyBtn').click();
    await pi.waitForFunction(text => document.querySelector('#sentenceInput').value === text, question);
    await pi.locator('#sentenceInput').fill(question + ' Pi');
    await pi.locator('.editing-tools').evaluate(element => { element.open = true; });
    await pi.locator('#applyBtn').click();
    await android.waitForFunction(text => document.querySelector('#sentenceInput').value === text, question + ' Pi');
    await android.locator('#sentenceInput').fill(question + ' bản nháp');
    await pi.locator('#modeIoT').click();
    await android.waitForFunction(() => document.querySelector('#mobileModeIoT').getAttribute('aria-pressed') === 'true');
    await pi.locator('#modeAI').click();
    await android.waitForFunction(text => document.querySelector('#sentenceInput').value === text, question + ' bản nháp');
    await android.locator('#mobileAskBtn').click();
    await pi.waitForFunction(text => document.querySelector('#piQuestion').textContent.includes(text) && document.querySelector('#piAnswer').textContent.includes('MOCK'), question+' bản nháp');
    await android.waitForFunction(text => document.querySelector('#mobileAIQuestion').textContent.includes(text) && document.querySelector('#mobileAIAnswer').textContent.includes('MOCK'), question+' bản nháp');
    const result = await (await page.request.get(api + '/api/state')).json();
    assert(result.pi.ai.question === question + ' bản nháp', 'AI question did not synchronize');
    assert(result.pi.iot.status === 'idle', 'AI must not control relays');
    assert(result.history_count >= 2, 'Question and reply must share server history');
    const mic = {status:'done',text:'Xin chào từ micro Pi',session:'fixture-microphone'};
    await page.request.post(api+'/test/microphone',{data:mic});
    for (const client of [pi,android]) await client.waitForFunction(text => document.querySelector('#micTranscript').value === text, mic.text);
    await android.locator('#micTranscript').fill(mic.text+' đã sửa');
    await page.request.post(api+'/test/microphone',{data:mic});
    await android.waitForTimeout(400);
    assert(await android.locator('#micTranscript').inputValue() === mic.text+' đã sửa','Snapshot overwrote edited speech');
    await android.locator('#confirmSpeech').click();
    await pi.waitForFunction(() => document.querySelector('#microphoneStatus').textContent.includes('Đã nhận dạng'));
    const confirmed = await (await page.request.get(api+'/api/state')).json();
    assert(confirmed.transcript === mic.text+' đã sửa','Edited speech did not reach shared backend');
    await context.setOffline(true);
    await android.waitForFunction(() => document.querySelector('#connectionText').textContent !== 'Đã kết nối Pi');
    assert(await android.locator('#espStatus').textContent() === 'Chưa xác minh','Offline ESP state is misleading');
    await context.setOffline(false);
    await android.waitForFunction(() => document.querySelector('#connectionText').textContent === 'Đã kết nối Pi');
    return {passed:true, bidirectionalDrafts:true, sharedMode:true, unsentDraft:true, aiReply:true, history:true, sharedMicrophone:true, editableSpeech:true, reconnect:true};
  } finally {
    await context.close();
  }
};
