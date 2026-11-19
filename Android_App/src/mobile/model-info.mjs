export function piModelMatch(manifest, pi) {
  if (!pi?.sha256 || !pi.classes) return null;
  return pi.sha256 === manifest.sha256 && pi.num_classes === manifest.labels.length &&
    Object.keys(pi.classes).length === manifest.labels.length &&
    manifest.labels.every((label,index) => pi.classes[label.id] === index);
}

export function mountModelInfo(host, manifest, packagedAt) {
  const panel = document.createElement('section');
  panel.className = 'settings-section';
  const heading = document.createElement('h2');
  heading.textContent = 'Thông tin AI';
  const list = document.createElement('dl');
  const rows = {};
  for (const [key,name] of Object.entries({model:'Model trên Android',version:'Phiên bản',source:'Nguồn checkpoint',
    packaged:'Đóng gói',runtime:'Runtime',shape:'Đầu vào',labels:'Số nhãn',pi:'Model trên Pi',match:'Đối chiếu với Pi'})) {
    const row = document.createElement('div'), term = document.createElement('dt'), value = document.createElement('dd');
    term.textContent = name; row.append(term,value); list.append(row); rows[key] = value;
  }
  const prep = manifest.preprocessing;
  rows.model.textContent = 'Model 2 · Cục bộ';
  rows.version.textContent = manifest.version;
  rows.source.textContent = manifest.checkpoint_source;
  rows.source.title = manifest.sha256;
  rows.packaged.textContent = new Date(packagedAt).toLocaleString('vi-VN');
  rows.shape.textContent = `${prep.sequence_length} × ${prep.input_size} · float32`;
  rows.labels.textContent = manifest.labels.length;
  rows.runtime.textContent = 'Chưa nạp · Bật camera để kiểm tra';
  panel.append(heading,list);
  host.before(panel);
  return {
    runtime(status, engine) { rows.runtime.textContent = engine || status; },
    pi(online, model) {
      rows.pi.textContent = !online ? 'Ngoại tuyến' : model ? `${model.name} · ${model.version}` : 'Pi chưa báo model đã nạp';
      const match = online ? piModelMatch(manifest,model) : null;
      rows.match.textContent = match === null ? 'Chưa đối chiếu trực tiếp' : match ? 'Khớp hash checkpoint và thứ tự nhãn' : 'Khác checkpoint hoặc thứ tự nhãn';
    },
  };
}
