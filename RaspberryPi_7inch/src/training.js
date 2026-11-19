export function mountCourseTraining(api) {
  const $ = id => document.getElementById(id);
  const panel = $('courseTraining');
  const base = '/api/training';
  const stages = { prepared: 'Đã chuẩn bị', queued: 'Chờ laptop nhận lượt', running: 'Đang huấn luyện',
    complete: 'Đã nhập kết quả', failed: 'Huấn luyện thất bại' };
  const checks = { pending: 'Chưa kiểm tra', running: 'Đang kiểm tra', passed: 'Đạt', failed: 'Không đạt' };
  let latest, busy = false, fetching = false, selected, canUse = false;

  function render() {
    const data = latest;
    const job = data?.job;
    const version = data?.versions.find(item => item.id === selected);
    const working = data?.versions.some(item => item.pi_check === 'running' || item.operation === 'running');
    const available = canUse && !busy && Boolean(data);
    const running = job && ['queued', 'running'].includes(job.status);
    const modelMatches = version && version.baseline === data.baseline;
    $('trainingPrepare').disabled = !available || !data?.ready || running;
    $('trainingStart').disabled = !available || !data?.agent_online || job?.status !== 'prepared';
    $('trainingDownload').disabled = !available || !job;
    $('trainingReset').hidden = !available || !(job?.status === 'failed' || running && !data.agent_online);
    $('trainingImport').disabled = !available || !job || !['prepared', 'failed'].includes(job.status);
    $('trainingVersion').disabled = !available || !data?.versions.length;
    $('trainingEvaluation').disabled = !available || !version;
    $('trainingCheck').disabled = !available || !version?.quality || version.active || !modelMatches || working;
    $('trainingActivate').disabled = $('trainingCheck').disabled || version?.pi_check !== 'passed';
    $('trainingRollback').disabled = !available || !version?.active || working;
    if (!data) return;
    const readiness = data.ready ? 'Sẵn sàng đánh giá' : data.can_trial ? 'Có mẫu để thử, chưa đủ bộ đánh giá' : 'Chưa đủ mẫu';
    const count = status => data.counts.filter(item => item.status === status).reduce((sum, item) => sum + item.total, 0);
    $('trainingData').textContent = `${count('pending')} chờ duyệt · ${count('approved')} đã duyệt · ${count('rejected')} đã loại. ${readiness} · ${data.approved_for_model} mẫu đã duyệt cho model hiện tại · ${data.sessions} phiên. Gợi ý ${data.target_per_label} mẫu mỗi ký hiệu cần cải thiện. Cần 3 phiên riêng, trong đó 2 phiên có ít nhất 2 mẫu mỗi nhãn để đánh giá.`;
    $('trainingJob').textContent = [data.agent_online ? 'Laptop đã kết nối' : 'Laptop chưa kết nối',
      job && stages[job.status], job?.status === 'running' && `${job.epoch}/${job.epochs} vòng`,
      job?.error, version && `Kiểm tra Pi: ${checks[version.pi_check]}`,
      version?.operation === 'running' && 'Đang đổi model', version?.error].filter(Boolean).join(' · ');
    const bar = $('trainingProgress');
    bar.hidden = job?.status !== 'running';
    if (!bar.hidden) {
      bar.max = job.epochs;
      bar.value = job.epoch;
    }
  }

  async function refresh() {
    if (fetching) return;
    fetching = true;
    try {
      const data = await api(base + '/status');
      if (JSON.stringify(latest?.coverage) !== JSON.stringify(data.coverage)) {
        $('trainingCoverage').replaceChildren(...Object.entries(data.coverage).map(([label, count]) => {
          const item = document.createElement('li');
          item.textContent = `${label.replaceAll('_', ' ')} · ${count}`;
          return item;
        }));
      }
      if (JSON.stringify(latest?.versions) !== JSON.stringify(data.versions)) {
        if (!data.versions.some(item => item.id === selected)) {
          selected = data.versions.find(item => item.active)?.id ?? data.versions[0]?.id;
        }
        $('trainingVersion').replaceChildren(...data.versions.map(item =>
          new Option(`${item.id.slice(0, 8)} · ${new Date(item.created * 1000).toLocaleDateString('vi-VN')}${item.active ? ' · Đang dùng' : ''}`, item.id)));
        $('trainingVersion').value = selected ?? '';
      }
      if (!canUse && !busy) $('trainingNotice').textContent = '';
      latest = data;
      canUse = true;
    } catch (error) {
      canUse = false;
      $('trainingNotice').textContent = error.message;
    } finally {
      fetching = false;
      render();
    }
  }

  async function perform(action) {
    if (busy || !canUse) return;
    busy = true;
    $('trainingNotice').textContent = '';
    render();
    try {
      await action();
      await refresh();
    } catch (error) {
      $('trainingNotice').textContent = error.message;
    } finally {
      busy = false;
      render();
    }
  }

  const post = (path, body) => perform(() => api(base + path, { method: 'POST', body }));
  const jobPath = () => `/jobs/${latest.job.id}`;
  $('trainingPrepare').onclick = () => post('/prepare');
  $('trainingStart').onclick = () => post(jobPath() + '/start');
  $('trainingReset').onclick = () => post(jobPath() + '/reset');
  $('trainingDownload').onclick = () => perform(async () => {
    const id = latest.job.id;
    const blob = await api(base + jobPath() + '/dataset', { image: true });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `deafy-${id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  $('trainingImport').onchange = event => {
    const file = event.target.files[0];
    event.target.value = '';
    if (file) post(jobPath() + '/import', file);
  };
  $('trainingVersion').onchange = event => {
    selected = event.target.value;
    $('trainingReport').hidden = true;
    render();
  };
  $('trainingEvaluation').onclick = () => perform(async () => {
    const target = $('trainingReport');
    if (!target.hidden) {
      target.hidden = true;
      return;
    }
    const { report, profile } = await api(`${base}/versions/${selected}/evaluation`);
    const { baseline, candidate } = report;
    const percent = value => (value * 100).toFixed(1) + '%';
    const rows = [
      report.trained_at && `Ngày train: ${new Date(report.trained_at).toLocaleString('vi-VN')}`,
      `Cổng chất lượng: ${report.passes_quality_gate ? 'Đạt' : 'Không đạt'} · Bộ test độc lập: ${report.samples.test} mẫu`,
      `Dữ liệu gốc đã khớp: ${report.original_available}/${report.original_expected} · Train: ${report.samples.train} mẫu`,
      `Accuracy: ${percent(baseline.accuracy)} → ${percent(candidate.accuracy)}`,
      `Macro F1: ${percent(baseline.macro_f1)} → ${percent(candidate.macro_f1)}`,
      profile && `Pi p95: ${profile.baseline.p95_ms.toFixed(2)} → ${profile.candidate.p95_ms.toFixed(2)} ms · RAM: ${profile.baseline.rss_mib.toFixed(0)} → ${profile.candidate.rss_mib.toFixed(0)} MiB`,
      'Theo ký hiệu · Precision / Recall / F1, model trước → model mới',
      ...report.labels.map(label => {
        const metrics = group => ['precision', 'recall', 'f1'].map(key => percent(group.classes[label][key])).join(' / ');
        return `${label.replaceAll('_', ' ')} (${candidate.classes[label].support} mẫu) · ${metrics(baseline)} → ${metrics(candidate)}`;
      }),
    ].filter(Boolean);
    target.replaceChildren(...rows.map(row => {
      const p = document.createElement('p');
      p.className = 'helper';
      p.textContent = row;
      return p;
    }));
    target.hidden = false;
  });
  $('trainingCheck').onclick = () => post(`/versions/${selected}/check`);
  $('trainingActivate').onclick = () => {
    if (confirm('Áp dụng model mới? Camera sẽ gián đoạn ngắn trong lúc Pi kiểm tra lại.')) {
      post(`/versions/${selected}/activate`);
    }
  };
  $('trainingRollback').onclick = () => {
    if (confirm('Khôi phục model trước? Camera sẽ gián đoạn ngắn.')) post(`/versions/${selected}/rollback`);
  };
  const visible = () => panel.open && panel.getClientRects().length > 0;
  panel.ontoggle = () => { if (visible()) refresh(); };
  setInterval(() => { if (visible() && !busy) refresh(); }, 4000);
}
