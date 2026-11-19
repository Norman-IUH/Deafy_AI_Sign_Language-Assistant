export function mountLearning(api, applyState, toast) {
  const $ = id => document.getElementById(id);
  const dialog = $('learningCorrection');
  const pretty = label => label.replaceAll('_', ' ');
  const statusName = { pending: 'Chờ duyệt', approved: 'Đã duyệt', rejected: 'Đã loại', trained: 'Đã huấn luyện' };
  let latest, current, editing, dismissed, online, saving, offset = 0;

  function render(state, connected) {
    latest = state;
    current = state?.learning;
    online = connected;
    if (!current?.session || !online) {
      editing = null;
      if (dialog.open) dialog.close();
    }
    $('learningSettings').hidden = !current;
    if (!saving) $('learningEnabled').checked = Boolean(current?.session);
    $('learningEnabled').disabled = !online || Boolean(saving);
    $('learningModel').textContent = state?.ai?.model
      ? `${state.ai.model.name} · ${state.ai.model.version} · ${state.ai.model.sha256.slice(0, 12)}`
      : 'Bật camera để xem phiên bản model đang dùng.';
    const evaluation = state?.ai?.model?.evaluation;
    if (evaluation) $('learningModel').textContent += ` · Macro F1 ${(evaluation.baseline * 100).toFixed(1)}% → ${(evaluation.candidate * 100).toFixed(1)}%`;
    const candidate = current?.candidate;
    $('learningFeedback').hidden = !online || !current?.session || !candidate || candidate.id === dismissed;
    $('learningPrediction').textContent = candidate
      ? `${pretty(candidate.label)}${Number.isFinite(candidate.confidence) ? ` · ${Math.round(candidate.confidence * 100)}%` : ''}`
      : '';
    for (const id of ['learningCorrect', 'learningWrong']) $(id).disabled = !candidate || Boolean(saving);
    $('learningSave').disabled = !editing || !$('learningLabel').value || Boolean(saving);
    for (const id of ['learningRefresh', 'learningExport', 'learningBackup']) $(id).disabled = !online;
  }

  async function post(path, data, notice) {
    if (!online || saving) return false;
    saving = true;
    render(latest, online);
    try {
      const snapshot = await api(path, { method: 'POST', body: JSON.stringify(data) });
      editing = null;
      if (dialog.open) dialog.close();
      applyState(snapshot);
      return true;
    } catch (issue) {
      if (notice) $(notice).textContent = issue.message;
      else toast(issue.message);
      return false;
    } finally {
      saving = false;
      render(latest, online);
    }
  }

  async function confirm(candidate, label) {
    if (!candidate || !label) return;
    if (await post('/api/learning/feedback', { event: candidate.id, label }, editing ? 'learningNotice' : null))
      toast('Đã lưu mẫu – Chờ duyệt');
  }
  $('learningEnabled').onchange = async event => {
    const enabled = event.target.checked;
    if (await post('/api/learning/session', { enabled }, 'learningSettingsNotice')) {
      $('learningSettingsNotice').textContent = enabled ? 'Đã bắt đầu phiên thu mẫu.' : 'Đã kết thúc phiên thu mẫu.';
    }
  };
  $('learningCorrect').onclick = () => confirm(current?.candidate, current?.candidate?.label);
  $('learningDismiss').onclick = () => {
    dismissed = current?.candidate?.id;
    render(latest, online);
  };
  $('learningWrong').onclick = async () => {
    const candidate = current?.candidate;
    if (!candidate || saving) return;
    saving = true;
    render(latest, online);
    try {
      await api('/api/learning/freeze', { method: 'POST', body: JSON.stringify({ event: candidate.id }) });
      if (!online || !current?.session) return;
      editing = candidate;
      const options = editing.labels.filter(label => label.toLowerCase() !== editing.label.toLowerCase());
      $('learningLabel').replaceChildren(new Option('Chọn nhãn…', ''), ...options.map(label => new Option(pretty(label), label)));
      $('learningFrozen').textContent = `Đang sửa mẫu đã giữ: ${pretty(candidate.label)}.`;
      $('learningNotice').textContent = '';
      dialog.showModal();
      $('learningLabel').focus();
    } catch (issue) {
      toast(issue.message);
    } finally {
      saving = false;
      render(latest, online);
    }
  };
  $('learningLabel').onchange = () => render(latest, online);
  $('learningCancel').onclick = () => dialog.close();
  dialog.addEventListener('close', () => {
    const event = editing?.id;
    editing = null;
    render(latest, online);
    if (event && online) api(`/api/learning/freeze/${event}`, { method: 'DELETE' }).catch(() => {});
  });
  $('learningSave').onclick = () => confirm(editing, $('learningLabel').value);

  async function inventory() {
    const data = await api(`/api/learning/samples?offset=${offset}`);
    $('learningCounts').textContent = data.counts.map(row => `${pretty(row.label)} · ${statusName[row.status]} ${row.total}`).join(' | ') || 'Chưa có mẫu.';
    $('learningItems').replaceChildren(...data.items.map(row => {
      const item = document.createElement('li');
      const text = document.createElement('p');
      text.textContent = `${pretty(row.label)} · ${statusName[row.status]} · ${row.captured_at}` +
        (row.label !== row.predicted ? ` · AI đoán ${pretty(row.predicted)}` : '');
      item.append(text);
      const actions = document.createElement('div');
      actions.className = 'speaker-actions';
      const choices = [['approved', 'Duyệt'], ['rejected', 'Loại'], ['delete', 'Xóa']];
      if (row.status === 'approved') choices.push(['trained', 'Đánh dấu đã huấn luyện']);
      for (const [action, label] of choices) {
        if (row.status === action || row.status === 'trained') continue;
        const button = document.createElement('button');
        button.className = 'button secondary';
        button.type = 'button';
        button.textContent = label;
        button.onclick = () => run(async () => {
          if (action === 'delete' && !window.confirm('Xóa mẫu này khỏi kho dữ liệu?')) return;
          await api(`/api/learning/samples/${row.id}`, { method: 'POST', body: JSON.stringify({ action }) });
          await inventory();
        });
        actions.append(button);
      }
      item.append(actions);
      return item;
    }));
    $('learningPages').hidden = !offset && data.items.length < 50;
    $('learningPrevious').disabled = offset === 0;
    $('learningNext').disabled = data.items.length < 50;
  }

  async function run(task) {
    if (!online) return;
    try { await task(); }
    catch (issue) { $('learningSettingsNotice').textContent = issue.message; }
  }
  $('learningRefresh').onclick = () => run(inventory);
  $('learningPrevious').onclick = () => run(() => { offset -= 50; return inventory(); });
  $('learningNext').onclick = () => run(() => { offset += 50; return inventory(); });
  for (const [id, backup] of [['learningExport', false], ['learningBackup', true]]) {
    $(id).onclick = () => run(async () => {
      const blob = await api(`/api/learning/export?backup=${backup}`, { image: true });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = backup ? 'gesture-backup.json' : 'gesture-approved.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });
  }
  return render;
}
