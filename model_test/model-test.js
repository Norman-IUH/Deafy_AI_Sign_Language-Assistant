import { createFramePresenter } from '/ui/frame-presenter.mjs';
const $ = id => document.getElementById(id);
const presenter = createFramePresenter($('frame'), $('empty'));
let state, busy = false, stopped = false, online = false, expectedKey, captureVocabularyKey, shownProfile, generation = 0;
async function post(path, body = {}) {
  const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json','X-Model-Test-Session':state.session},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw Error(Array.isArray(result.detail) ? result.detail.map(e=>e.msg).join('; ') : result.detail || 'Không thực hiện được thao tác.');
  return result;
}
async function run(action) {
  if (busy || !state || !online || stopped) return;
  busy = true; generation++; render(); $('error').hidden = true;
  try { await action(); } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
  finally { busy = false; render(); }
}
function render() {
  if (!state) return;
  const blocked = busy || !online || stopped;
  const ready = state.camera.running && state.model;
  const capturing = Boolean(state.benchmark?.capture);
  if (shownProfile !== state.profile) { $('model').value = state.profile; shownProfile = state.profile; }
  $('switch').disabled = blocked || Boolean(state.trial) || capturing;
  $('camera').disabled = blocked;
  $('camera').textContent = state.camera.running ? 'Tắt camera' : 'Bật camera';
  $('clear').disabled = blocked || !state.events.length;
  $('trial').disabled = blocked || !ready || Boolean(state.trial) || capturing;
  $('shutdown').disabled = blocked;
  $('connection').textContent = stopped ? 'Đã dừng môi trường thử' : online ? 'Đã nối môi trường thử Windows' : 'Mất kết nối môi trường thử';
  $('cameraStatus').textContent = state.camera.error || state.model_error || (state.camera.running ? state.model ? 'Camera laptop · GRU đang chạy' : 'Đang nạp model…' : 'Camera đã tắt');
  $('prediction').textContent = state.recognition.text || 'Đang chờ camera';
  $('score').textContent = state.recognition.confidence == null ? 'Chưa có confidence' : `Softmax cao nhất: ${(state.recognition.confidence*100).toFixed(1)}%`;
  $('progress').value = state.recognition.progress || 0;
  $('sampling').textContent = `${(state.recognition.elapsed_seconds || 0).toFixed(1)} / ${state.recognition.window_seconds || 3} giây · cần tay phải hiện rõ`;
  $('top3').replaceChildren(...(state.recognition.top_candidates || []).map(item=>{const li=document.createElement('li');li.textContent=`${item.text} · ${(item.confidence*100).toFixed(1)}%`;return li;}));
  for (const [id,key,unit] of [['fps','fps',''],['gru','gru_ms_median',' ms'],['pipeline','pipeline_ms_median',' ms']]) $(id).textContent = state.metrics[key] == null ? '—' : state.metrics[key] + unit;
  $('modelInfo').textContent = `${state.profiles[state.profile].name} · ${state.model?.version || 'Chưa nạp'} · SHA256 ${state.profiles[state.profile].sha256.slice(0,12)}…`;
  $('metadata').textContent = state.model ? JSON.stringify(state.model,null,2) : 'Metadata và nhãn sẽ đọc từ checkpoint khi bật camera.';
  $('confirmed').textContent = state.events.length ? state.events.map(item=>item.text || item.label).join(' · ') : 'Chưa có ký hiệu được xác nhận.';
  const key = JSON.stringify(state.model?.classes);
  if (key !== expectedKey) {
    expectedKey = key;
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Không làm ký hiệu · thử false positive';
    $('expected').replaceChildren(placeholder,...Object.keys(state.model?.classes || {}).map(label=>{const option=document.createElement('option');option.value=label;option.textContent=label;return option;}));
  }
  $('expected').disabled = blocked || Boolean(state.trial) || capturing;
  $('trialStatus').textContent = state.trial ? `Đang ghi: còn ${state.trial.remaining} giây` : '';
  $('trialResults').textContent = state.trials.length ? state.trials.slice(-6).map(row=>`${row.profile} · ${row.user_expected_label || 'Không làm ký hiệu'} · ${row.valid_capture ? row.user_expected_label ? row.matched ? 'Có xác nhận đúng nhãn đã chọn' : 'Chưa xác nhận nhãn đã chọn' : `${row.false_positive_events} sự kiện nhận nhầm` : 'Lượt không hợp lệ: camera chưa hoạt động đủ'} · sự kiện: ${row.confirmed_labels.join(', ') || 'không có'}`).join(' | ') : 'Chưa có lượt đánh giá. Không có số liệu accuracy webcam tự tạo.';
  $('isolation').textContent = state.isolation;
  const benchmark = state.benchmark;
  const vocabularyKey = JSON.stringify(benchmark?.vocabulary);
  if (vocabularyKey !== captureVocabularyKey) {
    captureVocabularyKey = vocabularyKey;
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Chọn nhãn checkpoint…';
    $('captureLabel').replaceChildren(placeholder,...(benchmark?.vocabulary || []).map(label=>{const option=document.createElement('option');option.value=label;option.textContent=label;return option;}));
  }
  const gesture = $('captureKind').value === 'gesture';
  $('captureLabel').disabled = blocked || capturing || !gesture;
  for (const id of ['captureSubject','captureSession','captureSplit','captureCondition','captureKind']) $(id).disabled = blocked || capturing;
  $('capture').disabled = blocked || !ready || !benchmark || capturing || Boolean(state.trial) || !$('captureSubject').checkValidity() || !$('captureSession').checkValidity() || (gesture && !$('captureLabel').value);
  $('captureStatus').textContent = capturing ? `${benchmark.capture.phase === 'preparing' ? 'Chuẩn bị' : 'Đang thu'} · còn ${benchmark.capture.remaining} giây`
    : benchmark?.last_capture?.status === 'saved' ? `Đã lưu mẫu hợp lệ: ${benchmark.last_capture.path}` : benchmark?.last_capture?.message || 'Chọn loại mẫu và mã người/session trước khi thu.';
  $('captureCounts').textContent = benchmark?.counts.length ? benchmark.counts.map(row=>`${row.split} / ${row.label_or_kind}: ${row.count}`).join(' · ') : 'Chưa có mẫu benchmark. Không có số liệu false positive hoặc accuracy độc lập được tạo sẵn.';
  $('benchmarkReport').hidden = !benchmark?.report_ready;
}
$('switch').onclick = () => run(async()=>{presenter.clear();state=await post('/api/model',{profile:$('model').value});});
$('camera').onclick = () => run(async()=>{state=await post(state.camera.running ? '/api/camera/stop' : '/api/camera/start');if(!state.camera.running)presenter.clear();});
$('clear').onclick = () => run(async()=>{state=await post('/api/events/clear');});
$('trial').onclick = () => run(async()=>{state=await post('/api/trial',{label:$('expected').value || null});});
$('capture').onclick = () => run(async()=>{state=await post('/api/capture',{subject:$('captureSubject').value.trim(),session:$('captureSession').value.trim(),split:$('captureSplit').value,condition:$('captureCondition').value,kind:$('captureKind').value,label:$('captureKind').value==='gesture' ? $('captureLabel').value : null});});
for (const id of ['captureSubject','captureSession','captureKind','captureLabel']) $(id).addEventListener('input',render);
$('shutdown').onclick = () => run(async()=>{await post('/api/shutdown');stopped=true;presenter.clear();$('connection').textContent='Đã dừng môi trường thử';});
async function poll() {
  const version = generation;
  try {
    const response=await fetch('/api/state');if(!response.ok)throw Error('Không truy cập được backend thử.');
    const next=await response.json();
    if(version===generation&&!busy&&!stopped){if(!online)$('error').hidden=true;online=true;state=next;render();if(!state.camera.has_frame)presenter.clear();}
  } catch(error) {online=false;render();$('connection').textContent='Mất kết nối môi trường thử';$('error').textContent=error.message;$('error').hidden=false;}
  if(!stopped)setTimeout(poll,250);
}
async function frame() {
  const version = generation;
  try {
    if(!busy&&online&&state?.camera.has_frame){const response=await fetch(`/api/camera/frame?landmarks=${$('landmarks').checked}`);if(response.ok)await presenter.present(await response.blob(),()=>version===generation&&Boolean(state?.camera.running));}
  } catch { /* State polling supplies camera/network errors; keep the last complete frame. */ }
  if(!stopped)setTimeout(frame,70);
}
poll();frame();
