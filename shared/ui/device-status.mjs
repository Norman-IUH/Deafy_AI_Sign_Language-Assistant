export function deviceStatus(state, online) {
  if (!online) return {microphoneStatus:'Chưa xác minh · mất kết nối Pi', mqttStatus:'Chưa xác minh', espStatus:'Chưa xác minh', smartHomeStatus:'Mất kết nối Pi'};
  const pi = state?.pi, mic = state?.microphone;
  const labels = {idle:'Chưa thu', connecting:'Đang chuẩn bị', recording:'Đang nghe', processing:'Đang nhận dạng', done:'Đã nhận dạng', cancelled:'Đã dừng'};
  const replies = [pi?.speech, pi?.iot].filter(Boolean);
  const failure = replies.find(reply => reply.error);
  const active = replies.find(reply => ['ACK','PLAYING'].includes(reply.status));
  const esp = !pi?.mqtt.connected ? 'Chưa xác minh · MQTT chưa nối'
    : failure?.error || (active ? `ESP32 phản hồi ${active.status}`
      : replies.some(reply => reply.status === 'DONE') ? 'Đã xác nhận lệnh gần nhất (DONE)' : 'Chưa có phản hồi lệnh');
  return {
    microphoneStatus: mic?.error || `${mic?.source || 'Micro Pi'} · ${labels[mic?.status] || 'Chưa kiểm tra'}`,
    mqttStatus: pi?.mqtt.connected ? 'Đã kết nối broker' : pi?.mqtt.message || 'Chưa cấu hình',
    espStatus: esp,
    smartHomeStatus: pi?.iot.error || (pi?.iot.status === 'DONE' ? 'Lệnh gần nhất đã được ESP xác nhận' : 'Trạng thái đèn/quạt cần ESP xác nhận'),
  };
}
