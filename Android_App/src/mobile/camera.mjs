import { createGru } from './gru.mjs';
import handsUrl from '@mediapipe/hands/hands.js?url';
import manifest from '../../public/mobile/model2.json';
import { features, windowedSigns } from './pipeline.mjs';
import { landmarkProjection } from './overlay.mjs';
import { cameraOrientation, rightHandCalibration } from './orientation.mjs';

const base = new URL(import.meta.env.BASE_URL + 'mobile/', location.origin).href;
async function modelBytes(filename, expected) {
  const response = await fetch(base + filename);
  if (!response.ok) throw Error('Model 2 weights unavailable');
  const bytes = await response.arrayBuffer();
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  const hash = Array.from(digest, value => value.toString(16).padStart(2,'0')).join('');
  if (hash !== expected) throw Error(`Checksum mismatch: ${filename}`);
  return bytes;
}
const loadHands = () => new Promise((resolve, reject) => {
  if (window.Hands) return resolve(window.Hands);
  const script = document.createElement('script');
  script.src = handsUrl;
  script.onload = () => window.Hands ? resolve(window.Hands) : reject(Error('MediaPipe chưa sẵn sàng.'));
  script.onerror = () => { script.remove(); reject(Error('Chưa tải được MediaPipe. Mở lại ứng dụng khi có mạng.')); };
  document.head.append(script);
});

export function mountMobileCamera({ video, overlay, status, onCaption, onModelStatus, isActive, onRunning, diagnostic, native, readMirror, saveMirror, onCalibration }) {
  let stream, loadingHands, loadingModel, desired = false, generation = 0, timer, muteTimer, opening, failed = false;
  let runningFrame = false, inferenceTask, pending = false, facing = 'user', releasedAt = -Infinity;
  const deviceIds = new Map();
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  let frameCallback;
  const ink = overlay.getContext('2d');
  const clearOverlay = () => {
    ink.setTransform(1, 0, 0, 1, 0, 0);
    ink.clearRect(0, 0, overlay.width, overlay.height);
  };
  let overlayWidth = 0, overlayHeight = 0;
  let jointIds = false;
  const resize = new ResizeObserver(([entry]) => {
    ({width: overlayWidth, height: overlayHeight} = entry.contentRect);
    clearOverlay();
  });
  resize.observe(overlay.parentElement);
  const canvas = document.createElement('canvas');
  const draw = canvas.getContext('2d');
  const signs = windowedSigns(native);
  const report = diagnostic?.(manifest, value => { jointIds = value; });
  const stats = report?.state || {};
  if (report) report.renderVideo = () => ({
    videoWidth:video.videoWidth, videoHeight:video.videoHeight, videoReadyState:video.readyState,
    videoTimeMs:Math.round(video.currentTime*1000), cameraSide:facing,
  });
  function ensureModel() {
    if (!loadingModel) {
      stats.Model2 = 'LOADING';
      onModelStatus('Đang nạp Model 2 trên điện thoại');
      loadingModel = loadModel().then(model => {
        stats.Model2 = 'READY';
        onModelStatus('Model 2 đã nạp trên điện thoại', stats.engine);
        return model;
      }, issue => {
        stats.Model2 = 'ERROR';
        report?.error('Tải Model 2',issue);
        onModelStatus('Không tải được Model 2 trên điện thoại');
        loadingModel = null;
        throw issue;
      });
    }
    return loadingModel;
  }
  async function loadLandmarks() {
    stats.MediaPipe = 'LOADING';
    if (report && !native) {
      const {diagnosticDetector} = await import('./diagnostic-detector.mjs');
      return diagnosticDetector(base, new URLSearchParams(location.search).get('delegate') === 'gpu',report);
    }
    const Hands = await loadHands();
    const hands = new Hands({locateFile: name => base + name});
    hands.setOptions({maxNumHands:2, selfieMode:false, modelComplexity:1, minDetectionConfidence:.5, minTrackingConfidence:.5});
    stats.delegate = 'MediaPipe Hands WebGL';
    return hands;
  }
  async function loadModel() {
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (!ios) {
      try {
        const ort = await import('onnxruntime-web/wasm');
        ort.env.wasm.numThreads = 1;
        ort.env.wasm.wasmPaths = base;
        const bytes = await modelBytes('model2.onnx', manifest.onnx_sha256);
        const session = await ort.InferenceSession.create(bytes,{executionProviders:['wasm']});
        stats.engine = 'ONNX WASM';
        let fallback;
        return async input => {
          if (fallback) return (await fallback)(input);
          try {
            const {logits} = await session.run({sequence:new ort.Tensor('float32',input,[1,30,126])});
            return Array.from(logits.data);
          } catch (error) {
            report?.error('Suy luận ONNX WASM',error);
            fallback = loadGru();
            await session.release().catch(() => {});
            return (await fallback)(input);
          }
        };
      } catch (error) { report?.error('ONNX WASM', error); }
    }
    return loadGru();
  }
  async function loadGru() {
    const bytes = await modelBytes('model2-gru.bin', manifest.gru_sha256);
    stats.engine = 'GRU JavaScript';
    onModelStatus('Model 2 đã nạp trên điện thoại', stats.engine);
    const raw = new DataView(bytes);
    const weights = Float32Array.from({length:raw.byteLength / 4}, (_,i)=>raw.getFloat32(i*4,true));
    return createGru(weights,manifest.labels.length);
  }
  function stop(pause = false) {
    report?.finishRun();
    if (report) { report.latestInput = null; report.calibrate = null; report.toggleSourceMirror = null; }
    onCalibration?.(false,'');
    Object.assign(stats,{camera:'OFF', hands:0, landmarks:[], Vietsub:'Chưa có', stage:'Camera chưa bật', tensorProgress:0, tensorStatus:'Chưa lấy mẫu'});
    if (!pause) desired = false;
    generation++;
    opening?.abort();
    clearTimeout(timer);
    clearTimeout(muteTimer);
    if (stream) {
      const old = stream;
      stream = null;
      old.getTracks().forEach(track => track.stop());
      releasedAt = performance.now();
    }
    const oldVideo = video;
    if (frameCallback !== undefined) oldVideo.cancelVideoFrameCallback?.(frameCallback);
    clearOverlay();
    const replacement = oldVideo.cloneNode(false);
    replacement.autoplay = replacement.playsInline = replacement.defaultMuted = replacement.muted = true;
    replacement.hidden = true;
    oldVideo.pause();
    oldVideo.srcObject = null;
    oldVideo.replaceWith(replacement);
    video = replacement;
    signs.reset();
    onCaption(null);
    onRunning(false);
    status.textContent = desired ? 'Camera tạm dừng' : 'Camera điện thoại chưa bật';
  }
  function fail(message) {
    stop(true);
    failed = true;
    status.textContent = message;
  }
  async function acquire(side, current) {
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia) throw Error('HTTPS');
    const limits = {width:{ideal:640}, height:{ideal:480}, frameRate:{ideal:native ? 30 : 15,max:native ? 30 : 20}};
    const releaseDelay = 220 - (performance.now() - releasedAt);
    if (releaseDelay > 0) await wait(releaseDelay);
    if (!current()) return;
    try {
      return await media.getUserMedia({audio:false,video:{...limits,facingMode:{exact:side}}});
    } catch (issue) {
      if (!current()) return;
      if (issue.name === 'NotReadableError' || issue.name === 'AbortError') {
        await wait(450);
        if (!current()) return;
        return media.getUserMedia({audio:false,video:{...limits,facingMode:{exact:side}}});
      }
      if (!['OverconstrainedError','NotFoundError'].includes(issue.name)) throw issue;
      const devices = await media.enumerateDevices?.().catch(() => []) || [];
      if (!current()) return;
      const match = side === 'user' ? /front|selfie|truoc|trước/i : /back|rear|environment|sau/i;
      const fallback = devices.find(d => d.kind === 'videoinput' && d.deviceId && match.test(d.label));
      const id = deviceIds.get(side) || fallback?.deviceId;
      if (id) return media.getUserMedia({audio:false,video:{...limits,deviceId:{exact:id}}});
      if (side === 'user' && devices.filter(d => d.kind === 'videoinput').length <= 1) {
        return media.getUserMedia({audio:false,video:{...limits,facingMode:{ideal:side}}});
      }
      throw issue;
    }
  }
  function ready(element, signal) {
    return new Promise((resolve,reject) => {
      const timeout = setTimeout(() => finish(Error('VIDEO_TIMEOUT')), 6500);
      const frame = element.requestVideoFrameCallback?.(() => finish());
      let settled = false;
      function finish(issue) {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        if (frame !== undefined) element.cancelVideoFrameCallback?.(frame);
        element.removeEventListener('playing', check);
        element.removeEventListener('timeupdate', check);
        signal.removeEventListener('abort', abort);
        if (issue) reject(issue); else resolve();
      }
      function check() {
        if (element.readyState >= 2 && element.videoWidth > 0 && element.currentTime > 0) finish();
      }
      function abort() { finish(Error('STALE')); }
      signal.addEventListener('abort', abort, {once:true});
      element.addEventListener('playing', check);
      element.addEventListener('timeupdate', check);
      element.play().then(check, () => check());
    });
  }
  async function start() {
    if (!desired || failed || !isActive() || document.hidden || stream || pending) return;
    const run = ++generation, side = facing;
    const current = () => run === generation;
    pending = true;
    const attempt = opening = new AbortController();
    Object.assign(stats,{camera:'LOADING', cameraFps:null, detectCallsPerSecond:null, landmarksFps:null, inferenceFps:null,
      frameMs:null,lastDetectMs:null,inferenceMs:null,handedness:[],rightAccepted:false,tensorSlots:null,
      stage:'Đang mở camera',tensorProgress:0,tensorStatus:'Chưa lấy mẫu',inferenceBlock:null,windowResets:0,lastWindowReset:null,
      hands:0,peakHands:0,lastHandLandmarks:[],landmarks:[],windowFrames:0,top3:[],lastPrediction:[],lastInput:null,lastFpsCause:null,firstHandToVietsubMs:null});
    const cameraName = side === 'user' ? 'camera trước' : 'camera sau';
    status.textContent = `Đang xin luồng ${cameraName}…`;
    const slow = setTimeout(() => {
      if (current() && !stream) status.textContent = `Chưa nhận luồng ${cameraName}. Kiểm tra quyền và ứng dụng khác đang dùng camera.`;
    }, 8000);
    try {
      const camera = await acquire(side, current);
      if (!camera) return;
      if (!current()) { camera.getTracks().forEach(track => track.stop()); releasedAt = performance.now(); return; }
      stream = camera;
      const track = camera.getVideoTracks()[0];
      if (!track) throw Error('VIDEO_TIMEOUT');
      const info = track.getSettings?.() || {};
      const cameraSide = ['user','environment'].includes(info.facingMode) ? info.facingMode : side;
      let sourceMirrored = readMirror?.(cameraSide,info.deviceId) === true;
      let orientation;
      const setOrientation = () => {
        orientation = cameraOrientation(cameraSide,sourceMirrored);
        video.dataset.mirrored = String(orientation.previewFlip);
        Object.assign(stats,{reportedFacing:info.facingMode || null,sourceMirrored, ...orientation});
      };
      setOrientation();
      track.addEventListener('ended', () => {
        if (current()) fail('Camera đã ngừng. Bấm bật camera để mở lại.');
      });
      track.addEventListener('mute', () => {
        clearTimeout(muteTimer);
        muteTimer = setTimeout(() => {
          if (current() && track.muted) {
            signs.reset(); clearOverlay(); onCaption(null);
            status.textContent = 'Camera tạm mất hình. Chờ camera hoặc thử bật lại.';
          }
        }, 700);
      });
      track.addEventListener('unmute', () => {
        clearTimeout(muteTimer);
        if (current()) status.textContent = 'Đang nhận lại hình…';
      });
      status.textContent = `Đã nhận luồng ${cameraName} · Đang chờ khung hình…`;
      video.dataset.facing = side;
      video.srcObject = camera;
      video.hidden = false;
      await ready(video, opening.signal);
      if (!current()) return;
      if (info?.deviceId && (!info.facingMode || info.facingMode === side)) deviceIds.set(side, info.deviceId);
      onRunning(true);
      status.textContent = 'Đang tải Model 2…';
      pending = false;
      stats.camera = 'READY';
      stats.stage = 'Camera sẵn sàng';
      let presented, cameraFrames = 0, cameraMeter = performance.now();
      const observe = (now, metadata) => {
        if (!current()) return;
        cameraFrames += presented ? Math.max(1, metadata.presentedFrames - presented.key) : 1;
        presented = {key:metadata.presentedFrames, time:metadata.mediaTime * 1000};
        if (now-cameraMeter >= 1000) {
          stats.cameraFps = +(cameraFrames*1000/(now-cameraMeter)).toFixed(1);
          cameraFrames = 0; cameraMeter = now;
        }
        frameCallback = video.requestVideoFrameCallback(observe);
      };
      frameCallback = video.requestVideoFrameCallback?.(observe);

      let predict, modelError = false, modelRequested = false;
      const startModel = () => {
        modelRequested = true;
        ensureModel().then(model => { predict = model; }, () => { modelError = true; });
      };
      if (!report || native) startModel();
      loadingHands ||= loadLandmarks().catch(error => { loadingHands = null; throw error; });
      let hands;
      try { hands = await loadingHands; }
      catch (error) {
        stats.MediaPipe = 'ERROR'; report?.error('Khởi tạo MediaPipe',error);
        if (current()) status.textContent = 'Camera có hình · MediaPipe chưa tải được. Tắt và bật camera để thử lại.';
        return;
      }
      if (!current()) return;
      let result;
      let resetTracking = true, calibration, calibrationUntil, pendingMirror;
      hands.onResults(value => { result = value; });
      let lastFrame = -1, lastScore, firstHandAt, lastAnnouncement = -Infinity;
      if (report && native) {
        report.calibrationStatus = '';
        report.toggleSourceMirror = () => {
          calibration = null;
          pendingMirror = !(pendingMirror ?? sourceMirrored);
        };
        report.calibrate = () => {
          calibration = rightHandCalibration(orientation.detectorFlip);
          calibrationUntil = performance.now() + 12000;
          signs.reset(); lastScore = firstHandAt = undefined; report.latestInput = null;
          onCaption(null);
          report.calibrationStatus = 'Giữ riêng tay phải trước camera, lòng bàn tay hướng vào ống kính.';
          onCalibration?.(true,report.calibrationStatus,true);
        };
      }
      let meterStart = performance.now(), detectCalls = 0, resultsCount = 0, predictions = 0;
      function infer(input, sampleStarted) {
        const revision = signs.revision();
        const began = performance.now();
        stats.stage = 'Đang suy luận Model 2';
        stats.inputShape = '30 × 126';
        stats.lastInput = {finite:input.every(Number.isFinite),nonzero:input.some(value=>value!==0)};
        inferenceTask = Promise.resolve().then(() => predict(input)).then(values => {
          if (!current() || pendingMirror !== undefined || calibration || revision !== signs.revision() || !stats.rightAccepted) return;
          if (values.length !== manifest.labels.length || !values.every(Number.isFinite)) throw Error('Invalid Model 2 logits');
          predictions++;
          if (report) report.latestInput = input;
          stats.inferenceMs = +(performance.now()-began).toFixed(1);
          const max = Math.max(...values), index = values.indexOf(max);
          const normalizer = values.reduce((sum, value) => sum + Math.exp(value-max),0);
          const confidence = 1 / normalizer;
          stats.top3 = values.map((logit,index)=>({index, id:manifest.labels[index].id, label:manifest.labels[index].text,
            logit, confidence:Math.exp(logit-max)/normalizer})).sort((a,b)=>b.logit-a.logit).slice(0,3);
          stats.lastPrediction = stats.top3;
          stats.stage = 'Đã suy luận Model 2';
          lastScore = Math.round(confidence * 100);
          if (signs.accept(index, confidence, sampleStarted)) {
            const label = manifest.labels[index];
            stats.Vietsub = label.text;
            stats.stage = 'Đã có Vietsub';
            if (firstHandAt !== undefined) stats.firstHandToVietsubMs ??= Math.round(performance.now()-firstHandAt);
            onCaption({...label, confidence, input, capturedAt:new Date().toISOString()});
          }
        }).catch(error => {
          loadingModel = null;
          if (!current()) return;
          modelError = true;
          stats.Model2 = 'ERROR'; stats.stage = 'Lỗi suy luận Model 2';
          onModelStatus('Lỗi suy luận Model 2 · Hãy bật lại camera');
          report?.error('Suy luận GRU',error);
        }).finally(() => { inferenceTask = null; });
      }
      status.textContent = 'Đang xử lý điểm tay…';
      async function tick() {
        if (run !== generation) return;
        if (runningFrame) { timer = setTimeout(tick, 30); return; }
        const now = performance.now();
        runningFrame = true;
        let phase = 'Đọc video';
        try {
          if (now - meterStart >= 1000) {
            const seconds = (now-meterStart)/1000;
            Object.assign(stats,{detectCallsPerSecond:+(detectCalls/seconds).toFixed(1),landmarksFps:+(resultsCount/seconds).toFixed(1),
              inferenceFps:+(predictions/seconds).toFixed(1)});
            meterStart=now;detectCalls=resultsCount=predictions=0;
          }
          const frameKey = presented?.key ?? video.currentTime;
          if (!track.muted && video.readyState >= 2 && frameKey !== lastFrame) {
            lastFrame = frameKey;
            if (pendingMirror !== undefined) {
              resetTracking ||= sourceMirrored !== pendingMirror;
              sourceMirrored = pendingMirror;
              pendingMirror = undefined;
              setOrientation();
              saveMirror?.(cameraSide,info.deviceId,sourceMirrored);
              report.calibrationStatus = sourceMirrored ? 'Đã đặt nguồn là ảnh lật sẵn.' : 'Đã đặt nguồn là ảnh thường.';
              onCalibration?.(false,report.calibrationStatus);
              report.latestInput = null;
              signs.reset(); lastScore = firstHandAt = undefined;
              clearOverlay(); onCaption(null);
            }
            const sampleTime = presented?.time ?? video.currentTime * 1000;
            const scale = Math.min(1, (native ? 384 : 480) / Math.max(video.videoWidth, video.videoHeight));
            const width = Math.round(video.videoWidth * scale), height = Math.round(video.videoHeight * scale);
            if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
            // MediaPipe and Model 2 both expect an effectively mirrored image.
            const flipInput = orientation.detectorFlip;
            draw.setTransform(flipInput ? -1 : 1, 0, 0, 1, flipInput ? width : 0, 0);
            draw.drawImage(video, 0, 0, width, height);
            result = null;
            phase = 'MediaPipe detectForVideo';
            detectCalls++;
            const detectionStarted = performance.now();
            if (resetTracking) { hands.reset?.(); resetTracking = false; }
            await hands.send({image:canvas,timestamp:now});
            if (run !== generation) return;
            if (result) {
              stats.MediaPipe = 'READY';
              stats.lastDetectMs = +(performance.now()-detectionStarted).toFixed(1);
              stats.videoTimestampMs = Math.round(sampleTime);
              resultsCount++;
              const lists = result.multiHandLandmarks || [];
              stats.hands = lists.length;
              stats.landmarks = lists.map(hand=>hand.length);
              if(lists.length){ stats.peakHands = Math.max(stats.peakHands || 0,lists.length); stats.lastHandLandmarks = stats.landmarks; }
              stats.handedness = (result.multiHandedness || []).map(hand=>({side:hand.label,score:Math.round(hand.score*100)}));
              if (calibration) {
                const corrected = now <= calibrationUntil ? calibration(result) : undefined;
                if (corrected !== undefined) {
                  calibration = null;
                  pendingMirror = corrected;
                  timer = setTimeout(tick, 0);
                  return;
                }
                if (now > calibrationUntil) {
                  calibration = null;
                  report.calibrationStatus = 'Chưa hiệu chỉnh được. Chỉ đưa một tay phải vào khung và thử lại.';
                  onCalibration?.(true,report.calibrationStatus);
                }
              }
              if (lists.length && firstHandAt === undefined) firstHandAt = now;
              if (report?.useModel && lists.length && !modelRequested) startModel();
              const frame = features(result);
              if (!overlay.hidden) drawHands(lists, orientation);
              stats.rightAccepted = frame.right;
              stats.tensorSlots = {left:frame.left,right:frame.right};
              const hadFrames = signs.count(), previousRevision = signs.revision();
              const input = calibration ? undefined : signs.sample(sampleTime, {...frame, hands:lists.length});
              if (hadFrames && previousRevision !== signs.revision()) {
                stats.windowResets++;
                stats.lastWindowReset = signs.gap() != null ? `Gián đoạn khung hình ${signs.gap()} ms` : 'Mất dấu tay phải';
              }
              const coverage = signs.coverage();
              if (coverage < 3000) { lastScore = undefined; stats.top3 = []; }
              stats.windowFrames = signs.count();
              stats.distinctInputFrames = signs.distinct();
              stats.tensorProgress = coverage >= 3000 ? 30 : Math.min(29, Math.floor(coverage / 100));
              stats.tensorStatus = coverage >= 3000 ? 'Hợp lệ · 30 × 126' : 'Đang chờ tensor';
              if (coverage < 3000 || lastScore === undefined && !inferenceTask && !modelError) {
                stats.stage = coverage >= 3000 ? 'Chuỗi sẵn sàng' : lists.length ? 'Đã phát hiện bàn tay' : 'Camera sẵn sàng';
              }
              stats.inferenceBlock = calibration ? 'Đang hiệu chỉnh hướng ảnh camera' : modelError ? 'Model 2 lỗi · Camera vẫn theo dõi tay' : !predict ? 'Model 2 chưa sẵn sàng'
                : !lists.length ? 'Chưa thấy bàn tay'
                : !frame.right ? signs.count() ? 'Mất dấu tay phải thoáng qua · Đang chờ lại' : frame.left ? 'Chỉ có slot tay trái. Model 2 cần slot tay phải.' : 'Chưa xác nhận được slot tay phải.'
                : coverage < 3000 ? signs.gap() != null ? `Nhịp camera bị gián đoạn (${signs.gap()} ms) · đang lấy lại mẫu` : 'Đang thu đủ cửa sổ 3 giây'
                : null;
              if (!calibration && (!report?.calibrationStatus || frame.left && !frame.right)) {
                onCalibration?.(frame.left && !frame.right,report?.calibrationStatus || '');
              }
              if (input && predict && !modelError && !inferenceTask) infer(input,now);
              stats.frameMs = +(performance.now()-now).toFixed(1);
              const handText = frame.left ? 'Tay trái và tay phải' : 'Tay phải';
              const message = modelError ? 'Camera có hình · Model 2 lỗi. Bật lại camera để thử.'
                : report && !modelRequested ? `MediaPipe hoạt động · ${stats.hands} tay · Model 2 đang tắt`
                : !predict ? 'MediaPipe hoạt động · Đang tải Model 2…'
                : !frame.right
                ? lists.length ? frame.left ? 'Đã thấy tay trái · Đưa tay phải vào khung' : 'Đã thấy tay · Chưa phân loại được tay' : 'Chưa thấy bàn tay'
                : lastScore === undefined
                  ? `${handText} · ${inferenceTask ? 'Đang suy luận' : `${Math.min(3, coverage / 1000).toFixed(1)}/3 giây`}`
                  : `${handText} · Model 2 ${lastScore}% · ${lastScore >= 70 ? 'Đã suy luận' : 'Chưa rõ ký hiệu'}`;
              if (status.textContent !== message && now - lastAnnouncement >= 250) {
                status.textContent = message;
                lastAnnouncement = now;
              }
            }
          }
          if (run === generation) timer = setTimeout(tick, Math.max(0, (native ? 67 : 83) - (performance.now() - now)));
        } catch (error) {
          if (current()) {
            if (phase.startsWith('MediaPipe')) stats.MediaPipe = 'ERROR';
            stats.stage = 'Lỗi xử lý'; stats.inferenceBlock = phase;
            if (phase.startsWith('MediaPipe')) loadingHands = null;
            report?.error(phase,error);
            signs.reset(); clearOverlay(); onCaption(null);
            status.textContent = 'Camera có hình · Lỗi xử lý điểm tay/Model 2. Bật lại camera để thử.';
          }
        } finally {
          runningFrame = false;
        }
      }
      tick();
    } catch (error) {
      if (current()) {
        fail(error.name === 'NotAllowedError' ? 'Trong cài đặt website Safari hoặc quyền ứng dụng, cho phép Camera rồi bấm bật lại.'
          : ['OverconstrainedError','NotFoundError'].includes(error.name) ? 'Không tìm thấy camera đã chọn. Bấm Đổi camera để thử nguồn còn lại.'
          : ['NotReadableError','AbortError'].includes(error.name) ? 'Camera đang bận. Đóng ứng dụng khác đang dùng camera rồi bấm bật lại.'
          : error.message === 'HTTPS' ? 'Camera cần trang HTTPS được tin cậy.'
          : error.message === 'VIDEO_TIMEOUT' ? 'Safari đã cấp luồng nhưng chưa hiển thị khung hình. Bấm bật hoặc đổi camera để thử lại.'
          : 'Không mở được camera hoặc Model 2. Kiểm tra quyền và tài nguyên ứng dụng.');
        stats.camera = 'ERROR'; report?.error('Camera',error);
      }
    } finally {
      clearTimeout(slow);
      // Only the attempt that still owns the camera-open slot may release it.
      if (opening === attempt) {
        pending = false;
        if (run !== generation && desired) start();
      }
    }
  }
  function drawHands(hands, {previewFlip, detectorFlip}) {
    if (!overlayWidth || !overlayHeight) return;
    const dpr = window.devicePixelRatio || 1;
    const width = Math.round(overlayWidth * dpr), height = Math.round(overlayHeight * dpr);
    if (overlay.width !== width || overlay.height !== height) {
      overlay.width = width; overlay.height = height;
    }
    clearOverlay();
    const project = landmarkProjection(video.videoWidth, video.videoHeight, overlayWidth, overlayHeight, previewFlip, detectorFlip);
    ink.setTransform(width / overlayWidth, 0, 0, height / overlayHeight, 0, 0);
    ink.lineWidth = 2;
    ink.strokeStyle = '#16a34a';
    ink.fillStyle = '#ffdf72';
    for (const hand of hands) {
      if (hand.length !== 21 || hand.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) continue;
      const points = hand.map(project);
      ink.beginPath();
      for (const [a,b] of window.HAND_CONNECTIONS || []) {
        ink.moveTo(...points[a]); ink.lineTo(...points[b]);
      }
      ink.stroke();
      for (const [index,[x,y]] of points.entries()) {
        ink.beginPath(); ink.arc(x,y,3,0,2*Math.PI); ink.fill();
        if (jointIds) { ink.font = '10px sans-serif'; ink.strokeStyle = '#000'; ink.strokeText(index,x+4,y-3); ink.fillText(index,x+4,y-3); ink.strokeStyle = '#16a34a'; }
      }
    }
  }
  function sync() {
    if (!isActive() || document.hidden) stop(true);
    else start();
  }
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('pagehide', () => stop(true));
  window.addEventListener('pageshow', sync);
  return {
    sync,
    calibrate() { report?.calibrate?.(); },
    captionStatus(value) { stats.Vietsub = value; },
    showOverlay(value) { overlay.hidden = !value; clearOverlay(); },
    toggle() { if (desired && !failed) stop(); else { failed = false; desired = true; start(); } },
    flip() { facing = facing === 'user' ? 'environment' : 'user'; failed = false; stop(true); start(); return facing; },
    labels: manifest.labels,
    checkpoint: manifest.sha256,
  };
}
