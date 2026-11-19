import { mountDiagnostics } from './mobile/diagnostics.mjs';
import { mountSpeaker } from '../../shared/ui/speaker.mjs';
import { createTimeline } from '../../shared/ui/timeline.mjs';
import { mountAssistant } from '../../shared/ui/assistant.mjs';
import { mountSignAssist } from '../../shared/ui/SignAssist.jsx';
import { mountMobileCamera } from './mobile/camera.mjs';
import { mountModelInfo } from './mobile/model-info.mjs';
import mobileModel from '../public/mobile/model2.json';
import { TextToSpeech } from '@capacitor-community/text-to-speech';
import { createApi, requestId } from '../../shared/api/client.mjs';
import { serverOrigin } from '../../shared/api/server-origin.mjs';
import { findPi } from '../../shared/api/discovery.mjs';
import { deviceStatus } from '../../shared/ui/device-status.mjs';
import { createSubtitles } from '../../shared/ui/subtitles.mjs';
import { websocketUrl, parsePacket } from '../../shared/websocket/protocol.mjs';
import './styles.css';
import { Capacitor, registerPlugin } from '@capacitor/core';
import { SpeechRecognition } from '@capgo/capacitor-speech-recognition';

mountSignAssist('mobile');
document.querySelector('.brand > span:last-child').textContent='Deafy';
const conversation = document.querySelector('.mobile-conversation');
const timelinePanel = document.createElement('details');
timelinePanel.className = 'mobile-history-panel';
const historyHeading = document.createElement('summary');
historyHeading.textContent = 'Hội thoại và micro';
const mic = document.querySelector('#listenBtn');
timelinePanel.append(historyHeading, mic, document.querySelector('.conversation-timeline'));
const aiPanel = document.querySelector('#mobileAIResult');
aiPanel.querySelector('summary').textContent = 'Trợ lý AI';
conversation.append(aiPanel, timelinePanel);
document.querySelector('.mobile-pi-controls').hidden = true;
document.querySelector('.app-shell').append(document.querySelector('nav'));

// Keep the composer above a keyboard that resizes only the visual viewport.
function fitViewport() {
  const viewport = window.visualViewport;
  if (!viewport) return;
  document.documentElement.style.setProperty('--app-height', `${viewport.height}px`);
  const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
  const keyboard = editing && window.innerHeight - viewport.height > 120;
  const wasOpen = document.documentElement.dataset.keyboard === 'true';
  document.documentElement.dataset.keyboard = String(keyboard);
  if (keyboard && !wasOpen && document.activeElement?.id === 'sentenceInput') {
    requestAnimationFrame(() => document.querySelector('.compose-panel').scrollIntoView({block:'nearest'}));
  }
}
window.visualViewport?.addEventListener('resize', fitViewport);
document.addEventListener('focusin', fitViewport);
document.addEventListener('focusout', () => requestAnimationFrame(fitViewport));
fitViewport();

const $ = id => document.getElementById(id);

const icons = {
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
const native = Capacitor.isNativePlatform();
const pwaBase = import.meta.env.BASE_URL;
const mobileTest = pwaBase === '/mobile-test/';
const settingsKey = mobileTest ? 'dakt.mobileTest.settings' : 'dakt.settings';
if(!native && location.protocol==='https:') $('serverHelp').textContent='PWA iPhone: để trống địa chỉ để dùng cùng HTTPS/WSS với Pi. Nhập mã truy cập Pi một lần; không nhập key Gemini/Groq/Places. Bắt đầu nghe dùng micro WebCamera trên Pi, chưa phải micro iPhone.';
$('platformNotice').hidden = true;
function readSettings() {
  try { return JSON.parse(localStorage.getItem(settingsKey) || '{}') || {}; } catch { return {}; }
}
const settings = { landmarks: false, server: '', token: '', autoDiscover: true, size: 'normal', theme: 'light', tts: true, voice: '', ...readSettings() };
const Pairing = registerPlugin('DeafyPairing');
const PiDiscovery = registerPlugin('PiDiscovery');
let resolvedServer = '';
let discoveryInFlight;
function discoverOnce() {
  discoveryInFlight ??= PiDiscovery.discover().finally(() => { discoveryInFlight = null; });
  return discoveryInFlight;
}
if (native) {
  $('serverHelp').textContent = 'Tự tìm Pi trên cùng Wi-Fi; nhập mã truy cập một lần. Có thể tắt tự tìm và nhập địa chỉ thủ công.';
  const label = document.createElement('label');
  label.className = 'checkbox-row';
  const toggle = document.createElement('input');
  toggle.type = 'checkbox'; toggle.checked = settings.autoDiscover;
  toggle.onchange = () => { settings.autoDiscover = toggle.checked; resolvedServer = ''; persist(); connect(); };
  label.append(toggle, ' Tự tìm Raspberry Pi trên Wi-Fi');
  $('connectionForm').prepend(label);
  const find = document.createElement('button');
  find.type='button'; find.className='button secondary'; find.textContent='Tìm thiết bị Deafy';
  find.onclick=()=>{settings.autoDiscover=true;toggle.checked=true;resolvedServer='';persist();connect();};
  const reconnect = document.createElement('button');
  reconnect.type='button';reconnect.className='button secondary';reconnect.textContent='Kết nối lại';
  reconnect.onclick=()=>connect();
  $('connectionForm').insertBefore(find, $('connectionResult'));
  $('connectionForm').insertBefore(reconnect, $('connectionResult'));
}
let state = null, online = false, socket, retryTimer, heartbeat, generation = 0, reconnectDelay = 1000;
let busy = false, currentPage = 'home', historyOffset = 0, searchRun = 0;
let speaking = false, listening = false, browserRecognizer, nativeListening = false;
function persist() { localStorage.setItem(settingsKey, JSON.stringify({...settings, ...(native ? {token:''} : {})})); }
const draftKey = 'dakt.mobile.localDraft';

const rememberDraft = () => localStorage.setItem(draftKey, $('sentenceInput').value);
function renderPiState() {
  const pi = state?.pi;
  $('mobilePiStatus').textContent = !online ? 'Mất kết nối Pi' : 'SignAssist AI · Dùng chung Pi';
  const pending = pi?.ai.status === 'processing' || ['processing','pending','ACK','PLAYING'].includes(pi?.speech.status);
  const mic = state?.microphone;
  const micBusy = ['connecting','recording','processing'].includes(mic?.status);
  $('mobileAskBtn').hidden = false;
  const needsRoutingUpdate = $('assistantTask').value === 'auto' && !pi?.auto_routing;
  $('mobileAskBtn').disabled = pi?.mode !== 'ai' || pi?.assistant_version !== 1 || needsRoutingUpdate || !online || busy || pending || micBusy || !$('sentenceInput').value.trim();

  $('mobileAskLabel').textContent = online && pi?.ai.status === 'processing' ? 'Chờ…' : 'Gửi';
  $('mobileAIResult').hidden = false;
  assistant?.render();

  $('mobileAIQuestion').textContent = pi?.ai.question ? 'Bạn: ' + pi.ai.question : '';
  $('mobileAIAnswer').hidden = online && (['weather','search'].includes(pi?.ai.task) || Boolean(pi?.ai.proposal));
  $('mobileAIAnswer').textContent = !online ? 'Chưa kết nối Pi.' : needsRoutingUpdate ? 'Pi cần cập nhật tự phân loại; tạm chọn tác vụ Tìm địa điểm.' : pi?.ai.error || pi?.provider_error || pi?.ai.answer || 'Câu trả lời từ Pi sẽ hiện ở đây.';
  $('mobileTransport').textContent = !online ? 'MQTT/ESP32: chưa xác minh khi mất kết nối Pi'
    : `MQTT: ${pi?.mqtt.connected ? 'đã nối broker' : pi?.mqtt.message || 'chưa cấu hình'} · ESP32: ${pi?.speech.error || (pi?.speech.status !== 'idle' ? pi?.speech.status : 'chưa có phản hồi âm thanh')}`;
  if (!native && mic) {
    const recording = ['connecting','recording'].includes(mic.status);
    listeningState(recording);
    $('listenBtn').title = 'Bắt đầu/dừng micro WebCamera trên Raspberry Pi';
    $('listenBtn').disabled = !online || busy || pending || mic.status === 'processing';

    const labels = {connecting:'Đang chuẩn bị micro Pi…',recording:'Đang nghe WebCamera trên Pi',processing:'Pi đang nhận dạng…',done:'Lần thu WebCamera gần nhất đã xong'};
    $('speechHint').textContent = mic.error || labels[mic.status] || 'Micro: WebCamera trên Pi';
    if (micSession !== mic.session) { micSession = mic.session; micEdited = false; micText = null; }
    if (micText !== mic.text) {
      micText = mic.text;
      if (!micEdited) $('micTranscript').value = mic.text;
    }
    const showDraft = Boolean(mic.text || micBusy);
    $('micTranscript').hidden = !showDraft;
    $('confirmSpeech').hidden = !showDraft;
    $('transcript').hidden = showDraft;
    $('micTranscript').readOnly = micBusy;
    $('confirmSpeech').disabled = micBusy || !online || !$('micTranscript').value.trim();
    document.querySelector('.speech-panel').dataset.empty = String(!showDraft && !state.transcript && !mic.error);
  }
}

function base() {
  try { return serverOrigin(native && settings.autoDiscover ? resolvedServer : settings.server, native) || location.origin; } catch { return ''; }
}
function error(message) { $('errorBanner').textContent = message; $('errorBanner').hidden = !message; }
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500); }
function connection(value, label) {
  const wasOnline = online;
  online = value;
  $('syncStatus').textContent = 'Bản nháp trên máy';
  $('connection').className = `connection ${value ? 'online' : 'offline'}`;
  $('connectionText').textContent = label || (value ? 'Đã kết nối Pi' : 'Pi mất kết nối');
  $('serverStatus').textContent = $('connectionText').textContent;
  $('footerStatus').textContent = value ? 'Đang đồng bộ với máy chủ của bạn.' : 'Ngoại tuyến · Bản nháp vẫn được giữ trên thiết bị.';
  updateButtons();
  if (value && !wasOnline) flushHistory();
}
function updateButtons() {

  speaking = online && ['processing', 'pending', 'ACK', 'PLAYING'].includes(state?.pi?.speech?.status);
  renderSpeaker(online ? state?.pi : null, online);
  $('mobileAIStatus').textContent = online ? 'Trợ lý AI qua Pi' : 'Trợ lý cần kết nối Pi';
  for (const [id, text] of Object.entries(deviceStatus(state, online))) $(id).textContent = text;
  if (native) {
    $('networkStatus').textContent = navigator.onLine ? 'Đang có kết nối mạng' : 'Thiết bị báo mất mạng';
    $('audioStatus').textContent = !settings.tts ? 'Đã tắt phát giọng'
      : audioOutput.value === 'phone' ? 'Giọng trên điện thoại'
      : online && state?.pi?.mqtt?.connected ? 'ESP32 · Xem phản hồi bên dưới' : 'ESP32 cần Pi và MQTT';
  }
  document.querySelector('.compose-panel').classList.toggle('speaking', speaking);
  const viaEsp = audioOutput.value === 'esp32';
  $('speakLabel').textContent = viaEsp ? 'Phát qua ESP32' : 'Phát giọng';
  $('speakingStatus').textContent = viaEsp && (!online || !state?.pi?.mqtt?.connected)
    ? 'ESP32 chưa khả dụng · Có thể chọn Điện thoại' : viaEsp && speaking ? 'Đang phát qua ESP32…' : '';
  $('sentenceInput').readOnly = busy;
  $('applyBtn').disabled = busy || !online || state?.pi?.mode !== 'ai';
  $('saveBtn').disabled = busy || !$('sentenceInput').value.trim();
  $('speakBtn').disabled = busy || !settings.tts || !$('sentenceInput').value.trim();
  if (viaEsp) $('speakBtn').disabled ||= speaking || !online || !state?.pi?.mqtt?.connected || state.pi.mode !== 'ai';
  $('listenBtn').disabled = busy || (!native && (!online || speaking));
  modelInfo?.pi(online, state?.ai?.model);
  renderPiState();
}
const api = createApi(() => ({ base: base(), token: settings.token }));
const timeline = createTimeline(api);
const renderSpeaker = mountSpeaker(api, applyState);
function applyState(next) {
  const previous = state;
  if (previous?.pi?.instance === next.pi?.instance && (next.revision < previous.revision || next.pi?.version < previous.pi?.version)) return;
  state = next;
  document.querySelector('.speech-panel').dataset.empty = String(!next.transcript && !listening);
  timeline.refresh(next, generation);
  if (!listening) $('transcript').textContent = next.transcript || 'Chưa có lời nói';
  if (currentPage === 'history' && previous?.revision !== next.revision) loadHistory();
  updateButtons();
}
async function connect() {
  const run = ++generation;
  clearTimeout(retryTimer); clearInterval(heartbeat);
  if (socket) { socket.onclose = null; socket.close(); }
  if (!native && !navigator.onLine) { connection(false, 'Mất mạng'); return; }
  if (native && settings.autoDiscover && !settings.token) {
    connection(false, 'Cần mã truy cập');
    $('connectionResult').textContent = 'Nhập mã truy cập Pi rồi bấm Lưu và kiểm tra kết nối.';
    return;
  }
  connection(false, 'Đang kết nối…');
  try {
    if (native && settings.autoDiscover) {
      connection(false, 'Đang tìm Pi…');
      const discovered = await findPi({token: settings.token, previous: resolvedServer || settings.server,
        discover: discoverOnce});
      if (run !== generation) return;
      resolvedServer = discovered;
      $('connectionResult').textContent = `Đã tìm và xác minh Pi: ${discovered}`;
    }
    if (!base()) { connection(false, 'Chưa cấu hình Pi'); return; }
    const next = await api('/api/state');
    if (run !== generation) return;
    applyState(next);
    const activeSocket = new WebSocket(websocketUrl(base()));
    socket = activeSocket;
    let lastMessage = Date.now();
    socket.onopen = () => { if (run === generation) activeSocket.send(JSON.stringify({ token: settings.token })); };
    socket.onmessage = event => {
      if (run !== generation) return;
      lastMessage = Date.now();
      const packet = parsePacket(event.data);
      if (packet?.type === 'state') {
        applyState(packet.state); if (!online) connection(true); reconnectDelay = 1000;
        $('connectionResult').textContent = 'Đã kết nối máy chủ. Dữ liệu đang được đồng bộ.';
      }
    };
    socket.onclose = event => {
      if (run !== generation) return;
      clearInterval(heartbeat); connection(false);
      if (event.code === 1008) {
        connection(false, 'Pi từ chối kết nối');
        $('connectionResult').textContent = 'Pi từ chối đồng bộ. Kiểm tra mã truy cập và địa chỉ máy chủ.';
      } else scheduleReconnect();
    };
    socket.onerror = () => activeSocket.close();
    heartbeat = setInterval(() => {
      if (Date.now() - lastMessage > 40000) socket.close();
      else if (socket.readyState === WebSocket.OPEN) socket.send('ping');
    }, 15000);
  } catch (issue) {
    if (run !== generation) return;
    const unauthorized = [401,403].includes(issue.status);
    connection(false, unauthorized ? 'Kiểm tra mã truy cập' : 'Pi mất kết nối');
    $('connectionResult').textContent = issue.message;
    if (!unauthorized) scheduleReconnect();
  }
}
function scheduleReconnect() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, reconnectDelay + Math.random() * 300);
  reconnectDelay = Math.min(reconnectDelay * 2, 15000);
}
async function shareDraft() {
  if (state.pi.mode !== 'ai') throw Error('Chuyển Pi sang AI để chia sẻ câu.');
  const draft = state.pi.buffers.ai;
  if (!confirm('Chia sẻ câu này và thay bản nháp hiện tại trên Pi?')) return;
  applyState(await api('/api/pi/draft', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:state.pi.epoch,
    mode:'ai',text:$('sentenceInput').value,expected_revision:draft.revision})}));
  toast('Đã chia sẻ câu với Pi.');
}
async function perform(task) {
  if (busy) return;
  busy = true; updateButtons(); error('');
  try { await task(); }
  catch (issue) {
    if (issue.status === 409) {
      try { applyState(await api('/api/state'));  } catch { /* Preserve the draft if resync fails. */ }
    }
    error(issue.message);
  } finally { busy = false; updateButtons(); }
}
$('sentenceInput').addEventListener('input', () => { rememberDraft(); updateButtons(); });
$('applyBtn').onclick = () => perform(shareDraft);
for (const [id, edit] of [
  ['spaceBtn', value => value + (value.endsWith(' ') ? '' : ' ')],
  ['backspaceBtn', value => Array.from(value).slice(0,-1).join('')],
  ['clearBtn', () => ''],
]) {
  $(id).onclick = () => {
    $('sentenceInput').value = edit($('sentenceInput').value);
    rememberDraft(); updateButtons();
  };
}

let historyQueue = [];
try { historyQueue = JSON.parse(localStorage.getItem('dakt.mobile.historyQueue') || '[]'); } catch {}
if (!Array.isArray(historyQueue)) historyQueue = [];
const deviceKey = 'dakt.mobile.deviceId';
const deviceId = localStorage.getItem(deviceKey) || requestId();
localStorage.setItem(deviceKey, deviceId);
const sessionId = requestId();
let syncingHistory = false;
const saveQueue = () => localStorage.setItem('dakt.mobile.historyQueue', JSON.stringify(historyQueue));
async function targetKey() {
  const destination = native && settings.autoDiscover ? 'verified-discovery' : base();
  if (!destination || !settings.token) throw Error('Cấu hình kết nối và mã truy cập Pi trước.');
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(destination + '\n' + settings.token));
  return Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2,'0')).join('');
}
async function flushHistory() {
  if (syncingHistory || !online || !historyQueue.length) return;
  syncingHistory = true;
  const connectionGeneration = generation;
  try {
    const key = await targetKey();
    for (const item of historyQueue) {
      if (!online || connectionGeneration !== generation) break;
      if (item.target !== key) continue;
      try {
        await api(item.path, {method:'POST',body:JSON.stringify(item.message)});
        historyQueue = historyQueue.filter(row => row !== item);
        saveQueue();
      } catch (issue) {
        if (item.path !== '/api/learning/mobile-feedback' || ![404,409,422].includes(issue.status)) throw issue;
        $('syncStatus').textContent = 'Mẫu học chưa được Pi nhận · Kiểm tra cài đặt và phiên bản model';
      }
    }
    if (!historyQueue.length) $('syncStatus').textContent = 'Đã đồng bộ · Bản nháp riêng';
  } catch { $('syncStatus').textContent = 'Dữ liệu chờ đồng bộ khi kết nối lại'; }
  finally { syncingHistory = false; }
}
async function enqueue(path, message) {
  if (historyQueue.length >= 100) { toast('Hàng đợi đã đầy.'); return false; }
  try {
    const target = await targetKey();
    historyQueue.push({target, path, savedAt:Date.now(), version:1, deviceId, sessionId, message});
    try { saveQueue(); } catch (issue) { historyQueue.pop(); throw issue; }
    toast('Đã lưu vào hàng đợi đồng bộ');
    flushHistory();
    return true;
  } catch (issue) { error(issue.message); return false; }
}
$('saveBtn').onclick = () => {
  const text = $('sentenceInput').value.trim();
  if (text && confirm('Lưu câu này vào lịch sử dùng chung trên Pi?')) {
    enqueue('/api/history', {request_id:requestId(), kind:'text',text});
  }
};
const assistant = mountAssistant({api, getState: () => state, getText: () => $('sentenceInput').value, commit: async () => {}, applyState, run: perform, toast,
  onTaskChange: renderPiState,
  connected: () => online,
  available: () => online && !busy && Boolean(state?.pi?.enabled)});
$('mobileAskBtn').onclick = () => {
  if ($('mobileAskBtn').disabled || state?.pi?.mode !== 'ai') return;
  return perform(async () => {
    applyState(await api('/api/pi/question', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:state.pi.epoch,...assistant.payload($("sentenceInput").value.trim()),read_results:false})}));
  });
};
function setLocalDraft(value) {
  $('sentenceInput').value = value;
  rememberDraft(); updateButtons();
}
$('useAIProposal').onclick = () => {
  const ai = state?.pi?.ai;
  if (ai?.proposal && $('sentenceInput').value.trim() === ai.source) setLocalDraft(ai.proposal);
};
$('useSpeechDraft').onclick = () => {
  const value = ($('micTranscript').hidden ? state?.transcript : $('micTranscript').value)?.trim();
  if (value) setLocalDraft(value);
};
$('signSuggestions').hidden = true;
$('mobileCameraPreview').closest('label').remove();
document.querySelector('.camera-source').lastChild.textContent = 'Camera điện thoại';
document.querySelector('.recognition-result .field-caption').textContent = 'Nhận diện trên điện thoại';
$('prediction').textContent = 'Bật camera để dùng Model 2';
$('cameraEmptyTitle').textContent = 'Camera điện thoại chưa bật';
$('aiIndicator').textContent = 'Model 2 · Cục bộ';
$('cameraImage').remove();
const landmarks = $('landmarksBtn');
const overlay = document.createElement('canvas');
overlay.className = 'mobile-hand-overlay';
overlay.setAttribute('aria-hidden','true');
const video = document.createElement('video');
video.className = 'mobile-camera-video';
video.autoplay = video.playsInline = video.defaultMuted = video.muted = video.hidden = true;
video.setAttribute('playsinline','');
document.querySelector('.camera-view').prepend(video,overlay);
const flip = document.createElement('button');
flip.type = 'button'; flip.className = 'button secondary'; flip.textContent = 'Đổi sang camera sau';
const outputLabel = document.createElement('label');
outputLabel.className = 'mobile-audio-output';
outputLabel.append('Đầu ra');
const audioOutput = document.createElement('select');
audioOutput.add(new Option('Điện thoại','phone'));
audioOutput.add(new Option('ESP32','esp32'));
audioOutput.value = settings.audioOutput === 'esp32' ? 'esp32' : 'phone';
audioOutput.onchange = () => { settings.audioOutput = audioOutput.value; persist(); updateButtons(); };
outputLabel.append(audioOutput);
$('speakBtn').closest('.compose-bottom').append(outputLabel);
const status = $('prediction');
const captionButton = $('cameraSubtitle');
const correction = document.createElement('select');
correction.setAttribute('aria-label','Sửa nhãn nhận diện');
const addCorrection = document.createElement('button');
addCorrection.type = 'button'; addCorrection.textContent = 'Thêm nhãn đã sửa';
const sendFeedback = document.createElement('button');
sendFeedback.type = 'button'; sendFeedback.className = 'button secondary'; sendFeedback.textContent = 'Gửi mẫu học';
const controls = document.createElement('div');
controls.className = 'mobile-camera-controls';
controls.append($('cameraBtn'), flip, landmarks);
captionButton.before(controls);
const cameraCalibration = document.createElement('div');
cameraCalibration.className = 'mobile-camera-calibration';
cameraCalibration.hidden = true;
const fixHand = document.createElement('button');
fixHand.type = 'button'; fixHand.className = 'button secondary';
fixHand.textContent = 'Tay phải bị báo trái?';
const calibrationMessage = document.createElement('p');
calibrationMessage.setAttribute('role','status');
cameraCalibration.append(fixHand,calibrationMessage);
if (native) captionButton.before(cameraCalibration);
const correctionPanel = document.createElement('details');
correctionPanel.className = 'mobile-correction';
const correctionHeading = document.createElement('summary');
correctionHeading.textContent = 'Sửa ký hiệu';
correctionPanel.append(correctionHeading, correction, addCorrection, sendFeedback);
captionButton.after(correctionPanel);
let caption, captionTimer, cameraRunning = false;
let signMode = 'single', lastAutoAppend;
const signSelect = document.createElement('select');
signSelect.setAttribute('aria-label', 'Chế độ nhận diện');
signSelect.add(new Option('Từng ký hiệu', 'single'));
signSelect.add(new Option('Ghép liên tục', 'continuous'));
const signPause = signButton('Tạm dừng', () => setSignMode(signMode === 'paused' ? 'continuous' : 'paused'));
const signFinish = signButton('Kết thúc', () => { setSignMode('single'); $('sentenceInput').focus(); });
const signUndo = signButton('Xóa cuối', () => {
  const input = $('sentenceInput');
  if (lastAutoAppend && input.value === lastAutoAppend.after) {
    input.value = lastAutoAppend.before;
    lastAutoAppend = null; rememberDraft(); updateButtons(); renderSignMode();
  }
});
function signButton(text, action) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'button secondary';
  button.textContent = text; button.onclick = action;
  return button;
}
function renderSignMode() {
  signSelect.value = signMode === 'single' ? 'single' : 'continuous';
  signPause.textContent = signMode === 'paused' ? 'Tiếp tục' : 'Tạm dừng';
  signPause.hidden = signFinish.hidden = signMode === 'single';
  signUndo.hidden = !lastAutoAppend || $('sentenceInput').value !== lastAutoAppend.after;
}
function setSignMode(mode) {
  signMode = mode;
  renderCaption(null); renderSignMode();
}
if (native) {
  const signTools = document.createElement('div');
  signTools.className = 'mobile-sign-tools';
  signTools.append(signSelect, signPause, signFinish, signUndo);
  captionButton.before(signTools);
  signSelect.onchange = () => setSignMode(signSelect.value);
  $('sentenceInput').addEventListener('input', () => { lastAutoAppend = null; renderSignMode(); });
  renderSignMode();
}
function append(text, automatic = false) {
  const input = $('sentenceInput');
  const next = [input.value.trimEnd(), text].filter(Boolean).join(' ');
  if (next.length > input.maxLength) { toast('Câu đã quá dài.'); return false; }
  lastAutoAppend = automatic ? {before: input.value, after: next} : null;
  input.value = next; rememberDraft();
  if (!automatic) renderCaption(null);
  camera.captionStatus('Đã thêm vào câu'); updateButtons(); renderSignMode();
  if (!automatic) toast('Đã thêm vào câu');
  return true;
}
const subtitles = createSubtitles(captionButton, item => append(item.text));
function renderCaption(item) {
  clearTimeout(captionTimer);
  caption = item && {...item,id:requestId(),label:item.id,remaining_ms:10000};
  const added = caption && cameraRunning && signMode === 'continuous' && append(item.text, true);
  const autoHint = added ? 'Đã thêm vào câu' : signMode === 'paused' ? 'Đã tạm dừng' : '';
  correctionPanel.hidden = !caption;
  if (!caption) correctionPanel.open = false;
  subtitles.update({camera:{running:cameraRunning}, pi:{enabled:true,mode:'ai',caption}}, autoHint);
  if (caption) {
    captionButton.lastElementChild.textContent = `${Math.round(item.confidence * 100)}% · ${autoHint || 'Thêm'}`;
    addCorrection.disabled = Boolean(autoHint);
    correction.value = item.id;
    captionTimer = setTimeout(() => { renderCaption(null); camera.captionStatus('Đã hết hạn'); }, 10000);
  }
}
const modelStatus = $('modelStatus');
const modelInfo = mobileTest ? null : mountModelInfo(modelStatus.closest('.settings-section'), mobileModel, __DEAFY_PACKAGED_AT__);
if (native) {
  const statusList = modelStatus.closest('dl');
  for (const [id, label] of [['networkStatus','Mạng điện thoại'],['audioStatus','Phát giọng']]) {
    const row = document.createElement('div'), name = document.createElement('dt'), value = document.createElement('dd');
    name.textContent = label; value.id = id;
    row.append(name,value); statusList.append(row);
  }
}
modelStatus.textContent = 'Model 2 sẽ nạp khi bật camera tại Giao tiếp';
const cameraLink = document.createElement('a');
cameraLink.href = '#home';
cameraLink.className = 'button secondary';
cameraLink.textContent = 'Mở Giao tiếp để thử camera';
modelStatus.closest('dl').after(cameraLink);
const diagnosticPane = !native && new URLSearchParams(location.search).get('diagnostics') === '1';
const camera = mountMobileCamera({video,overlay,status,native,
  onCalibration(visible,message,inProgress = false) {
    cameraCalibration.hidden = !visible && !message;
    fixHand.hidden = !visible;
    fixHand.disabled = inProgress;
    if (calibrationMessage.textContent !== message) calibrationMessage.textContent = message;
  },
  readMirror(side,deviceId) {
    const profile = settings.cameraMirror?.[side];
    return Boolean(deviceId && profile?.deviceId === deviceId && profile.mirrored === true);
  },
  saveMirror(side,deviceId,mirrored) {
    if (!deviceId) return;
    settings.cameraMirror = {...settings.cameraMirror,[side]:{deviceId,mirrored}};
    persist();
  },
  diagnostic: native || diagnosticPane ? (manifest, jointIds) => mountDiagnostics(document.querySelector('.camera-panel'),manifest,jointIds,native) : undefined,
  onCaption:renderCaption,
  onModelStatus: (message, engine) => { modelStatus.textContent = message; modelInfo?.runtime(message,engine); },
  isActive: () => currentPage === 'home', onRunning(running) {
  cameraRunning = running;
  $('cameraEmpty').hidden = running;
  $('cameraBtn').lastElementChild.textContent = running ? 'Tắt camera' : 'Bật camera';
  document.querySelector('.camera-panel').dataset.running = String(running);
  $('cameraStatus').textContent = running ? 'Camera điện thoại đang bật' : 'Camera điện thoại chưa bật';
  $('aiIndicator').textContent = 'Model 2 · Trên điện thoại';
}});
fixHand.onclick = () => camera.calibrate();
function showLandmarks() {
  const visible = Boolean(settings.landmarks);
  camera.showOverlay(visible);
  landmarks.textContent = visible ? 'Ẩn đường tay' : 'Hiện đường tay';
  landmarks.setAttribute('aria-pressed',String(visible));
}
landmarks.onclick = () => { settings.landmarks = !settings.landmarks; persist(); showLandmarks(); };
if (diagnosticPane) settings.landmarks = true;
showLandmarks();
for (const label of camera.labels) correction.add(new Option(label.text,label.id));
sendFeedback.onclick = async () => {
  const item = caption;
  const label = correction.value;
  if (!item || sendFeedback.disabled || historyQueue.some(row => row.message.event === item.id)) return;
  if (!confirm('Cho phép gửi keypoints của lượt này cùng nhãn đã chọn vào kho chờ duyệt trên Pi?')) return;
  sendFeedback.disabled = true;
  try {
    const raw = new ArrayBuffer(item.input.length * 4), bytes = new DataView(raw);
    item.input.forEach((value, index) => bytes.setFloat32(index * 4, value, true));
    const features = btoa(String.fromCharCode(...new Uint8Array(raw)));
    if (await enqueue('/api/learning/mobile-feedback', {event:item.id, predicted:item.label, label, confidence:item.confidence,
      captured_at:item.capturedAt, model_sha256:camera.checkpoint, version:1, device_id:deviceId, session_id:sessionId, features})) {
      if (caption?.id === item.id) renderCaption(null);
    }
  } finally { sendFeedback.disabled = false; }
};
addCorrection.onclick = () => {
  const label = caption && camera.labels.find(item => item.id === correction.value);
  if (label) append(label.text);
};
$('cameraBtn').lastElementChild.textContent = 'Bật camera';
flip.textContent = 'Camera sau';
$('cameraBtn').onclick = () => camera.toggle();
flip.onclick = () => { const facing = camera.flip(); flip.textContent = facing === 'user' ? 'Camera sau' : 'Camera trước'; };

renderCaption(null);

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
if (mobileTest && !settings.token) {
  try {
    const previous = JSON.parse(localStorage.getItem('dakt.settings') || '{}');
    const origin = previous.server ? new URL(previous.server).origin : location.origin;
    if (origin === location.origin && typeof previous.token === 'string' && previous.token.trim()) {
      const reuse = document.createElement('button');
      reuse.type = 'button'; reuse.className = 'button secondary';
      reuse.textContent = 'Dùng kết nối Deafy đã lưu';
      reuse.onclick = () => {
        $('serverUrl').value = '';
        $('apiToken').value = previous.token;
        $('connectionForm').requestSubmit();
        reuse.remove();
      };
      $('connectionForm').append(reuse);
    }
  } catch { /* A saved address can be absent or invalid. */ }
}

$('connectionForm').onsubmit = async event => {
  event.preventDefault();
  if (busy) { $('connectionResult').textContent = 'Chờ thao tác hiện tại hoàn tất trước khi đổi máy chủ.'; return; }
  try {
    const url = serverOrigin($('serverUrl').value, native && !settings.autoDiscover);
    settings.server = url; settings.token = $('apiToken').value.trim(); resolvedServer = ''; if (native) await Pairing.save({token:settings.token}); persist();
    error(''); $('connectionResult').textContent = 'Đang kiểm tra…'; state = null; connect();
  } catch (issue) { $('connectionResult').textContent = issue.message; }
};
if (!native) window.speechSynthesis?.getVoices();
$('speakBtn').onclick = () => perform(async () => {
  const text = $('sentenceInput').value.trim();
  if (!text) return;
  if (audioOutput.value === 'esp32') {
    if (!online || speaking || !state?.pi?.mqtt?.connected || state.pi.mode !== 'ai') return;
    applyState(await api('/api/pi/speech', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:state.pi.epoch,text})}));
  } else if (native) await TextToSpeech.speak({text,lang:'vi-VN'});
  else {
    if (!window.speechSynthesis) throw Error('Trình duyệt chưa hỗ trợ phát giọng.');
    const voice = speechSynthesis.getVoices().find(item => item.lang.toLowerCase().startsWith('vi') && item.localService);
    if (!voice) throw Error('Cài giọng tiếng Việt trên điện thoại để phát ngoại tuyến.');
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice; utterance.lang = 'vi-VN';
    await new Promise((resolve, reject) => {
      utterance.onend = resolve;
      utterance.onerror = () => reject(Error('Không phát được giọng tiếng Việt trên thiết bị.'));
      speechSynthesis.speak(utterance);
    });
  }
});
async function shareSpeech(text) {
  if (!text.trim()) return;
  $('transcript').textContent = text;
  if (native && !online) {
    document.querySelector('.speech-panel').dataset.empty = 'false';
    toast('Đã nhận lời nói trên điện thoại · Chưa đồng bộ Pi.');
    return;
  }
  const payload = { request_id: requestId(), kind: 'speech', text: text.trim() };
  try { const result = await api('/api/history', { method: 'POST', body: JSON.stringify(payload) }); applyState(result.state); }
  catch (issue) { $('transcript').textContent = text; error(`${issue.message} Lời nói chưa được lưu: bạn có thể sao chép nội dung đang hiển thị.`); }
}
let micSession = null, micEdited = false, micText = null;
$('micTranscript').addEventListener('input', () => {
  micEdited = true;
  $('confirmSpeech').disabled = !online || !$('micTranscript').value.trim();
});
$('confirmSpeech').onclick = () => perform(() => shareSpeech($('micTranscript').value));
function listeningState(value) {
  if (value) document.querySelector('.speech-panel').dataset.empty = 'false';
  listening = value; $('listenBtn').setAttribute('aria-pressed', String(value));
  $('listenBtn').lastElementChild.textContent = value ? 'Dừng nghe' : 'Bắt đầu nghe';
  document.querySelector('.speech-panel').classList.toggle('listening', value);
  $('speechHint').textContent = value ? 'Đang nghe…' : '';
}
$('listenBtn').onclick = async () => {
  if (!native && state?.microphone) {
    return perform(async () => applyState(await api(listening ? '/api/pi/microphone/stop' : '/api/pi/microphone/start', {method:'POST',body:JSON.stringify({request_id:listening ? state.microphone.session : requestId()})})));
  }
  if (listening) { browserRecognizer?.stop(); if (nativeListening) await SpeechRecognition.stop(); listeningState(false); return; }
  try {
    if (native) {
      if (!(await SpeechRecognition.available()).available) throw new Error('Điện thoại chưa có dịch vụ nhận giọng nói.');
      if ((await SpeechRecognition.requestPermissions()).speechRecognition !== 'granted') throw new Error('Cần quyền micro để nhận giọng nói.');
      nativeListening = true; listeningState(true);
      const result = await SpeechRecognition.start({ language: 'vi-VN', popup: true, partialResults: false, maxResults: 1 });
      if (result.matches?.[0]) await shareSpeech(result.matches[0]);
      listeningState(false); nativeListening = false;
    } else {
      const Recognizer = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Recognizer || !window.isSecureContext) throw new Error('Nhận giọng nói cần Chrome/Edge qua localhost hoặc HTTPS.');
      browserRecognizer = new Recognizer(); browserRecognizer.lang = 'vi-VN'; browserRecognizer.continuous = true; browserRecognizer.interimResults = true;
      browserRecognizer.onresult = event => {
        if (speaking || !listening) return;
        let partial = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const text = event.results[i][0].transcript;
          if (event.results[i].isFinal) shareSpeech(text); else partial += text;
        }
        if (partial) $('transcript').textContent = partial;
      };
      browserRecognizer.onerror = event => { error(`Nhận giọng nói bị dừng (${event.error}). Kiểm tra quyền micro và dịch vụ nhận giọng nói.`); listeningState(false); };
      browserRecognizer.onend = () => listeningState(false);
      browserRecognizer.start(); listeningState(true);
    }
  } catch (issue) { listeningState(false); nativeListening = false; error(issue.message || 'Không bật được nhận giọng nói.'); }
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
  document.title = `${mobileTest ? 'Deafy Mobile Test' : 'Sign Assist'} · ${{ home:'Giao tiếp', history:'Lịch sử', settings:'Cài đặt' }[currentPage]}`;
  if (currentPage === 'history') loadHistory();
  camera.sync();
  if (currentPage !== 'home') { browserRecognizer?.stop(); if (nativeListening) SpeechRecognition.stop(); listeningState(false); }
}
window.addEventListener('hashchange', route);
window.addEventListener('online', connect);
// Safari can suspend websocket timers while locked or in the background.
document.addEventListener('visibilitychange', () => { if (!document.hidden && (!native || !online)) connect(); });
window.addEventListener('pageshow', event => { if (event.persisted) connect(); });
window.addEventListener('offline', () => {
  generation++; clearTimeout(retryTimer); clearInterval(heartbeat);
  if (socket) { socket.onclose = null; socket.close(); }
  connection(false, 'Mất mạng');
  if (native) scheduleReconnect();
});
window.addEventListener('pagehide', () => { browserRecognizer?.abort(); if (nativeListening) SpeechRecognition.stop(); });
$('fullscreenBtn').onclick = async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { toast('Trình duyệt không cho phép toàn màn hình. Có thể dùng F11.'); } };
$('sentenceInput').value = localStorage.getItem(draftKey) ?? (!mobileTest ? localStorage.getItem('dakt.draft') : null) ?? '';
if (!native) $('speechHint').textContent = '';
appearance(); route(); updateButtons();
async function initializeConnection() {
  if (native) {
    try {
      const stored = await Pairing.load();
      if (stored.token) settings.token = stored.token;
      else if (settings.token) await Pairing.save({token:settings.token});
      persist(); $('apiToken').value=settings.token;
    } catch (issue) { error(issue.message); settings.token=''; }
  }
  connect();
}
initializeConnection();
if(!native && !diagnosticPane && isSecureContext && 'serviceWorker' in navigator) navigator.serviceWorker.register(pwaBase + 'sw.js', {scope:pwaBase, updateViaCache:'none'}).then(registration => {
  if (!mobileTest) return;
  const notice = document.createElement('p');
  notice.className = 'helper'; notice.setAttribute('role','status');
  notice.textContent = 'Đang lưu Model 2 để dùng ngoại tuyến…';
  document.querySelector('.mobile-camera-controls').after(notice);
  const check = () => {
    if (registration.waiting) notice.textContent = 'Có bản cập nhật. Đóng các tab Mobile Test rồi mở lại.';
    else if (registration.active?.state === 'activated') notice.textContent = 'Mobile Test đã lưu tài nguyên ngoại tuyến.';
  };
  const watch = () => {
    const worker = registration.installing;
    worker?.addEventListener('statechange', () => {
      if (worker.state === 'redundant' && !registration.active) notice.textContent = 'Chưa lưu đủ tài nguyên ngoại tuyến. Thử tải lại khi có mạng.';
      else check();
    });
  };
  registration.addEventListener('updatefound', watch); watch(); check();
}).catch(() => { if (mobileTest) toast('Chưa lưu được bản ngoại tuyến. Kiểm tra HTTPS và tải lại.'); });
