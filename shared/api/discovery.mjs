import { requestId } from './client.mjs';
import { serverOrigin } from './server-origin.mjs';

export async function verifyPi(origin, token, fetcher = fetch, cryptography = crypto) {
  const url = new URL(serverOrigin(origin, true));
  const parts = url.hostname.split('.').map(Number);
  const local = parts.length === 4 && parts.every(n => Number.isInteger(n) && n >= 0 && n <= 255) &&
    (parts[0] === 10 || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) || (parts[0] === 192 && parts[1] === 168));
  if (!local || url.protocol !== 'http:' || !token) return false;
  const nonce = requestId();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1800);
  try {
    // No Authorization header or cookies go to an unverified advertisement.
    const response = await fetcher(`${url.origin}/api/discovery?kind=api&challenge=${nonce}`,
      { signal: controller.signal, redirect: 'error', credentials: 'omit', cache: 'no-store' });
    if (!response.ok) return false;
    const data = await response.json();
    if (data.service !== 'DAKT-Nc' || data.origin !== url.origin || !Number.isInteger(data.mqtt_port) ||
        data.mqtt_port < 1 || data.mqtt_port > 65535 || !/^[a-f0-9]{64}$/.test(data.proof)) return false;
    const encoder = new TextEncoder();
    const key = await cryptography.subtle.importKey('raw', encoder.encode(token), {name:'HMAC', hash:'SHA-256'}, false, ['verify']);
    const signature = Uint8Array.from(data.proof.match(/../g), b => parseInt(b, 16));
    return await cryptography.subtle.verify('HMAC', key, signature,
      encoder.encode(`deafy-discovery-v1\napi\n${nonce}\n${url.origin}\n${data.mqtt_port}`));
  } finally { clearTimeout(timer); }
}

export async function findPi({token, previous, discover, verify = verifyPi}) {
  if (!token) throw new Error('Nhập mã truy cập Pi một lần trong Cài đặt để ghép nối tự động.');
  if (previous && await verify(previous, token).catch(() => false)) return previous;
  const {origins = []} = await discover();
  for (const origin of [...new Set(origins)].slice(0, 8)) {
    if (await verify(origin, token).catch(() => false)) return origin;
  }
  throw new Error('Chưa tìm thấy Pi đã ghép nối. Kiểm tra Wi-Fi deafy, Deafy AI hoặc dùng địa chỉ thủ công.');
}
