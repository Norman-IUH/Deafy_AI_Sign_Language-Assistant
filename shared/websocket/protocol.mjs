export function websocketUrl(base) {
  const url = new URL(base);
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Địa chỉ Pi phải dùng HTTP hoặc HTTPS.');
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/ws';
  url.search = ''; url.hash = '';
  return url.href;
}

export function parsePacket(data) {
  try {
    const packet = JSON.parse(data);
    if (packet?.type === 'state' && packet.state && typeof packet.state.sentence === 'string'
      && Number.isInteger(packet.state.sentence_revision) && packet.state.ai && packet.state.camera && packet.state.recognition) return packet;
  } catch { /* Ignore invalid messages; heartbeat will reconnect if snapshots stop. */ }
  return null;
}
