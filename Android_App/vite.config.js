import { defineConfig, loadEnv } from 'vite';
import { previewProxy } from '../shared/previewProxy.mjs';
import { fileURLToPath } from 'node:url';
export default defineConfig({define:{__DEAFY_PACKAGED_AT__:JSON.stringify(new Date().toISOString())},resolve:{dedupe:['react','react-dom']},server:{fs:{allow:[fileURLToPath(new URL('..', import.meta.url))]},host:'127.0.0.1',port:5174,strictPort:true,proxy:previewProxy({ ...loadEnv('development', fileURLToPath(new URL('../backend', import.meta.url)), 'DAKT_'), ...process.env })},build:{outDir:'www'}});
