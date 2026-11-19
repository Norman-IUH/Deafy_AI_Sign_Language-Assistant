// Run in a disposable Playwright context with an isolated mock backend on port 8002.
module.exports = async function checkPiFullscreen(page) {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const calls = [];
  const question = 'Bật đèn có nghĩa là gì? ' + Date.now();
  const capture = request => {
    if (request.method() === 'POST') calls.push(new URL(request.url()).pathname);
  };
  page.on('request', capture);
  try {
    const probe = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
    assert(probe.pi.provider === 'mock', 'Use an isolated mock backend for this test');
    await page.setViewportSize({ width: 800, height: 480 });
    await page.goto('http://127.0.0.1:5173');
    await page.evaluate(() => {
      localStorage.setItem('dakt.settings', JSON.stringify({ server: 'http://127.0.0.1:8002' }));
      localStorage.removeItem('dakt.pi.drafts');
    });
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#connectionText').textContent === 'Đã kết nối Pi');
    const before = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
    await page.locator('#fullscreenBtn').click();
    await page.locator('#modeAI').click();
    await page.waitForFunction(() => document.documentElement.dataset.piMode === 'ai' && !document.querySelector('#modeAI').disabled);
    await page.locator('#sentenceInput').fill('   ');
    assert(await page.locator('#askBtn').isDisabled(), 'Whitespace must not be sent');
    await page.locator('#sentenceInput').fill(question);
    const count = () => calls.filter(p => p === '/api/pi/question').length;
    assert(count() === 0, 'Typing must not automatically send');
    await page.locator('#askBtn').evaluate(button => { button.click(); button.click(); button.click(); });
    await page.waitForFunction(text => document.querySelector('#piAnswer').textContent.includes(text), question);
    assert(count() === 1, 'Repeated clicks must make one AI request');
    assert(!calls.includes('/api/pi/control'), 'AI must not send relay control requests');
    assert(!await page.locator('#piAnswerPanel').evaluate(e => e.open), 'Answer drawer starts closed');
    for (const size of [{width:800,height:480}, {width:1024,height:600}, {width:1440,height:900}]) {
      await page.setViewportSize(size);
      const layout = await page.locator('.camera-panel').evaluate(panel => {
        const camera = panel.querySelector('.camera-view').getBoundingClientRect();
        const controls = ['modeAI','modeIoT','cameraBtn','exitImmersive','sentenceInput','askBtn','speakBtn','signSuggestionToggle'];
        return {
          fits: panel.scrollWidth <= panel.clientWidth && panel.scrollHeight <= panel.clientHeight,
          cameraHeight: camera.height,
          controls: controls.map(id => {
            const box = document.getElementById(id).getBoundingClientRect();
            return box.height >= 48 && box.left >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
          })
        };
      });
      assert(layout.fits && layout.controls.every(Boolean), 'Fullscreen overflow or clipped control at ' + JSON.stringify(size));
      assert(layout.cameraHeight >= size.height / 2, 'Camera must keep at least half of fullscreen');
      const aiRect = await page.locator('.camera-view').boundingBox();
      await page.locator('#piAnswerToggle').click();
      assert(JSON.stringify(await page.locator('.camera-view').boundingBox()) === JSON.stringify(aiRect), 'Answer drawer must not resize camera');
      await page.locator('#piAnswerToggle').click();
      await page.locator('#modeIoT').click();
      await page.waitForFunction(() => document.documentElement.dataset.piMode === 'iot' && !document.querySelector('#modeAI').disabled);
      assert(JSON.stringify(await page.locator('.camera-view').boundingBox()) === JSON.stringify(aiRect), 'AI and IoT camera bounds must match');
      assert((await page.locator('#piIoTStatus').innerText()).includes('Chưa cấu hình'), 'No success without MQTT');
      await page.locator('#modeAI').click();
      await page.waitForFunction(() => document.documentElement.dataset.piMode === 'ai' && !document.querySelector('#modeAI').disabled);
    }
    await page.locator('#modeIoT').click();
    await page.waitForFunction(() => document.documentElement.dataset.piMode === 'iot' && !document.querySelector('#modeAI').disabled);
    assert(!await page.locator('#askBtn').isVisible(), 'IoT must hide send');
    await page.locator('#exitImmersive').click();
    assert(await page.locator('.pi-mode-bar').evaluate(e => e.parentElement.id === 'page-home'), 'Restore normal mode bar');
    await page.locator('#modeAI').click();
    await page.waitForFunction(() => document.documentElement.dataset.piMode === 'ai' && !document.querySelector('#modeAI').disabled);
    assert(await page.locator('#sentenceInput').inputValue() === question, 'Draft must survive mode/fullscreen switches');
    await page.locator('#fullscreenBtn').click();
    await page.route('**/api/pi/question', route => route.fulfill({ status: 503, contentType:'application/json', body:JSON.stringify({detail:'AI thử nghiệm: mất Internet'}) }));
    await page.locator('#askBtn').click();
    await page.waitForFunction(() => document.querySelector('#errorBanner').textContent.includes('mất Internet'));
    assert(await page.locator('#errorBanner').isVisible(), 'API error must be visible inside native fullscreen');
    await page.unroute('**/api/pi/question');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.body.classList.contains('camera-immersive'));
    const after = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
    assert(before.camera.running === after.camera.running, 'Mode changes must preserve camera state');
    assert(!calls.some(p => p.startsWith('/api/camera/')), 'Mode/fullscreen must not start or stop camera');
    return { passed: true, questionRequests: count(), note: 'One request reached mock backend; second deliberately returned 503.' };
  } finally {
    page.off('request', capture);
    await page.unroute('**/api/pi/question');
  }
};
