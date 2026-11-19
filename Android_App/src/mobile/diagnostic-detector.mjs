import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';

export async function diagnosticDetector(base, gpu, report) {
  const tasks = base+'tasks/';
  const files = await FilesetResolver.forVisionTasks(tasks);
  const compressed = typeof DecompressionStream === 'function';
  const abort = new AbortController();
  const downloadTimeout = setTimeout(() => abort.abort(),45000);
  report.state.MediaPipeStage = 'Đang tải song song mô hình tay và WASM';
  async function get(url,key,unzip=false) {
    const start = performance.now();
    const response = await fetch(url,{signal:abort.signal});
    report.state[key] = {http:response.status};
    if (!response.ok) throw Error('Resource HTTP '+response.status);
    const body = unzip ? new Response(response.body.pipeThrough(new DecompressionStream('gzip'))) : response;
    const bytes = await body.arrayBuffer();
    report.state[key] = {http:response.status,ms:Math.round(performance.now()-start),bytes:bytes.byteLength};
    return bytes;
  }
  let wasm, model;
  try {
    [wasm,model] = await Promise.all([
      get(files.wasmBinaryPath + (compressed ? '.gz' : ''),'wasmDownload',compressed),
      get(tasks+'hand_landmarker.task','handModelDownload'),
    ]);
  } catch (error) {
    abort.abort(); report.state.MediaPipeStage = 'Lỗi tải tệp'; throw error;
  } finally { clearTimeout(downloadTimeout); }
  const options = {runningMode:'VIDEO',numHands:2,baseOptions:{modelAssetBuffer:new Uint8Array(model)}};
  const create = async delegate => {
    report.state.MediaPipeStage = 'Đang khởi tạo WASM và graph · '+delegate;
    const wasmBinaryPath = URL.createObjectURL(new Blob([wasm],{type:'application/wasm'}));
    let timeout;
    const pending = HandLandmarker.createFromOptions({...files,wasmBinaryPath},{...options,baseOptions:{...options.baseOptions,delegate}});
    try {
      return await Promise.race([pending,new Promise((_,reject)=>{
        timeout = setTimeout(()=>reject(new DOMException('WASM initialization timeout','TimeoutError')),25000);
      })]);
    } catch (error) {
      pending.then(task=>task.close(),()=>{});
      throw error;
    } finally { clearTimeout(timeout); URL.revokeObjectURL(wasmBinaryPath); }
  };
  let delegate = gpu ? 'GPU' : 'CPU', detector;
  try { detector = await create(delegate); }
  catch (error) {
    if (delegate !== 'GPU' || error.name === 'TimeoutError') throw error;
    report.error('MediaPipe GPU initialization',error);
    delegate = 'CPU';
    detector = await create(delegate);
  }
  report.state.delegate = delegate;
  report.state.MediaPipeStage = 'Graph đã khởi tạo · Chờ detectForVideo';
  window.HAND_CONNECTIONS = HandLandmarker.HAND_CONNECTIONS.map(({start,end})=>[start,end]);
  let listener;
  return {
    onResults(handler) { listener = handler; },
    async send({image,timestamp}) {
      let result;
      try { result = detector.detectForVideo(image,timestamp); }
      catch (error) {
        if (delegate !== 'GPU') throw error;
        report.error('MediaPipe GPU detection',error);
        detector.close();
        detector = await create('CPU');
        delegate = report.state.delegate = 'CPU';
        result = detector.detectForVideo(image,timestamp);
      }
      report.state.MediaPipeStage = 'detectForVideo đã trả kết quả';
      listener({multiHandLandmarks:result.landmarks,multiHandedness:result.handedness.map(side=>({
        label:side[0]?.categoryName, score:side[0]?.score,
      }))});
    },
  };
}
