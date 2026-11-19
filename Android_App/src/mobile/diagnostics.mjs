const knownErrors = new Set(['Error','TypeError','ReferenceError','RangeError','NotAllowedError','NotReadableError',
  'OverconstrainedError','NotFoundError','AbortError','SecurityError','TimeoutError','NetworkError','CompileError','RuntimeError']);
function staticPath(src) {
  try {
    const url = new URL(src,location.href);
    if (url.origin !== location.origin) return '';
    const match = url.pathname.match(/^\/(?:mobile-test\/)?(?:assets|mobile)\/([\w./-]+\.(?:wasm(?:\.gz)?|js|mjs|task|bin|onnx|data|tflite|binarypb))$/);
    return match?.[1] || '';
  } catch { return ''; }
}

export function mountDiagnostics(host, manifest, setJointIds, native = false) {
  const state = {camera:'OFF',MediaPipe:'OFF',delegate:'—',Model2:'OFF',Vietsub:'Chưa có',inputShape:'30 × 126 (dự kiến)'};
  const errors = [], runs = [];
  const report = {
    state,
    error(stage,error) {
      const name = error?.name;
      const message = String(error?.message || '');
      const category = /webgl|gl context/i.test(message) ? 'WebGL'
        : /checksum/i.test(message) ? 'checksum'
        : /wasm|webassembly|simd/i.test(message) ? 'WASM'
        : /fetch|download|network/i.test(message) ? 'network' : '';
      const line = stage + ' · ' + (knownErrors.has(name) ? name : 'Error') + (category ? ' · '+category : '');
      if (!errors.includes(line)) errors.push(line);
    },
    finishRun() {
      if (state.camera !== 'READY') return;
      runs.push({...state,...report.renderVideo()});
      if (runs.length>4) runs.shift();
    },
    useModel:false,
    renderVideo:()=>({}),
  };
  window.addEventListener('error', event => {
    const asset = staticPath(event.target?.src || event.filename);
    if (asset || event.error) report.error(asset || 'JavaScript',event.error);
  },true);
  window.addEventListener('unhandledrejection', event => report.error('Promise',event.reason));
  const panel = document.createElement(native ? 'details' : 'section');
  panel.className = 'settings-section';
  const header = document.createElement(native ? 'summary' : 'h2');
  header.textContent = 'Chẩn đoán AI';
  const tip = document.createElement('p');
  tip.textContent = 'Bật camera, đưa tay vào khung. Chỉ chạy Model 2 sau khi MediaPipe đã thấy tay thật.';
  const model = document.createElement('button');
  model.className = 'button secondary';
  model.textContent = 'Chạy thêm Model 2';
  model.onclick = () => { report.useModel = true; model.hidden = true; };
  model.hidden = native;
  const jointIds = document.createElement('button');
  jointIds.type = 'button';
  jointIds.className = 'button secondary';
  jointIds.textContent = 'Số thứ tự điểm khớp';
  jointIds.setAttribute('aria-pressed','false');
  jointIds.onclick = () => {
    const enabled = jointIds.getAttribute('aria-pressed') !== 'true';
    jointIds.setAttribute('aria-pressed', String(enabled));
    setJointIds(enabled);
  };
  const calibrate = document.createElement('button');
  calibrate.type = 'button';
  calibrate.className = 'button secondary';
  calibrate.textContent = 'Hiệu chỉnh tay phải';
  const calibrationStatus = document.createElement('p');
  calibrationStatus.setAttribute('role','status');
  calibrate.onclick = () => { report.calibrate?.(); refresh(); };
  const mirrorSource = document.createElement('button');
  mirrorSource.type = 'button';
  mirrorSource.className = 'button secondary';
  mirrorSource.textContent = 'Đổi hướng ảnh nguồn';
  mirrorSource.onclick = () => report.toggleSourceMirror?.();
  const copy = document.createElement('button');
  copy.className = 'button secondary';
  copy.textContent = 'Sao chép báo cáo chẩn đoán';
  const output = document.createElement('pre');
  output.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px';
  const summary = document.createElement('p');
  summary.className = 'helper';
  summary.style.whiteSpace = 'pre-line';
  function snapshot() {
    const resources = performance.getEntriesByType('resource').flatMap(entry => {
      const file = staticPath(entry.name);
      return file ? [{file, http:entry.responseStatus || 'trình duyệt không báo mã',
        ms:Math.round(entry.duration), bytes:entry.decodedBodySize}] : [];
    });
    return {build:native ? 'android-1.0.0-rc7' : 'ios-diag-2',https:isSecureContext,checkpoint:manifest.sha256,
      modelVersion:manifest.version, mediaPipeVersion:native ? 'Hands 0.4.1675469240' : 'Tasks Vision 0.10.22-rc.20250304', ...state, ...report.renderVideo(), priorCameraRuns:runs,
      errors, resources:resources.slice(-35)};
  }
  const label = document.createElement('label');
  label.textContent = 'Nhãn đúng của mẫu vừa làm';
  const sampleLabel = document.createElement('select');
  sampleLabel.add(new Option('Chọn nhãn đúng', ''));
  for (const item of manifest.labels) sampleLabel.add(new Option(item.text, item.id));
  label.append(sampleLabel);
  const exportSample = document.createElement('button');
  const sampleText = document.createElement('textarea');
  sampleText.readOnly = sampleText.hidden = true;
  sampleText.setAttribute('aria-label','Mẫu keypoints để sao chép thủ công');
  exportSample.type = 'button';
  exportSample.className = 'button secondary';
  exportSample.textContent = 'Sao chép mẫu kiểm thử';
  exportSample.onclick = async () => {
    if (!sampleLabel.value || !report.latestInput) return;
    const bytes = new ArrayBuffer(30 * 126 * 4);
    const data = new DataView(bytes);
    report.latestInput.forEach((value, index) => data.setFloat32(index * 4,value,true));
    const content = JSON.stringify({checkpoint:manifest.sha256,shape:[30,126],label:sampleLabel.value,
      keypoints:btoa(String.fromCharCode(...new Uint8Array(bytes)))});
    try { await navigator.clipboard.writeText(content); exportSample.textContent = 'Đã sao chép mẫu'; }
    catch { sampleText.value = content; sampleText.hidden = false; sampleText.select(); }
  };
  const refresh = () => {
    model.disabled = !state.hands || state.MediaPipe !== 'READY';
    calibrate.disabled = !report.calibrate;
    mirrorSource.disabled = !report.toggleSourceMirror;
    mirrorSource.setAttribute('aria-pressed',String(Boolean(state.sourceMirrored)));
    const notice = report.calibrate ? report.calibrationStatus || '' : 'Bật camera để hiệu chỉnh.';
    if (calibrationStatus.textContent !== notice) calibrationStatus.textContent = notice;
    exportSample.disabled = !sampleLabel.value || !report.latestInput;
    const data = snapshot();
    const hand = name => name === 'Left' ? 'trái' : 'phải';
    const side = data.reportedFacing || data.cameraSide;
    summary.textContent = [
      `Camera ${side === 'environment' ? 'sau' : 'trước'} · ${data.camera}`,
      `Mirror vào MediaPipe ${data.detectorFlip ? 'bật' : 'tắt'} · Preview ${data.previewFlip ? 'bật lật' : 'tắt lật'}`,
      `MediaPipe: ${data.handedness?.map(item=>`${hand(item.side)} ${item.score}%`).join(', ') || '—'}`,
      `Slot đầu vào: trái ${data.tensorSlots?.left ? 'có' : 'trống'} · phải ${data.tensorSlots?.right ? 'có' : 'trống'}`,
      `Tensor: ${data.tensorStatus || 'Chưa lấy mẫu'} · ${data.tensorProgress || 0}/30 vị trí · ${data.windowFrames || 0} khung camera hợp lệ trong cửa sổ`,
      `Số lần lấy mẫu lại: ${data.windowResets || 0}${data.lastWindowReset ? ` · ${data.lastWindowReset}` : ''}`,
      data.inferenceBlock || data.stage || '—',
      `Model: ${manifest.version} · ${data.Model2}`,
      `Top-3: ${data.top3?.map(item=>`${item.label} ${(100*item.confidence).toFixed(1)}%`).join(', ') || '—'}`,
      `Vietsub: ${data.Vietsub}`,
    ].join('\n');
    output.textContent = JSON.stringify(data,null,2);
  };
  sampleLabel.onchange = refresh;
  copy.onclick = async () => {
    refresh();
    try { await navigator.clipboard.writeText(output.textContent); copy.textContent = 'Đã sao chép báo cáo'; }
    catch { const range = document.createRange(); range.selectNodeContents(output); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); }
  };
  if (native) tip.textContent = 'Thử cả hai camera. Bật đường nối tay để xem số điểm khớp.';
  panel.append(header,tip,summary,model,jointIds,copy);
  if (native) panel.append(calibrate,mirrorSource,calibrationStatus,label,exportSample,sampleText);
  panel.append(output); host.after(panel);
  setInterval(() => { if (!native || panel.open) refresh(); },800);
  panel.addEventListener('toggle', () => { if (panel.open) refresh(); });
  if (!native) refresh();
  return report;
}
