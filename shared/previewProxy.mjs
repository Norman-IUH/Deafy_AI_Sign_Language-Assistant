// Credentials stay in the loopback-only Vite process, never in a browser bundle.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { findPi, verifyPi } from './api/discovery.mjs';

export async function discoverPiOnLan() {
  const python = fileURLToPath(new URL(process.platform === 'win32'
    ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv-pi/bin/python', import.meta.url));
  const script = fileURLToPath(new URL('../backend/lan_discovery_client.py', import.meta.url));
  const {stdout} = await promisify(execFile)(python, [script], {timeout:6000, maxBuffer:16384, windowsHide:true});
  return JSON.parse(stdout);
}

export function previewProxy(env, {discover = discoverPiOnLan, verify = verifyPi} = {}) {
  const target = env.DAKT_PREVIEW_API || 'http://127.0.0.1:8001';
  const url = new URL(target);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('DAKT_PREVIEW_API must be an HTTP(S) origin.');
  }
  const headers = env.DAKT_API_TOKEN ? { authorization: `Bearer ${env.DAKT_API_TOKEN}` } : {};
  const auto = url.protocol === 'http:' && url.hostname.toLowerCase().endsWith('.local');
  let verified = '', expires = 0, pending;
  async function verifiedTarget() {
    if (verified && Date.now() < expires) return verified;
    if (!pending) pending = findPi({token:env.DAKT_API_TOKEN, previous:verified, discover, verify})
      .then(origin => { verified = origin; expires = Date.now() + 1000; return origin; })
      .finally(() => { pending = null; });
    return pending;
  }
  function route(websocket) {
    let proxy;
    const options = {target: websocket ? target.replace(/^http/, 'ws') : target, headers: auto ? {} : headers};
    if (websocket) options.ws = true;
    if (auto) {
      options.configure = instance => { proxy = instance; };
      options.bypass = async () => {
        try {
          const origin = await verifiedTarget();
          proxy.options.target = websocket ? origin.replace(/^http/, 'ws') : origin;
          proxy.options.headers = headers;
        } catch {
          verified = ''; expires = 0;
          proxy.options.headers = {};
          return false;
        }
      };
    }
    return options;
  }
  return {
    '/api': route(false),
    '/ws': route(true)
  };
}
