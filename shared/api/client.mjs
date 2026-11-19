export const requestId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');

// Read the destination once so a retry cannot send a pending command to a different Pi.
export function createApi(getConnection, fetcher = (...args) => fetch(...args)) {
  return async function api(path, options = {}) {
    const { base, token } = getConnection();
    if (!base) throw new Error('Nhập địa chỉ Raspberry Pi trong Cài đặt để kết nối.');
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetcher(base + path, { ...options, signal: controller.signal,
          headers: { ...options.headers, ...(options.body ? { 'Content-Type': 'application/json' } : {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          const issue = new Error(typeof data.detail === 'string' ? data.detail : `Yêu cầu không thành công (${response.status}).`);
          issue.status = response.status;
          throw issue;
        }
        return options.image ? await response.blob() : await response.json();
      } catch (issue) {
        if (issue.status) throw issue;
        // The serialized body, including its request ID, stays identical on retry.
        if (attempt === 0 && options.body) continue;
        throw new Error('Không liên lạc được máy chủ. Kiểm tra Wi-Fi và địa chỉ Pi; bản nháp vẫn được giữ.');
      } finally { clearTimeout(timer); }
    }
  };
}
