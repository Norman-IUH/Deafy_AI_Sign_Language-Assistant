// Run in a disposable browser context against the isolated mock backend on Windows :8002.
module.exports = async function checkPiInput(page) {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const calls = [];
  page.on('request', r => { if (r.method() === 'POST') calls.push(new URL(r.url()).pathname); });
  await page.addInitScript(() => {
    localStorage.setItem('dakt.settings', JSON.stringify({ server: 'http://127.0.0.1:8002' }));
    window.SpeechRecognition = window.webkitSpeechRecognition = function () { throw new Error('Pi must not use browser STT'); };
  });
  await page.goto('http://127.0.0.1:5173');
  await page.waitForFunction(() => !document.querySelector('#modeAI').disabled);
  const initial = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
  assert(initial.pi.provider === 'mock', 'Use the isolated test backend');
  await page.locator('#modeAI').click();
  await page.waitForFunction(() => document.documentElement.dataset.piMode === 'ai');
  for (const size of [{width:800,height:480}, {width:1024,height:600}, {width:1440,height:900}]) {
    await page.setViewportSize(size);
    const controls = await page.evaluate(() => ['modeAI','modeIoT','askBtn','speakBtn','listenBtn','confirmSpeech'].map(id => {
      const e = document.getElementById(id), b = e.getBoundingClientRect();
      const hit = document.elementFromPoint(b.x + b.width/2, b.y + b.height/2);
      return b.width >= 44 && b.height >= 44 && b.bottom <= innerHeight && (e === hit || e.contains(hit));
    }));
    assert(controls.every(Boolean), 'Core control clipped or obscured: ' + JSON.stringify(size));
  }
  await page.locator('#sentenceInput').fill('');
  await page.locator('#signSuggestionToggle').click();
  await page.locator('#signSearch').fill('xin chao');
  const response = page.waitForResponse(r => r.url().endsWith('/api/pi/select'));
  await page.locator('#signChoices button').getByText('Xin chào', {exact:true}).click();
  assert((await response).status() === 200, 'Selection API failed');
  await page.waitForFunction(() => document.querySelector('#sentenceInput').value === 'Xin chào');
  assert(!calls.includes('/api/pi/question') && !calls.includes('/api/pi/control'), 'Selection must not send AI or relay commands');
  const content = '**Xin chào**\n\n[x](javascript:alert(1))\n\n<img src=x onerror="alert(1)">';
  await page.locator('#sentenceInput').fill(content);
  await page.locator('#askBtn').click();
  await page.waitForFunction(() => document.querySelector('#piAnswer strong')?.textContent === 'Xin chào');
  assert(await page.locator('#piAnswer script,#piAnswer img,#piAnswer a[href^="javascript:"]').count() === 0, 'Unsafe AI markup');
  await page.locator('#listenBtn').click();
  await page.waitForFunction(() => document.querySelector('#errorBanner').textContent.includes('arecord'));
  assert(calls.includes('/api/pi/microphone/start'), 'Pi must call backend recording');
  return {passed:true, sizes:3, selection:true, safeMarkdown:true, microphoneBackendError:true};
};
