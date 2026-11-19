import { requestId } from '../api/client.mjs';

export function mountSpeaker(api, applyState) {
  const panel = document.getElementById('speakerControls');
  const volume = panel.querySelector('#speakerVolume');
  const gain = panel.querySelector('#speakerGain');
  const mute = panel.querySelector('#speakerMute');
  const notice = panel.querySelector('#speakerNotice');
  const controls = panel.querySelector('fieldset');
  const voiceControls = panel.querySelector('#voiceControls');
  const voice = panel.querySelector('#speakerVoice');
  const speed = panel.querySelector('#speakerSpeed');
  const preview = panel.querySelector('#speakerPreview');
  const testTone = panel.querySelector('#speakerTestTone');
  const testOffline = panel.querySelector('#speakerTestOffline');
  const allowOffline = panel.querySelector('#speakerAllowOffline');
  const voiceNotice = panel.querySelector('#speakerVoiceNotice');
  const speedLabel = () => { panel.querySelector('#speakerSpeedValue').textContent = (Number(speed.value) / 100).toFixed(2) + '×'; };
  const defaults = { volume: 60, gain_db: 0, muted: false };
  let settings, shown, online, saving, pi, voicesShown, voiceShown, previewId, previewSending, previewError;

  function labels() {
    panel.querySelector('#speakerVolumeValue').textContent = volume.value + '%';
    panel.querySelector('#speakerGainValue').textContent = gain.value + ' dB';
  }

  function render(next, connected) {
    pi = next;
    settings = pi?.speaker;
    online = connected;
    controls.disabled = !online || !settings || Boolean(saving);
    voiceControls.hidden = !pi?.voices;
    voiceControls.disabled = controls.disabled;
    const catalog = JSON.stringify(pi?.voices);
    if (catalog !== voicesShown) {
      voicesShown = catalog;
      voice.replaceChildren(...(pi?.voices || []).map(item => {
        const option = new Option(item.label + (item.available ? '' : ' · Chưa cấu hình'), item.id);
        option.disabled = !item.available;
        return option;
      }));
      voiceShown = undefined;
    }
    const voiceKey = JSON.stringify([settings?.voice, settings?.speed]);
    if (voiceKey !== voiceShown) {
      voiceShown = voiceKey;
      voice.value = settings?.voice || 'Aoede';
      speed.value = settings?.speed || 100;
      speedLabel();
    }
    const speech = pi?.speech;
    panel.querySelector('#speakerSavedVoice').textContent = settings?.voice ? `Giọng đã lưu: ${settings.voice}` : '';
    panel.querySelector('#speakerActualVoice').textContent = speech?.voice && speech?.engine
      ? `Giọng tạo âm thanh gần nhất: ${speech.voice} · ${speech.engine}`
      : 'Chưa có âm thanh từ lượt hiện tại.';
    const testDisabled = previewSending || !pi?.mqtt?.connected || settings?.muted || !settings?.volume
      || ['processing', 'pending', 'ACK', 'PLAYING'].includes(speech?.status);
    preview.disabled = testDisabled || !voice.value;
    testTone.disabled = testDisabled;
    testOffline.disabled = testDisabled || !pi?.tts?.offline_available;
    panel.querySelector('#speakerOfflineControls').hidden = !Object.hasOwn(settings || {}, 'allow_offline');
    allowOffline.checked = Boolean(settings?.allow_offline);
    panel.querySelector('#speakerTtsAvailability').textContent = pi?.tts
      ? `${pi.tts.message} ${pi.tts.offline_available ? 'eSpeak vi+f3 khả dụng.' : 'Giọng ngoại tuyến chưa khả dụng.'}`
      : '';
    if (previewId && speech?.request_id === previewId) {
      voiceNotice.textContent = speech.error || (speech.status === 'DONE' ? 'Đã phát câu mẫu.' : 'Đang phát thử…');
    } else if (!previewSending) {
      voiceNotice.textContent = previewError || speech?.error || (speech?.fallback_reason ? `${speech.fallback_reason} Đang dùng eSpeak NG ngoại tuyến.` : '');
    }
    const key = settings && JSON.stringify(settings);
    if (key === shown) return;
    shown = key;
    const value = settings || defaults;
    volume.value = value.volume;
    gain.value = value.gain_db;
    mute.textContent = value.muted ? 'Bật tiếng' : 'Tắt tiếng';
    labels();
  }

  async function save(changes) {
    if (!online || !settings || saving) return;
    saving = true;
    controls.disabled = true;
    notice.textContent = 'Đang lưu…';
    try {
      applyState(await api('/api/pi/speaker', {
        method: 'POST', body: JSON.stringify({ request_id: requestId(), ...changes }),
      }));
      notice.textContent = 'Đã lưu. Áp dụng từ lượt phát tiếp theo.';
    } catch (issue) {
      notice.textContent = issue.message;
    } finally {
      saving = false;
      shown = undefined;
      render(pi, online);
    }
  }

  volume.oninput = gain.oninput = labels;
  volume.onchange = () => save({ volume: Number(volume.value) });
  gain.onchange = () => save({ gain_db: Number(gain.value) });
  panel.querySelector('#speakerLower').onclick = () => save({ volume: Math.max(0, settings.volume - 5) });
  panel.querySelector('#speakerRaise').onclick = () => save({ volume: Math.min(100, settings.volume + 5) });
  mute.onclick = () => save({ muted: !settings.muted });
  panel.querySelector('#speakerReset').onclick = () => save(defaults);
  speed.oninput = speedLabel;
  voice.onchange = () => render(pi, online);
  panel.querySelector('#speakerSaveVoice').onclick = () => save({ voice: voice.value, speed: Number(speed.value) });
  panel.querySelector('#speakerResetVoice').onclick = async () => {
    voice.value = 'Aoede';
    speed.value = 100;
    speedLabel();
    await save({ voice: 'Aoede', speed: 100 });
  };
  allowOffline.onchange = () => save({ allow_offline: allowOffline.checked });
  async function playTest(path, options) {
    previewId = requestId();
    previewSending = true;
    previewError = '';
    render(pi, online);
    voiceNotice.textContent = 'Đang chuẩn bị câu mẫu…';
    try {
      applyState(await api(path, {
        method: 'POST', body: JSON.stringify({ request_id: previewId, epoch: pi.epoch, ...options }),
      }));
    } catch (issue) {
      previewError = issue.message;
    } finally {
      previewSending = false;
      render(pi, online);
    }
  }
  preview.onclick = () => playTest('/api/pi/speaker/preview', { voice: voice.value, speed: Number(speed.value) });
  testTone.onclick = () => playTest('/api/pi/speaker/test', { kind: 'tone' });
  testOffline.onclick = () => playTest('/api/pi/speaker/test', { kind: 'offline' });
  return render;
}
