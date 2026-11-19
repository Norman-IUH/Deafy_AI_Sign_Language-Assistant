// Run in a disposable browser with scripts/ui_fixture.py on :8002, never on a real Pi.
module.exports = async function checkAndroidOffline(page) {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const exceptions = [];
  page.on('pageerror', e => exceptions.push(e.message));
  const state = await (await page.request.get('http://127.0.0.1:8002/api/state')).json();
  state.ai = {ready:true, message:'UI fixture only'};
  state.camera = {running:true, error:null};
  state.recognition = {...state.recognition, text:'Xin chào', confidence:0.9};
  let disconnected = false, ws;
  await page.route('**/api/state', route => route.fulfill({status:disconnected ? 503 : 200,
    contentType:'application/json', body:JSON.stringify(disconnected ? {detail:'UI offline fixture'} : state)}));
  await page.route('**/api/camera/frame?*', route => route.fulfill({status:503, body:'No camera fixture'}));
  await page.routeWebSocket('**/ws', socket => {
    ws = socket;
    socket.onMessage(() => socket.send(JSON.stringify({type:'state',state})));
  });
  await page.goto('http://127.0.0.1:5174');
  await page.evaluate(() => localStorage.setItem('dakt.settings',JSON.stringify({server:'http://127.0.0.1:8002'})));
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#connection').classList.contains('online'));
  assert(await page.locator('#prediction').textContent() === 'Xin chào','Connected prediction');
  // First update establishes context, subsequent event must show once and expire after 10s.
  await page.clock.install();
  ws.send(JSON.stringify({type:'state',state}));
  state.confirmed_sign = {id:'ui-fixture-1',text:'Xin chào'};
  ws.send(JSON.stringify({type:'state',state}));
  await page.locator('#cameraSubtitle').waitFor({state:'visible'});
  await page.clock.fastForward(9999);
  assert(await page.locator('#cameraSubtitle').isVisible(),'Subtitle expired early');
  await page.clock.fastForward(1);
  assert(await page.locator('#cameraSubtitle').isHidden(),'Subtitle did not expire at 10s');
  await page.locator('#sentenceInput').fill('Bản nháp khi chưa có Pi');
  disconnected = true; ws.close();
  await page.waitForFunction(() => document.querySelector('#connection').classList.contains('offline'));
  assert((await page.locator('#modelStatus').textContent()).includes('Chưa xác minh'),'Stale model-ready status');
  assert((await page.locator('#cameraStatus').textContent()).includes('Chưa xác minh'),'Stale camera status');
  assert(await page.locator('#aiIndicator').textContent() === 'Chưa sẵn sàng','Stale AI badge');
  assert(await page.locator('#cameraSubtitle').isHidden(),'Subtitle survived disconnect');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#connection').classList.contains('offline'));
  assert(await page.locator('#sentenceInput').inputValue() === 'Bản nháp khi chưa có Pi','Offline draft lost');
  assert(await page.locator('#cameraBtn').isDisabled(),'Offline camera action enabled');
  const layouts=[];
  for(const [width,height] of [[360,800],[390,844],[412,915]]) {
    await page.setViewportSize({width,height});
    for(const screen of ['home','history','settings']) {
      await page.evaluate(screen => {location.hash=screen;},screen);
      await page.locator('#page-'+screen).waitFor({state:'visible'});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Horizontal overflow '+width+screen);
      if(width===390) await page.screenshot({path:'.tools/model2-android-'+screen+'.png'});
    }
    layouts.push([width,height]);
  }
  assert(!exceptions.length,exceptions.join('; '));
  return {passed:true,checks:'connected/disconnected status, real 10s subtitle timer, offline draft across reload, 3 screens x 3 resolutions',layouts};
};
