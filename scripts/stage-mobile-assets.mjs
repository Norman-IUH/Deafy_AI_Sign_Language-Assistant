import { gzipSync } from 'node:zlib';
import { copyFile, mkdir, stat, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const target = new URL('../Android_App/public/mobile/', import.meta.url);
const modules = new URL('../Android_App/node_modules/', import.meta.url);
await mkdir(target, {recursive:true});
const manifest = JSON.parse(await readFile(new URL('model2.json',target), 'utf8'));
const expectedCheckpoint = process.env.DAKT_MOBILE_CHECKPOINT_SHA256 || manifest.sha256;
if (!/^[a-f0-9]{64}$/.test(expectedCheckpoint) || manifest.sha256 !== expectedCheckpoint) {
  throw Error('Checkpoint Model 2 differs from the expected Pi checkpoint.');
}
if (!manifest.checkpoint_source || !manifest.version || !manifest.labels.length) throw Error('Missing Model 2 provenance.');
for (const [file, expected] of [['model2.onnx',manifest.onnx_sha256], ['model2-gru.bin',manifest.gru_sha256]]) {
  const actual = createHash('sha256').update(await readFile(new URL(file,target))).digest('hex');
  if (actual !== expected) throw Error(`${file} differs from the verified export in model2.json.`);
}
const assets = {
  '@mediapipe/hands/': [
    'hands.binarypb', 'hand_landmark_full.tflite', 'hand_landmark_lite.tflite',
    'hands_solution_packed_assets_loader.js','hands_solution_packed_assets.data',
    'hands_solution_simd_wasm_bin.data','hands_solution_simd_wasm_bin.js','hands_solution_simd_wasm_bin.wasm',
    'hands_solution_wasm_bin.js','hands_solution_wasm_bin.wasm',
  ],
  'onnxruntime-web/dist/': ['ort-wasm-simd-threaded.mjs','ort-wasm-simd-threaded.wasm'],
};
for (const [folder, files] of Object.entries(assets)) {
  for (const file of files) await copyFile(new URL(folder+file,modules),new URL(file,target));
}
const tasks = new URL('tasks/',target);
await mkdir(tasks,{recursive:true});
if (!(await stat(new URL('hand_landmarker.task',tasks))).size) throw Error('Missing Hand Landmarker model');
for (const kind of ['vision_wasm_internal','vision_wasm_nosimd_internal']) {
  for (const ext of ['js','wasm']) {
    await copyFile(new URL('@mediapipe/tasks-vision/wasm/'+kind+'.'+ext,modules),new URL(kind+'.'+ext,tasks));
  }
  const wasm = await readFile(new URL(kind+'.wasm',tasks));
  await writeFile(new URL(kind+'.wasm.gz',tasks),gzipSync(wasm));
}
console.log('Copied local MediaPipe and ONNX Runtime assets to',fileURLToPath(target));
