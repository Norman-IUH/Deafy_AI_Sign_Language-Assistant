import { requestId } from '../api/client.mjs';
import {mountLocation} from './location.mjs';

// Shared Pi/Android controls use the same draft and assistant endpoints.
export function mountAssistant({ api, getState, getText, commit, applyState, run, available, connected = available, onTaskChange, toast }) {
  const $ = id => document.getElementById(id);
  const sharedLocation=mountLocation({api,getState,applyState,connected});
  const speechDraft = () => ($('micTranscript').hidden ? getState()?.transcript || '' : $('micTranscript').value).trim();
  const readable = ai => ai.status === 'done' && Boolean(ai.answer) && ai.task !== 'rewrite'
    && (ai.task !== 'search' || ai.search?.items?.length > 0)
    && (ai.task !== 'weather' || ai.search?.status === 'ok');
  let vocabulary = [], choicesKey, placesKey;
  const taskChanged = () => {
    const label = $('askLabel') || $('mobileAskLabel');
    label.textContent = {auto:'Gửi',rewrite:'Ghép câu',question:'Hỏi AI',search:'Tìm kiếm',weather:'Thời tiết'}[$('assistantTask').value];
  };
  $('assistantTask').onchange = () => { taskChanged(); onTaskChange(); }; taskChanged();
  $('editAISentence').onclick = () => { $('sentenceInput').focus(); };
  function payload(text) {
    return {text, task: $('assistantTask').value, read_results: $('assistantTask').value !== 'rewrite' && $('ttsEnabled').checked,
      location_source: $('useManualReference').checked ? 'manual' : 'phone'};
  }
  $('useAIProposal').onclick = () => run(async () => {
    const answer = getState().pi.ai;
    if (!answer.proposal || getText() !== answer.source) throw Error('Câu gốc đã đổi. Hãy ghép câu lại để giữ đúng ý.');
    await commit();
    const pi = getState().pi;
    if (pi.ai.request_id !== answer.request_id || pi.buffers.ai.text !== answer.source) throw Error('Câu đã thay đổi trên thiết bị khác.');
    applyState(await api('/api/pi/draft', {method:'POST', body:JSON.stringify({request_id:requestId(), epoch:pi.epoch,
      mode:'ai', text:answer.proposal, expected_revision:pi.buffers.ai.revision})}));
  });
  $('readAIResult').onclick = () => run(async () => {
    const pi = getState().pi;
    if (!readable(pi.ai)) throw Error('Chưa có kết quả hợp lệ để đọc.');
    applyState(await api('/api/pi/speech', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:pi.epoch,text:(pi.ai.speech_text || pi.ai.answer).slice(0,2000)})}));
  });
  $('useSpeechDraft').onclick = () => run(async () => {
    const text = speechDraft();
    if (!text) throw Error('Chưa có lời nói để dùng.');
    await commit();
    const pi = getState().pi;
    applyState(await api('/api/pi/draft', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:pi.epoch,
      mode:'ai',text,expected_revision:pi.buffers.ai.revision})}));
  });
  async function select(label, operation, candidate) {
    await commit();
    const pi = getState().pi;
    applyState(await api('/api/pi/select', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch:pi.epoch,
      candidate_id:candidate,expected_revision:pi.buffers.ai.revision,label,operation})}));
  }
  $('removeLastSign').onclick = () => {
    const pi = getState()?.pi;
    return run(() => select(pi.last_selection.label, 'delete_last', pi.suggestion?.id ?? null));
  };
  function render() {
    sharedLocation.render();
    const pi = getState()?.pi;
    if (!pi) return;
    const mic = getState()?.microphone;
    const active = pi.ai.status === 'processing' ? pi.provider_state?.active : pi.ai.provider || pi.provider_state?.active || pi.provider;
    const label = !connected() ? 'Ngoại tuyến · chưa kết nối Pi' : pi.ai.task === 'weather' ? 'Dữ liệu thời tiết: Open-Meteo' : pi.ai.task === 'search' ? 'Tìm địa điểm'
      : active === 'groq' ? 'AI dự phòng: Groq' : active === 'gemini' ? 'Gemini' : active === 'mock' ? 'Bản thử MOCK' : 'Ngoại tuyến · giữ câu gốc';
    $('assistantProvider').textContent = label;
    const ai = pi.ai, busy = pi.assistant_version !== 1 || !available() || ai.status === 'processing' || ['processing','pending','ACK','PLAYING'].includes(pi.speech.status)
      || ['connecting','recording','processing'].includes(mic?.status);
    $('useSpeechDraft').disabled = busy || ['connecting','recording','processing'].includes(mic?.status)
      || !speechDraft();
    $('assistantTask').disabled = busy;
    const locationTask = ['search','weather'].includes($('assistantTask').value) ||
      ($('assistantTask').value === 'auto' && ['search','weather'].includes(ai.task));
    const searching = $('assistantTask').value === 'search' || $('assistantTask').value === 'auto' && ai.task === 'search';
    const manual = !searching && $('useManualReference').checked;
    const location = pi.location;
    $('activeLocation').hidden = !locationTask || ai.task === 'weather' && ai.search?.status === 'ok';
    $('activeLocation').textContent = manual
      ? location?.manual_ready ? 'Đang dùng vị trí tham chiếu' : 'Cập nhật vị trí tham chiếu trong Cài đặt.'
      : location?.phone_ready ? 'Đang dùng GPS đã chia sẻ' : 'Mở Cài đặt trên iPhone để chia sẻ lại GPS.';
    $('assistantOriginal').textContent = ai.task === 'rewrite' && ai.source ? 'Câu gốc: ' + ai.source : '';
    $('assistantProposal').textContent = ai.proposal ? 'Câu AI đề xuất: ' + ai.proposal : '';
    $('useAIProposal').hidden = !ai.proposal;
    $('useAIProposal').disabled = busy || !ai.proposal || getText() !== ai.source;
    $('readAIResult').disabled = busy || !$('ttsEnabled').checked || !readable(ai);
    $('readAIResult').textContent = ai.task === 'search' ? 'Đọc lại danh sách' : 'Đọc kết quả qua ESP32';
    $('readAIResult').title = !connected() ? 'Chưa kết nối backend Pi' : busy ? 'Chờ yêu cầu hoặc âm thanh hiện tại hoàn tất'
      : !$('ttsEnabled').checked ? 'Bật giọng nói trong Cài đặt để phát loa'
      : ai.task === 'rewrite' ? 'Câu ghép cần được bạn kiểm tra và xác nhận trước khi phát'
      : !readable(ai) ? 'Chưa có kết quả hợp lệ để đọc' : '';
    $('readAIHint').textContent = $('readAIResult').disabled ? $('readAIResult').title : 'Đọc lại bằng một yêu cầu mới; kết quả không tự phát lại khi kết nối lại.';
    $('editAISentence').disabled = !available();
    const searchedAt = ai.search?.searched_at ? new Date(ai.search.searched_at) : null;
    const searchedTime = searchedAt && Number.isFinite(searchedAt.getTime()) && ['ok', 'empty'].includes(ai.search.status)
      ? ` · ${ai.search.cached ? 'Đã lưu lúc' : 'Tìm lúc'} ${searchedAt.toLocaleTimeString('vi-VN', {timeZone:'Asia/Ho_Chi_Minh',hour:'2-digit',minute:'2-digit'})}` : '';
    $('placesStatus').textContent = ai.task === 'weather' ? '' : ai.task === 'search' && ai.status === 'processing' ? 'Đang tìm địa điểm…'
      : ai.task === 'search' && ai.error ? ai.error : ai.search ? ai.search.message + searchedTime : '';
    const resultKey = JSON.stringify([ai.task, ai.status, ai.error, ai.search, busy, $('ttsEnabled').checked]);
    const geoapify = ai.search?.source === 'Geoapify';
    $('osmAttribution').hidden = ai.task !== 'search' || ai.search?.status !== 'ok' || !(geoapify || ai.search?.source?.includes('OpenStreetMap'));
    $('geoapifyAttribution').hidden = !geoapify;
    if (placesKey !== resultKey) {
    placesKey = resultKey;
    renderWeather($('weatherResult'), ai);
    const rows = (ai.search?.items || []).map((item, index) => {
      const article = document.createElement('article'); article.className = 'place-result';
      const name = document.createElement('strong'); name.textContent = `${index + 1}. ${item.name}`;
      const address = document.createElement('p'); address.textContent = item.address;
      const read = document.createElement('button'); read.className = 'button secondary'; read.textContent = `Đọc địa điểm ${index + 1}`;
      read.disabled = busy || !$('ttsEnabled').checked;
      const resultId = ai.request_id, epoch = pi.epoch;
      read.onclick = () => run(async () => {
        const current = getState().pi;
        if (current.epoch !== epoch || current.ai.request_id !== resultId) throw Error('Kết quả đã thay đổi. Chọn lại địa điểm.');
        applyState(await api('/api/pi/speech', {method:'POST',body:JSON.stringify({request_id:requestId(),epoch,
          text:`${item.name}. Địa chỉ: ${item.address}.`})}));
      });
      const distance = document.createElement('small');
      if (Number.isFinite(item.distance_m)) distance.textContent = `${item.distance_m.toLocaleString('vi-VN')} m theo đường thẳng`;
      article.append(name, address, distance, read); return article;
    });
    $('placesResults').replaceChildren(...rows);
    }
    $('mapsFallback').hidden = !ai.search?.maps_url || Boolean(ai.search?.items?.length);
    if (ai.search?.maps_url) {
      $('mapsFallback').href = ai.search.maps_url;
      $('mapsFallback').textContent = ai.search.source?.includes('OpenStreetMap')
        ? 'Mở OpenStreetMap để tìm thủ công'
        : 'Tìm trực tiếp trên Google Maps (ngoài ứng dụng)';
    }
    const normalize = text => text.toLocaleLowerCase('vi').normalize('NFD').replace(/\p{Diacritic}/gu, '').replaceAll('đ','d').trim();
    const query = normalize($('signSearch').value);
    const ranked = !query && pi.suggestion?.candidates?.length ? pi.suggestion.candidates : [];
    const classes = getState()?.ai?.ready && getState().ai.model?.classes;
    const availableLabels = classes ? new Set(Object.keys(classes).map(label => label.toLowerCase())) : null;
    const items = ranked.length ? ranked : vocabulary.filter(item => (!availableLabels || availableLabels.has(item.label)) && (!query || normalize(item.text).includes(query)));
    $('signCandidateHeading').textContent = ranked.length ? 'Top 3 từ softmax mô hình · điểm chưa hiệu chuẩn, hãy chọn lại nếu sai'
      : 'Chọn thủ công từ bộ nhãn hiện có · không phải Top 3 của mô hình';
    $('removeLastSign').disabled = busy || !pi.last_selection || pi.last_selection.revision !== pi.buffers.ai.revision;
    const key = JSON.stringify([items, pi.suggestion?.id, pi.buffers.ai.revision, busy]);
    if (key === choicesKey) return;
    choicesKey = key;
    $('signChoices').replaceChildren(...items.map(item => {
      const button = document.createElement('button'); button.className = 'button secondary';
      button.textContent = item.text + (ranked.length ? ` · ${(item.confidence*100).toFixed(0)}%` : ''); button.disabled = busy;
      const candidate = pi.suggestion?.id ?? null;
      button.onclick = () => run(() => select(item.label, $('signEditAction').value, candidate));
      return button;
    }));
    $('signSuggestionHint').textContent = items.length ? 'Chọn từ đúng. Không tự gửi AI hoặc phát loa.' : 'Không có trong bộ nhãn. Bạn vẫn có thể nhập câu trực tiếp.';
    $('signSuggestionToggle').textContent = pi.suggestion ? 'Sửa ký hiệu · Mới' : 'Sửa ký hiệu';
  }
  $('signSearch').oninput = render;
  $('micTranscript').addEventListener('input', render);
  api('/api/pi/vocabulary').then(data => { vocabulary = data.items; render(); })
    .catch(() => { $('signSuggestionHint').textContent = 'Chưa tải được bộ nhãn từ Pi.'; });
  return {payload, render, appendCaption: caption => run(async () => {
    await select(caption.label, 'append_caption', caption.id);
    toast('Đã thêm vào câu');
  })};
}

function renderWeather(card, ai) {
  card.hidden = ai.task !== 'weather';
  if (card.hidden) return;
  const result = ai.search;
  if (result?.status !== 'ok') {
    card.textContent = ai.status === 'processing' ? 'Đang lấy thời tiết…'
      : ai.error || result?.message || 'Chưa có kết quả thời tiết.';
    return;
  }
  const {current = {}, daily = {}} = result;
  const observed = new Date(result.observed_at || '');
  const updated = Number.isFinite(observed.getTime()) ? new Intl.DateTimeFormat('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit',
  }).format(observed) : '';
  const details = document.createElement('p');
  details.className = 'helper';
  details.textContent = [result.label || 'Vị trí đã chọn', updated && 'Cập nhật ' + updated].filter(Boolean).join(' · ');
  const heading = document.createElement('strong');
  heading.textContent = [`${current.temperature_2m} °C`, result.condition].filter(Boolean).join(' · ');
  const metrics = document.createElement('dl');
  for (const [label, value, unit] of [
    ['Cảm giác như', current.apparent_temperature, '°C'], ['Độ ẩm', current.relative_humidity_2m, '%'],
    ['Khả năng mưa cao nhất hôm nay', daily.precipitation_probability_max, '%'],
    ['Thấp nhất', daily.temperature_2m_min, '°C'], ['Cao nhất', daily.temperature_2m_max, '°C'],
  ]) {
    if (!Number.isFinite(value)) continue;
    const row = document.createElement('div'), name = document.createElement('dt'), number = document.createElement('dd');
    name.textContent = label; number.textContent = `${value} ${unit}`;
    row.append(name, number); metrics.append(row);
  }
  card.replaceChildren(heading, details, metrics);
}
