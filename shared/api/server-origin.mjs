export function serverOrigin(value, native = false) {
  const text = value.trim();
  if (!text) {
    if (native) throw new Error('Nhập IP LAN hoặc hostname Raspberry Pi.');
    return '';
  }
  const url = new URL(text);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Dùng địa chỉ HTTP/HTTPS gốc của Pi, kèm cổng backend (8001).');
  }
  if (native && /^(localhost|127\..*|\[?::1\]?|0\.0\.0\.0)$/i.test(url.hostname)) {
    throw new Error('Trên điện thoại, hãy dùng IP LAN hoặc hostname Raspberry Pi; không dùng localhost.');
  }
  return url.origin;
}
