// Disposable browser context; isolated backend test database on port 8002.
module.exports = async function checkAndroidPreview(page) {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const issues = [];
  const onError = error => issues.push(error.message);
  page.on('pageerror', onError);
  try {
    await page.goto('http://127.0.0.1:5174');
    await page.evaluate(() => {
      localStorage.setItem('dakt.settings', JSON.stringify({server:'http://127.0.0.1:8002'}));
      localStorage.removeItem('dakt.draft');
    });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#connectionText').textContent === 'Đã kết nối Pi');
    for (const [width,height] of [[360,800],[390,844],[412,915]]) {
      await page.setViewportSize({width,height});
      for (const screen of ['home','history','settings']) {
        await page.goto('http://127.0.0.1:5174/#'+screen);
        await page.locator('#page-'+screen).waitFor({state:'visible'});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow '+screen+width);
        if (screen === 'home') {
          assert(await page.locator('#sentenceInput').evaluate(e => e.getBoundingClientRect().bottom <= document.querySelector('nav').getBoundingClientRect().top), 'Composer behind nav');
          await page.locator('#mobileCameraPreview').uncheck();
          assert(!await page.locator('.camera-view').isVisible(), 'Collapse camera');
          await page.locator('#mobileCameraPreview').check();
          assert(await page.locator('.camera-view').isVisible(), 'Expand camera');
        }
      }
    }
    await page.goto('http://127.0.0.1:5174/#history');
    await page.locator('#historySearch').fill('no-result-'+Date.now());
    await page.getByRole('heading',{name:'Không tìm thấy nội dung'}).waitFor();
    await page.goto('http://127.0.0.1:5174/#home');
    await page.locator('#sentenceInput').fill('');
    assert(await page.locator('#speakBtn').isDisabled(), 'Empty speech must be disabled');
    await page.locator('#sentenceInput').fill('Kiểm thử giao diện');
    await page.locator('.editing-tools summary').click();
    await page.locator('#applyBtn').click();
    await page.waitForFunction(() => document.querySelector('#syncStatus').textContent === 'Đã đồng bộ');
    const state = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
    const sentence = state.pi.enabled ? state.pi.buffers[state.pi.mode].text : state.sentence;
    assert(sentence === 'Kiểm thử giao diện', 'Editor must call the shared draft/command API');
    // Explicit speech now goes to Pi/ESP; no physical hardware in this fixture.
    let speechPayload;
    await page.route('**/api/pi/speech', async route => {
      speechPayload = route.request().postDataJSON();
      await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Fixture: ESP32 chưa kết nối'})});
    });
    await page.locator('#speakBtn').click();
    await page.getByRole('alert').filter({hasText:'Fixture: ESP32 chưa kết nối'}).waitFor();
    assert(speechPayload.text === 'Kiểm thử giao diện' && speechPayload.epoch === state.pi.epoch && speechPayload.request_id, 'Pi speech payload');
    await page.unroute('**/api/pi/speech');
    await page.request.post('http://127.0.0.1:8002/test/microphone',{data:{status:'idle',session:'android-mic'}});
    await page.waitForFunction(() => document.querySelector('#listenBtn').getAttribute('aria-pressed') === 'false');
    const microphoneStart = page.waitForResponse(response => response.url().endsWith('/api/pi/microphone/start'));
    await page.locator('#listenBtn').click();
    assert((await microphoneStart).status() === 503,'Windows fixture must not pretend to have Pi USB hardware');
    await page.request.post('http://127.0.0.1:8002/test/microphone',{data:{status:'done',text:'Kiểm thử micro',session:'android-mic'}});
    await page.waitForFunction(() => document.querySelector('#micTranscript').value === 'Kiểm thử micro');
    const speechSaved = page.waitForResponse(response => response.url().endsWith('/api/history') && response.request().method() === 'POST');
    await page.locator('#confirmSpeech').click();
    assert((await speechSaved).ok(), 'STT transcript must reach history API');
    await page.setViewportSize({width:390,height:480});
    await page.locator('#sentenceInput').focus();
    assert(await page.locator('#sentenceInput').evaluate(e => e.getBoundingClientRect().bottom <= document.querySelector('nav').getBoundingClientRect().top), 'Keyboard-sized viewport clips input');
    await page.setViewportSize({width:390,height:844});
    await page.locator('#sentenceInput').fill('Bản nháp chưa gửi');
    await page.route('**/api/state', route => route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Máy chủ đang ngoại tuyến'})}));
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#connection').classList.contains('offline'));
    assert(await page.locator('#sentenceInput').inputValue() === 'Bản nháp chưa gửi', 'Offline draft must survive reload');
    assert(await page.locator('#cameraBtn').isDisabled(), 'Offline camera control disabled');
    await page.unroute('**/api/state');
    assert(!issues.length, 'Console exceptions: '+issues.join(', '));
    return {passed:true,resolutions:3,screens:3,checks:'camera collapse, history search, empty state, edit API, TTS/STT wiring, keyboard-sized viewport, offline draft and controls'};
  } finally {
    page.off('pageerror', onError);
    await page.unroute('**/api/pi/speech');
    await page.unroute('**/api/state');
  }
};
