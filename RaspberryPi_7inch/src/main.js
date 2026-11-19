import { mountSpeaker } from '../../shared/ui/speaker.mjs';
import { mountLearning } from './learning.js';
import { mountCourseTraining } from './training.js';
import { createTimeline } from '../../shared/ui/timeline.mjs';
import { mountSignAssist } from '../../shared/ui/SignAssist.jsx';
import { createFramePresenter } from '../../shared/camera/presenter.mjs';
import { setupImmersive } from './immersive.js';
import { createApi, requestId } from '../../shared/api/client.mjs';
import { serverOrigin } from '../../shared/api/server-origin.mjs';
import { deviceStatus } from '../../shared/ui/device-status.mjs';
import { websocketUrl, parsePacket } from '../../shared/websocket/protocol.mjs';
import './styles.css';
import { mountPiModes } from './modes.js';
import { createSubtitles } from './subtitles.mjs';

mountSignAssist('pi');

const $ = id => document.getElementById(id);
const subtitles = createSubtitles($('cameraSubtitle'), caption => piModes?.appendCaption(caption));
const icons = {
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="m22 2-11 11"/>',
  hands: '<path d="M8 13V6a2 2 0 0 1 4 0v6m0-5a2 2 0 0 1 4 0v6m0-3a2 2 0 0 1 4 0v6a6 6 0 0 1-6 6h-2a6 6 0 0 1-5-3l-4-6a2 2 0 0 1 3-2l2 2Z"/>',
  chat: '<path d="M21 11a8 8 0 0 1-8 8H7l-5 3V10a8 8 0 0 1 8-8h3a8 8 0 0 1 8 9Z"/><path d="M7 8h9M7 12h6"/>',
  history: '<path d="M3 11a9 9 0 1 1 3 8M3 4v7h7m2-4v5l3 2"/>',
  settings: '<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2.5"/><circle cx="16" cy="12" r="2.5"/><circle cx="9" cy="18" r="2.5"/>',
  camera: '<path d="M3 6h5l2-3h4l2 3h5v15H3Z"/><circle cx="12" cy="13" r="4"/>',
  expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  backspace: '<path d="m8 5-6 7 6 7h13V5Z"/><path d="m12 9 6 6m0-6-6 6"/>',
  sync: '<path d="M20 7A9 9 0 0 0 5 5L2 8m0-5v5h5m-3 9a9 9 0 0 0 15 2l3-3m0 5v-5h-5"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4Z"/>',
  volume: '<path d="m11 4-6 5H2v6h3l6 5Zm5 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 6 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15m-7-11v7m4-7v7"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ''}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
const native = false;
function readSettings() {
  try { return JSON.parse(localStorage.getItem('dakt.settings') || '{}') || {}; } catch { return {}; }
}
const settings = { landmarks: false, server: '', token: '', size: 'normal', theme: 'light', tts: true, voice: '', ...readSettings() };
let state = null, online = false, socket, retryTimer, heartbeat, generation = 0, reconnectDelay = 1000;
let busy = false, dirty = false, draftRevision = 0, currentPage = 'home', historyOffset = 0, searchRun = 0;
let previewBusy = false, speaking = false, listening = false, browserRecognizer, nativeListening = false;
let piModes;
function persist() { localStorage.setItem('dakt.settings', JSON.stringify(settings)); }
function base() {
  try { return serverOrigin(settings.server, native) || location.origin; } catch { return ''; }
}
function error(message) { $('errorBanner').textContent = message; $('errorBanner').hidden = !message; }
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500); }
function connection(value, label) {
  online = value;
  if (!value) subtitles.reset();
  if (!value) $('syncStatus').textContent = 'Ngoại tuyến · Giữ bản nháp';
  else if (!dirty) $('syncStatus').textContent = 'Đã đồng bộ';
  if ($('immersiveStatus')) $('immersiveStatus').textContent = value ? (state?.camera.error || (state?.camera.running ? 'Camera đang hoạt động' : 'Camera chưa bật')) + (state?.ai.ready ? '' : ' · ' + (state?.ai.message || '')) : label || 'Ngoại tuyến · Đang kết nối lại';
  $('connection').className = `connection ${value ? 'online' : 'offline'}`;
  $('connectionText').textContent = label || (value ? 'Đã kết nối Pi' : 'Mất kết nối');
  $('serverStatus').textContent = label || (value ? 'Đã kết nối' : 'Đang kết nối lại…');
  $('footerStatus').textContent = value ? 'Đang đồng bộ với máy chủ của bạn.' : 'Ngoại tuyến · Bản nháp vẫn được giữ trên thiết bị.';
  updateButtons();
  piModes?.connection(value);
}
function updateButtons() {
  speaking = ['processing', 'pending', 'ACK', 'PLAYING'].includes(state?.pi?.speech?.status);
  renderSpeaker(state?.pi, online);
  renderLearning(state, online);
  for (const [id, text] of Object.entries(deviceStatus(state, online))) $(id).textContent = text;
  document.querySelector('.compose-panel').classList.toggle('speaking', speaking);
  $('speakLabel').textContent = speaking ? 'Đang phát…' : 'Phát thành tiếng';
  $('sentenceInput').readOnly = busy;
  ['spaceBtn','backspaceBtn','clearBtn','applyBtn','saveBtn','cameraBtn'].forEach(id => { $(id).disabled = busy || !online; });
  $('speakBtn').disabled = !settings.tts || speaking || !$('sentenceInput').value.trim();
  $('listenBtn').disabled = busy || !online || speaking;
  piModes?.render();
  applyMicrophone(state?.microphone);
}
function refreshSubtitle() {
  if (online && state) subtitles.update(state, piModes?.captionAction(state.pi?.caption));
}
const api = createApi(() => ({ base: base(), token: settings.token }));
const timeline = createTimeline(api);
const renderSpeaker = mountSpeaker(api, applyState);
const renderLearning = mountLearning(api, applyState, toast);
mountCourseTraining(api);
function updateDiagnostics() {
  $('landmarksBtn').setAttribute('aria-pressed', String(Boolean(settings.landmarks)));
  $('recognitionScore').hidden = !settings.landmarks;
  $('recognitionTiming').hidden = !settings.landmarks;
  const recognition = state?.recognition;
  const elapsed = recognition?.elapsed_seconds, duration = recognition?.window_seconds;
  const seconds = value => value.toFixed(1).replace('.', ',');
  $('recognitionTiming').textContent = !state?.camera.running ? 'Đang chờ camera'
    : !state?.ai.ready ? 'Đang chờ mô hình'
    : Number.isFinite(elapsed) && Number.isFinite(duration) && duration > 0
      ? `${elapsed < duration ? 'Lấy mẫu' : 'Đủ mẫu'}: ${seconds(elapsed)} / ${seconds(duration)} giây`
      : 'Đang chờ dữ liệu thời gian';
  const score = state?.ai.ready && state?.camera.running ? state?.recognition.confidence : null;
  $('recognitionScore').textContent = Number.isFinite(score) ? `Điểm model: ${Math.round(Math.max(0, Math.min(1, score)) * 100)}%` : 'Chưa có dự đoán';
}
$('landmarksBtn').onclick = () => { settings.landmarks = !settings.landmarks; persist(); updateDiagnostics(); };
updateDiagnostics();
function applyState(next) {
  const previous = state;
  if (previous?.pi?.instance === next.pi?.instance && (next.revision < previous.revision || next.pi?.version < previous.pi?.version)) return;
  state = next;
  updateDiagnostics();
  timeline.refresh(next, generation);
  if (!dirty && !piModes?.active) { $('sentenceInput').value = next.sentence; draftRevision = next.sentence_revision; }
  else if (draftRevision !== next.sentence_revision) $('syncStatus').textContent = 'Máy chủ có thay đổi · Bản nháp đang được giữ';
  $('prediction').textContent = next.ai.ready ? (next.recognition.text || 'Đang quan sát cử chỉ…') : next.ai.message;
  if (next.ai.ready && next.recognition.label?.startsWith('dau_')) $('prediction').textContent += ' · Thêm dấu trong ô văn bản';
  $('prediction').title = $('prediction').textContent;
  $('aiIndicator').textContent = next.ai.ready ? 'Sẵn sàng' : 'Chưa sẵn sàng';
  $('modelStatus').textContent = next.ai.ready ? next.ai.pipeline || 'Đã nạp mô hình' : next.ai.message;
  $('cameraStatus').textContent = next.camera.error || (next.camera.running ? 'Đang hoạt động' : 'Chưa bật');
  $('cameraBtn').lastElementChild.textContent = next.camera.running ? 'Tắt camera' : 'Bật camera';
  $('cameraEmptyTitle').textContent = next.camera.error ? 'Chưa mở được camera' : next.camera.running ? 'Đang tải hình camera…' : 'Camera chưa bật';
  $('cameraEmptyHint').textContent = next.camera.error || '';
  if (!listening) $('transcript').textContent = next.transcript || 'Chưa có lời nói';
  if (!next.camera.running) clearPreview();
  if (!dirty) $('syncStatus').textContent = 'Đã đồng bộ';
  if (currentPage === 'history' && previous?.revision !== next.revision) loadHistory();
  $('immersiveStatus').textContent = !online ? 'Ngoại tuyến' : next.camera.error || (next.camera.running ? 'Camera đang hoạt động' : 'Camera chưa bật') + (next.ai.ready ? '' : ' · ' + next.ai.message);
  updateButtons();
  piModes?.apply(next);
}
async function connect() {
  const run = ++generation;
  clearTimeout(retryTimer); clearInterval(heartbeat);
  if (socket) { socket.onclose = null; socket.close(); }
  connection(false, 'Đang kết nối…');
  if (!base()) { connection(false, 'Chưa cấu hình Pi'); return; }
  try {
    const next = await api('/api/state');
    if (run !== generation) return;
    applyState(next);
    socket = new WebSocket(websocketUrl(base()));
    let lastMessage = Date.now();
    socket.onopen = () => socket.send(JSON.stringify({ token: settings.token }));
    socket.onmessage = event => {
      if (run !== generation) return;
      lastMessage = Date.now();
      const packet = parsePacket(event.data);
      if (packet?.type === 'state') {
        applyState(packet.state); connection(true); reconnectDelay = 1000;
        $('connectionResult').textContent = 'Đã kết nối máy chủ. Dữ liệu đang được đồng bộ.';
      }
    };
    socket.onclose = event => {
      if (run !== generation) return;
      clearInterval(heartbeat); connection(false);
      if (event.code === 1008) error('Kết nối bị từ chối. Kiểm tra mã truy cập và cấu hình origin của máy chủ.');
      scheduleReconnect();
    };
    socket.onerror = () => socket.close();
    heartbeat = setInterval(() => {
      if (Date.now() - lastMessage > 40000) socket.close();
      else if (socket.readyState === WebSocket.OPEN) socket.send('ping');
    }, 15000);
  } catch (issue) {
    if (run !== generation) return;
    connection(false, issue.status === 401 ? 'Cần mã truy cập' : 'Ngoại tuyến');
    $('connectionResult').textContent = issue.message;
    scheduleReconnect();
  }
}
function scheduleReconnect() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, reconnectDelay + Math.random() * 300);
  reconnectDelay = Math.min(reconnectDelay * 2, 15000);
}
async function command(action, text = '', revision = state?.sentence_revision) {
  const result = await api('/api/commands', { method: 'POST', body: JSON.stringify({ request_id: requestId(), expected_revision: revision, action, text }) });
  dirty = false; localStorage.removeItem('dakt.draft'); applyState(result.state);
}
async function commit() {
  if (dirty) await command('set', $('sentenceInput').value, draftRevision);
}
async function perform(task) {
  if (busy) return;
  busy = true; updateButtons(); error('');
  try { await task(); }
  catch (issue) {
    if (issue.status === 409) {
      try { applyState(await api('/api/state')); draftRevision = state.sentence_revision; } catch { /* Preserve the draft if resync fails. */ }
    }
    error(issue.message);
  } finally { busy = false; updateButtons(); }
}
$('sentenceInput').addEventListener('input', () => {
  if (piModes?.active) return;
  if (!dirty) draftRevision = state?.sentence_revision ?? 0;
  dirty = true; localStorage.setItem('dakt.draft', $('sentenceInput').value);
  $('syncStatus').textContent = 'Bản nháp · Bấm Cập nhật câu để chia sẻ'; updateButtons();
});
$('applyBtn').onclick = () => perform(async () => { await commit(); toast('Đã cập nhật câu trên các thiết bị.'); });
for (const [id, action] of [['spaceBtn','space'],['backspaceBtn','backspace'],['clearBtn','clear']]) {
  $(id).onclick = () => perform(async () => {
    if (action === 'clear' && $('sentenceInput').value && !confirm('Xóa câu đang soạn trên tất cả thiết bị? Nội dung đã lưu vẫn được giữ.')) return;
    await commit(); await command(action);
  });
}
$('saveBtn').onclick = () => perform(async () => {
  await commit();
  if (!state.sentence.trim()) throw new Error('Nhập hoặc ghép một câu trước khi lưu.');
  const result = await api('/api/history', { method: 'POST', body: JSON.stringify({ request_id: requestId(), kind: 'conversation', text: state.sentence, transcript: state.transcript }) });
  applyState(result.state); toast('Đã lưu cuộc trò chuyện trên máy chủ.');
});
$('cameraBtn').onclick = () => perform(async () => { applyState(await api(`/api/camera/${state?.camera.running ? 'stop' : 'start'}`, { method: 'POST' })); });
const frames = createFramePresenter($('cameraImage'), $('cameraEmpty'));
function clearPreview() { frames.clear(); }
setInterval(async () => {
  if (previewBusy || !online || !state?.camera.running || !state?.camera.has_frame || currentPage !== 'home' || document.hidden) return;
  previewBusy = true;
  const previewGeneration = generation;
  try {
    const showLandmarks = Boolean(settings.landmarks);
    const blob = await api(`/api/camera/frame?landmarks=${showLandmarks}`, { image: true });
    if (showLandmarks !== Boolean(settings.landmarks)) return;
    if (previewGeneration !== generation || !state?.camera.running) return;
    await frames.present(blob, () => previewGeneration === generation && online && state?.camera.running && currentPage === 'home' && !document.hidden);
  } catch { /* Keep the last decoded frame during a transient request failure. */ }
  finally { previewBusy = false; }
}, 50);

function appearance() {
  document.documentElement.dataset.theme = settings.theme === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : settings.theme;
  document.documentElement.dataset.size = settings.size;
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', appearance);
for (const [id,key] of [['fontSize','size'],['theme','theme']]) {
  $(id).value = settings[key]; $(id).onchange = () => { settings[key] = $(id).value; persist(); appearance(); };
}
$('ttsEnabled').checked = settings.tts;
$('ttsEnabled').onchange = () => { settings.tts = $('ttsEnabled').checked; persist(); updateButtons(); };
$('serverUrl').value = settings.server; $('apiToken').value = settings.token;
$('connectionForm').onsubmit = event => {
  event.preventDefault();
  if (busy) { $('connectionResult').textContent = 'Chờ thao tác hiện tại hoàn tất trước khi đổi máy chủ.'; return; }
  try {
    const url = serverOrigin($('serverUrl').value, native);
    settings.server = url; settings.token = $('apiToken').value.trim(); persist();
    error(''); $('connectionResult').textContent = 'Đang kiểm tra…'; state = null; connect();
  } catch (issue) { $('connectionResult').textContent = issue.message; }
};
async function shareSpeech(text) {
  if (!text.trim()) return;
  $('transcript').textContent = text;
  const payload = { request_id: requestId(), kind: 'speech', text: text.trim() };
  try { const result = await api('/api/history', { method: 'POST', body: JSON.stringify(payload) }); applyState(result.state); }
  catch (issue) { $('transcript').textContent = text; error(`${issue.message} Lời nói chưa được lưu: bạn có thể sao chép nội dung đang hiển thị.`); }
}
function listeningState(value) {
  if (value) document.querySelector('.speech-panel').dataset.empty = 'false';
  listening = value; $('listenBtn').setAttribute('aria-pressed', String(value));
  $('listenBtn').lastElementChild.textContent = value ? 'Dừng nghe' : 'Bắt đầu nghe';
  document.querySelector('.speech-panel').classList.toggle('listening', value);
  $('speechHint').textContent = value ? 'Đang nghe…' : '';
}
let micSession = null, micEdited = false, micText = '';
$('micTranscript').addEventListener('input', () => {
  micEdited = true;
  $('confirmSpeech').disabled = !$('micTranscript').value.trim() || listening;
});
function applyMicrophone(mic) {
  if (!mic) return;
  if (micSession !== mic.session) { micSession = mic.session; micEdited = false; }
  if (mic.text !== micText) {
    micText = mic.text;
    if (!micEdited) $('micTranscript').value = mic.text;
  }
  const recording = ['connecting', 'recording'].includes(mic.status);
  const processing = mic.status === 'processing';
  document.querySelector('.speech-panel').dataset.empty = String(
    !recording && !processing && !$('micTranscript').value.trim() && !mic.error);
  $('micTranscript').readOnly = recording || processing;
  listeningState(recording);
  const labels = { connecting: 'Đang chuẩn bị micro WebCamera…', recording: 'Đang nghe · Tự dừng khi nói xong · Tối đa 12 giây',
    processing: 'Đang nhận dạng câu tiếng Việt trên Pi, vui lòng chờ…', done: 'Kiểm tra và sửa lời nói, rồi bấm Xác nhận.', cancelled: 'Đã dừng micro.' };
  $('speechHint').textContent = mic.error || labels[mic.status] || 'Nguồn: micro USB WebCamera · ASR trên Pi';
  $('listenBtn').disabled = !online || processing || state?.pi?.ai.status === 'processing'
    || ['processing', 'pending', 'ACK', 'PLAYING'].includes(state?.pi?.speech.status);
  $('listenBtn').setAttribute('aria-busy', String(processing || mic.status === 'connecting'));
  $('confirmSpeech').disabled = recording || processing || !$('micTranscript').value.trim() || !online;
}
$('listenBtn').onclick = async () => {
  try {
    const path = listening ? '/api/pi/microphone/stop' : '/api/pi/microphone/start';
    applyState(await api(path, { method: 'POST', body: JSON.stringify({
      request_id: listening ? state.microphone.session : requestId() }) }));
  } catch (issue) { error(issue.message); }
};
$('confirmSpeech').onclick = async () => {
  $('confirmSpeech').disabled = true;
  await shareSpeech($('micTranscript').value);
  applyMicrophone(state?.microphone);
};

const formatTime = value => new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
const kindLabel = { speech: 'Giọng nói', sign: 'Ký hiệu', text: 'Văn bản', conversation: 'Cuộc trò chuyện', ai_question: 'Câu hỏi AI', ai_answer: 'Phản hồi AI' };
async function loadHistory(append = false) {
  const run = ++searchRun;
  if (!append) historyOffset = 0;
  $('historyStatus').textContent = 'Đang tải lịch sử…';
  try {
    const result = await api(`/api/history?q=${encodeURIComponent($('historySearch').value)}&offset=${historyOffset}`);
    if (run !== searchRun) return;
    if (!append) $('historyList').replaceChildren();
    for (const item of result.items) {
      const row = document.createElement('article'); row.className = 'history-item';
      const main = document.createElement('button'); main.className = 'history-main';
      const meta = document.createElement('div'); meta.className = 'history-meta';
      const kind = document.createElement('span'); kind.className = 'history-kind'; kind.textContent = kindLabel[item.kind];
      const time = document.createElement('time'); time.dateTime = item.created_at; time.textContent = formatTime(item.created_at);
      meta.append(kind,time); const text = document.createElement('p'); text.textContent = item.text;
      main.append(meta,text); main.onclick = () => showDetail(item.id); row.append(main);
      if (state?.capabilities.history_delete) {
        const remove = document.createElement('button'); remove.className = 'icon-button'; remove.innerHTML = icon('trash'); remove.setAttribute('aria-label', `Xóa nội dung ngày ${formatTime(item.created_at)}`);
        remove.onclick = () => perform(async () => { if (confirm('Xóa mục lịch sử này trên tất cả thiết bị? Câu đang hiển thị được giữ.')) { await api(`/api/history/${item.id}`, { method: 'DELETE' }); await loadHistory(); } }); row.append(remove);
      }
      $('historyList').append(row);
    }
    historyOffset += result.items.length;
    $('moreHistory').hidden = historyOffset >= result.total;
    $('historyStatus').textContent = `${result.total} nội dung đã lưu`;
    if (!result.total) {
      const empty = document.createElement('div'); empty.className = 'empty-state';
      empty.innerHTML = `<span>${icon('history')}</span><h2>${$('historySearch').value ? 'Không tìm thấy nội dung' : 'Chưa có lịch sử'}</h2><p>${$('historySearch').value ? 'Thử một từ khóa khác.' : 'Bấm Lưu ở trang Giao tiếp để giữ nội dung.'}</p>`;
      $('historyList').append(empty);
    }
  } catch (issue) { if (run === searchRun) $('historyStatus').textContent = issue.message; }
}
async function showDetail(id) {
  try {
    const item = await api(`/api/history/${id}`);
    $('detailTime').textContent = `${kindLabel[item.kind]} · ${formatTime(item.created_at)}`;
    $('detailText').textContent = item.text;
    $('detailTranscript').textContent = item.transcript ? `Lời người đối diện: ${item.transcript}` : '';
    $('historyDialog').showModal();
  } catch (issue) { error(issue.message); }
}
$('closeDialog').onclick = () => $('historyDialog').close();
$('refreshHistory').onclick = () => loadHistory(); $('moreHistory').onclick = () => loadHistory(true);
let searchTimer;
$('historySearch').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadHistory(), 300); };
function route() {
  currentPage = ['home','history','settings'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home';
  for (const page of ['home','history','settings']) $(`page-${page}`).hidden = page !== currentPage;
  document.querySelectorAll('nav a').forEach(link => { if (link.dataset.page === currentPage) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current'); });
  document.documentElement.dataset.page = currentPage;
  document.title = `Sign Assist · ${{ home:'Giao tiếp', history:'Lịch sử', settings:'Cài đặt' }[currentPage]}`;
  if (currentPage === 'history') loadHistory();
  if (currentPage !== 'home') { clearPreview(); browserRecognizer?.stop(); if (nativeListening) SpeechRecognition.stop(); listeningState(false); }
}
window.addEventListener('hashchange', route);
window.addEventListener('online', connect);
window.addEventListener('offline', () => { clearInterval(heartbeat); if (socket) { socket.onclose = null; socket.close(); } connection(false); scheduleReconnect(); });
window.addEventListener('pagehide', () => { browserRecognizer?.abort(); if (nativeListening) SpeechRecognition.stop(); clearPreview(); });
setupImmersive(document.querySelector('.camera-panel'), $('fullscreenBtn'), $('exitImmersive'));
const draft = localStorage.getItem('dakt.draft');
if (draft !== null) { $('sentenceInput').value = draft; dirty = true; $('syncStatus').textContent = 'Bản nháp được giữ từ lần trước'; }
piModes = mountPiModes({ api, applyState, error, toast, refreshSubtitle });
appearance(); route(); updateButtons(); connect();
