import { requestId } from '../../shared/api/client.mjs';
import { answerHTML } from './markdown.mjs';
import { mountAssistant } from '../../shared/ui/assistant.mjs';
import { appendStableSign } from './continuous-signs.mjs';

const $ = id => document.getElementById(id);
const statusLabel = { idle: 'Chưa có yêu cầu', processing: 'Đang tạo giọng nói trên Pi', pending: 'Đã gửi · Chờ ESP32', ACK: 'ESP32 đã nhận',
  PLAYING: 'ESP32 đang phát', DONE: 'ESP32 đã hoàn tất', error: 'Có lỗi', ERROR: 'ESP32 báo lỗi', cancelled: 'Đã hủy do chuyển chế độ' };

export function mountPiModes({ api, applyState, error, toast, refreshSubtitle }) {
  let state, camera, microphone, online = false, editing = false;
  let lastAnswer;
  let signMode = 'single', seenCaption, autoCaption, lastAppend, signNotice = '';
  let drafts;
  try { drafts = JSON.parse(localStorage.getItem('dakt.pi.drafts') || '{}'); } catch { drafts = {}; }
  if (!drafts || typeof drafts !== 'object' || Array.isArray(drafts)) drafts = {};
  const revisions = {};
  const persist = () => localStorage.setItem('dakt.pi.drafts', JSON.stringify(drafts));
  const current = () => 'ai';
  const text = () => String(drafts[current()] ?? state?.buffers[current()].text ?? '');
  function keepDraft(value) {
    const mode = current();
    if (!Object.hasOwn(drafts, mode)) revisions[mode] = state?.buffers[mode].revision ?? 0;
    drafts[mode] = value; persist();
  }

  function collect(next) {
    const caption = state.caption;
    if (!caption || caption.id === seenCaption) return;
    seenCaption = caption.id;
    if (signMode !== 'continuous' || !online || editing || !camera?.running || !next.ai?.ready
        || !state.enabled || state.mode !== 'ai' || state.settling) return;
    const before = text();
    const appended = appendStableSign(before, caption);
    if (appended === before) return;
    if (appended === null) {
      signNotice = 'Ô câu đã đầy · Xóa bớt để ghép tiếp.';
      return;
    }
    lastAppend = {before, after: appended};
    autoCaption = caption.id;
    keepDraft(appended);
    signNotice = 'Đã thêm: ' + caption.text;
  }

  function setSignMode(value) {
    signMode = value;
    seenCaption = state?.caption?.id;
    signNotice = '';
    render();
  }

  $('piSignMode').onchange = event => setSignMode(event.target.value);
  $('piSignPause').onclick = () => setSignMode(signMode === 'paused' ? 'continuous' : 'paused');
  $('piSignFinish').onclick = () => { setSignMode('single'); $('sentenceInput').focus(); };
  $('piSignUndo').onclick = () => {
    if (editing || !lastAppend || text() !== lastAppend.after) return;
    keepDraft(lastAppend.before); lastAppend = null; render();
  };

  function render() {
    if (!state) return;
    document.documentElement.dataset.piMode = 'ai';
    $('piModeStatus').textContent = 'Giao tiếp AI';
    $('composeHeading').lastChild.textContent = 'Câu của bạn';
    $('sentenceInput').placeholder = 'Ghép ký hiệu, dùng micro hoặc nhập câu…';
    if ($('sentenceInput').value !== text()) $('sentenceInput').value = text();
    $('piSignMode').value = signMode === 'single' ? 'single' : 'continuous';
    $('piSignPause').hidden = $('piSignFinish').hidden = signMode === 'single';
    $('piSignPause').textContent = signMode === 'paused' ? 'Tiếp tục' : 'Tạm dừng';
    $('piSignUndo').hidden = !lastAppend || text() !== lastAppend.after;
    $('piSignUndo').disabled = editing;
    $('sentenceInput').readOnly = editing;
    $('sentenceInput').setAttribute('aria-describedby', 'piModeHint');
    $('piAnswerPanel').hidden = false;
    $('piAnswerPanel').dataset.task = state.ai.task || '';
    $('askBtn').hidden = false;
    $('askBtn').closest('.compose-bottom').hidden = false;
    const busy = state.ai.status === 'processing' || ['processing','pending','ACK','PLAYING'].includes(state.speech.status)
      || ['connecting','recording','processing'].includes(microphone?.status);
    const needsRoutingUpdate = $('assistantTask').value === 'auto' && !state.auto_routing;
    $('askBtn').disabled = state.assistant_version !== 1 || needsRoutingUpdate || !online || !state.enabled || editing || !text().trim() || busy;
    $('speakBtn').disabled = state.assistant_version !== 1 || !state.enabled || !online || editing || !text().trim() || busy || !$('ttsEnabled').checked;
    $('speakLabel').textContent = state.speech.status === 'processing' ? 'Đang tạo giọng…'
      : ['pending','ACK','PLAYING'].includes(state.speech.status) ? 'Đang phát…' : 'Phát qua ESP32';
    $('speakBtn').setAttribute('aria-busy', String(['processing','pending','ACK','PLAYING'].includes(state.speech.status)));
    $('askLabel').textContent = state.ai.status === 'processing' ? 'Đang gửi…' : ({auto:'Gửi',rewrite:'Ghép câu',question:'Hỏi AI',search:'Tìm kiếm',weather:'Thời tiết'}[$('assistantTask').value]);
    $('askBtn').setAttribute('aria-busy', String(editing || state.ai.status === 'processing'));
    for (const id of ['spaceBtn','backspaceBtn','clearBtn','applyBtn','saveBtn']) $(id).disabled = !state.enabled || editing;
    for (const id of ['clearDraftBtn']) $(id).disabled = !state.enabled || editing || !text();
    $('applyBtn').disabled ||= !online;
    $('saveBtn').disabled ||= !online;
    $('piModeHint').textContent = signMode === 'paused' ? 'Đã tạm dừng ghép câu.'
      : signMode === 'continuous' ? signNotice || 'Chờ ký hiệu mới · Nghỉ tay để lặp lại cùng ký hiệu.'
      : state.assistant_version !== 1 ? 'Cần cập nhật backend SignAssist AI trước khi gửi/phát.' : 'Kiểm tra câu. Chọn tác vụ Trợ lý AI hoặc bấm Phát loa.';
    $('piAnswerHeading').textContent = state.ai.task==='weather'?'Thời tiết':state.ai.task === 'search' ? 'Kết quả tìm địa điểm' : state.provider === 'mock' ? 'Bản thử MOCK · Chưa kết nối Gemini' : 'Câu trả lời AI';
    $('piAnswer').hidden = ['weather', 'search'].includes(state.ai.task);
    $('piQuestion').textContent = state.ai.question ? 'Bạn: ' + state.ai.question : '';
    if (lastAnswer !== state.ai.answer) {
      lastAnswer = state.ai.answer;
      $('piAnswer').innerHTML = answerHTML(state.ai.answer || 'Câu trả lời sẽ xuất hiện ở đây.');
    }
    $('signSuggestions').hidden = false;
    $('piAIStatus').textContent = ['weather','search'].includes(state.ai.task) ? '' : state.ai.error || state.provider_error || (state.ai.status === 'processing' ? 'Đang chờ AI trả lời…' : '');
    const directSpeech = state.speech.request_id && state.speech.request_id !== state.ai.request_id;
    $('piRequestStatus').textContent = !online ? 'Ngoại tuyến · Bản nháp được giữ'
      : needsRoutingUpdate ? 'Pi cần cập nhật tự phân loại; tạm chọn tác vụ Tìm địa điểm.'
      : directSpeech || ['processing','pending','ACK','PLAYING','error','ERROR'].includes(state.speech.status) ? state.speech.error || `Âm thanh ESP32: ${statusLabel[state.speech.status] || state.speech.status}`
      : $('piAIStatus').textContent || (state.ai.search ? 'Mở Trợ lý AI để xem kết quả' : state.ai.answer ? 'Đã có câu trả lời · Mở Trợ lý AI để xem' : 'Kiểm tra câu hỏi, rồi bấm Gửi');
    $('piAnswerToggleLabel').textContent = state.ai.answer ? 'Trợ lý AI · Mới' : 'Trợ lý AI';
    $('piAnswerPanel').setAttribute('aria-busy', String(state.ai.status === 'processing'));
    $('piSpeechStatus').textContent = state.speech.error || (state.speech.status === 'idle' ? '' : `Âm thanh ESP32: ${statusLabel[state.speech.status] || state.speech.status}`);
    $('syncStatus').textContent = Object.hasOwn(drafts, current())
      ? revisions[current()] !== undefined && revisions[current()] !== state.buffers[current()].revision
        ? 'Có ký hiệu mới · Giữ bản nháp' : 'Bản nháp được giữ trên Pi'
      : 'Đã đồng bộ';
    assistant.render();
    refreshSubtitle();
    $('immersiveStatus').textContent = !online ? 'Ngoại tuyến' : camera?.error || (camera?.running ? 'Camera đang hoạt động' : 'Camera chưa bật');
  }

  async function run(task) {
    if (editing) return;
    editing = true; render(); error('');
    try { await task(); } catch (issue) {
      error(issue.message);
      if (issue.status === 409) {
        try {
          const snapshot = await api('/api/state');
          applyState(snapshot);
          revisions[current()] = state.buffers[current()].revision;
        } catch { /* Keep local drafts through reconnect. */ }
      }
    } finally { editing = false; render(); }
  }

  async function commit() {
    const mode = current();
    if (!Object.hasOwn(drafts, mode)) return;
    const sent = text();
    const snapshot = await api('/api/pi/draft', { method: 'POST', body: JSON.stringify({
      request_id: requestId(), epoch: state.epoch, mode, text: sent,
      expected_revision: revisions[mode] ?? state.buffers[mode].revision }) });
    if (drafts[mode] === sent) { delete drafts[mode]; persist(); }
    applyState(snapshot);
  }

  $('piAnswerPanel').addEventListener('toggle', () => { if ($('piAnswerPanel').open && !document.body.classList.contains('desktop-assistant')) $('signSuggestions').open = false; });
  $('signSuggestions').addEventListener('toggle', () => { if ($('signSuggestions').open && !document.body.classList.contains('desktop-assistant')) $('piAnswerPanel').open = false; });
  $('closePiAnswer').onclick = () => { $('piAnswerPanel').open = false; $('piAnswerToggle').focus(); };
  for (const [id, direction] of [['piAnswerScrollUp', -1], ['piAnswerScrollDown', 1]]) {
    $(id).onclick = () => {
      const content = $('piAnswerPanel').querySelector('.pi-answer-content');
      content.scrollBy({top: direction * Math.max(80, content.clientHeight * .8), behavior:'instant'});
    };
  }
  const assistant = mountAssistant({api, getState: () => ({pi: state, microphone}), getText: text, commit, applyState, run, toast,
    onTaskChange: render,
    connected: () => online,
    available: () => online && Boolean(state?.enabled) && !editing});
  $('sentenceInput').addEventListener('input', () => {
    lastAppend = null;
    keepDraft($('sentenceInput').value); render();
  });
  $('applyBtn').onclick = () => run(commit);
  function editDraft(change) {
    if (!state?.enabled || editing) return;
    const mode = current();
    if (!Object.hasOwn(drafts, mode)) revisions[mode] = state.buffers[mode].revision;
    drafts[mode] = change(text()).slice(0, 2000); persist(); render();
    if (online) return run(commit);
  }
  $('clearDraftBtn').onclick = () => editDraft(() => '');
  for (const [id, change] of [['spaceBtn', s => s + ' '], ['backspaceBtn', s => Array.from(s).slice(0, -1).join('')], ['clearBtn', () => '']]) {
    $(id).onclick = () => {
      if (id === 'clearBtn' && text() && !confirm('Xóa nội dung của chế độ này?')) return;
      return editDraft(change);
    };
  }
  $('askBtn').onclick = () => {
    if (!state || current() !== 'ai' || $('askBtn').disabled) return;
    return run(async () => {
      await commit();
      applyState(await api('/api/pi/question', { method: 'POST', body: JSON.stringify({
        request_id: requestId(), epoch: state.epoch, ...assistant.payload(text()), read_results: false }) }));
    });
  };
  $('saveBtn').onclick = () => run(async () => {
    if (!text().trim()) throw new Error('Chưa có nội dung để lưu.');
    await api('/api/history', { method: 'POST', body: JSON.stringify({ request_id: requestId(), kind: 'text', text: text() }) });
    toast('Đã lưu nội dung.');
  });
  $('speakBtn').onclick = () => {
    if (!state || current() !== 'ai' || $('speakBtn').disabled) return;
    return run(async () => {
      await commit();
      applyState(await api('/api/pi/speech', { method: 'POST', body: JSON.stringify({
        request_id: requestId(), epoch: state.epoch, text: text() }) }));
    });
  };

  return {
    captionAction(caption) {
      if (caption?.id === autoCaption && autoCaption) return 'Đã thêm vào câu';
      if (signMode !== 'single') return signMode === 'paused' ? 'Đã tạm dừng' : 'Ghép liên tục';
      return '';
    },
    appendCaption(caption) {
      if (!this.captionAction(caption)) return assistant.appendCaption(caption);
    },
    get active() { return true; },
    apply(next) {
      if (!next.pi) { $('piModeStatus').textContent = 'Cần cập nhật backend SignAssist AI.'; return; }
      if (state?.instance === next.pi.instance && next.pi.version < state.version) return;
      if (state?.instance !== next.pi.instance) seenCaption = next.pi.caption?.id;
      state = next.pi; camera = next.camera; microphone = next.microphone;
      collect(next); render();
    },
    connection(value) {
      if (!value) seenCaption = state?.caption?.id;
      online = value; render();

    },
    render
  };
}
