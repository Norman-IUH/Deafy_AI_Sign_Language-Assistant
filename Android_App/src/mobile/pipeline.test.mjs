import test from 'node:test';
import assert from 'node:assert/strict';
import { features, windowedSigns } from './pipeline.mjs';
import { landmarkProjection } from './overlay.mjs';
import { piModelMatch } from './model-info.mjs';
import { cameraOrientation, rightHandCalibration } from './orientation.mjs';

test('hand slots, confidence and duplicate handedness', () => {
  const hand = Array.from({length:21}, (_, i) => ({x:i,y:i+1,z:i+2}));
  const side = (label, score = .9) => ({label,score});
  const frame = features({multiHandLandmarks:[hand, hand],multiHandedness:[side('Right'),side('Left',.69)]});
  assert.equal(frame.right,true);
  assert.deepEqual([...frame.vector.slice(60,66)],[0,0,0,0,1,2]);
  const ambiguous = features({multiHandLandmarks:[hand,hand],multiHandedness:[side('Right'),side('Right')]});
  assert.equal(ambiguous.right,false);
  assert.ok(ambiguous.vector.every(x => x === 0));
});

test('30 x 126 nearest samples, timing gaps and stable latched predictions', () => {
  const signs = windowedSigns();
  const frame = n => ({vector:new Float32Array(126).fill(n),right:true});
  for (let i=0; i<30; i++) assert.equal(signs.sample(i*100,frame(i)),undefined);
  const input = signs.sample(3000,frame(30));
  assert.equal(input.length,3780);
  assert.deepEqual(Array.from({length:30},(_,i)=>input[i*126]),Array.from({length:30},(_,i)=>i));
  for (const [at,result] of [[3000,false],[3200,false],[3400,true],[5600,false]]) {
    assert.equal(signs.accept(1,.9,at),result);
  }
  assert.equal(signs.sample(6000,frame(60)),undefined);
  assert.equal(signs.sample(6100,{right:false}),undefined);
});

test('a gap greater than 200 ms resets the window', () => {
  const signs = windowedSigns();
  const frame = {vector:new Float32Array(126),right:true};
  for (let i=0; i<12; i++) assert.equal(signs.sample(i*250,frame),undefined);
  assert.equal(signs.sample(3000,frame),undefined);
  assert.equal(signs.sample(3400,frame),undefined);
  assert.equal(signs.coverage(),0);
});

test('mobile ignores a missed detection inside 200 ms without adding its coordinates', () => {
  const signs = windowedSigns(true);
  const accepted = {vector:new Float32Array(126).fill(1),right:true};
  const missed = {vector:new Float32Array(126).fill(-1),right:false};
  for (let ms=0; ms<3000; ms+=100) signs.sample(ms, ms===1500 ? missed : accepted);
  const input = signs.sample(3000,accepted);
  assert.ok(input?.every(value => value===1));
  const revision = signs.revision();
  signs.sample(3100,missed);
  assert.equal(signs.revision(),revision);
  signs.sample(3250,missed);
  assert.equal(signs.revision(),revision+1);
  assert.equal(signs.count(),0);
});

test('Pi nearest-frame rule can reuse frames within the 200 ms limit', () => {
  const signs = windowedSigns();
  const frame = n => ({vector:new Float32Array(126).fill(n),right:true});
  for (let i=0; i<20; i++) assert.equal(signs.sample(i*150,frame(i)),undefined);
  const input = signs.sample(3000,frame(20));
  assert.deepEqual(Array.from({length:30},(_,i)=>input[i*126]),Array.from({length:30},(_,i)=>Math.round(i*100/150)));
  assert.equal(signs.distinct(),20);
});

test('compatibility requires live checkpoint identity and actual class indices', () => {
  const manifest = {sha256:'trusted',labels:[{id:'A'},{id:'B'}]};
  const pi = {sha256:'trusted',num_classes:2,classes:{A:0,B:1}};
  assert.equal(piModelMatch(manifest, null),null);
  assert.equal(piModelMatch(manifest, pi),true);
  assert.equal(piModelMatch(manifest,{...pi, classes:{A:1,B:0}}),false);
  assert.equal(piModelMatch(manifest,{...pi, sha256:'other'}),false);
});

test('portrait letterbox and rear-camera mirror use the displayed contain rectangle', () => {
  const point = {x:.25,y:.75};
  assert.deepEqual(landmarkProjection(480,640,360,240,true,true)(point), [135,180]);
  assert.deepEqual(landmarkProjection(480,640,360,240,false,true)(point), [225,180]);
  assert.deepEqual(landmarkProjection(640,480,320,480,true,true)(point), [80,300]);
});

test('an already mirrored source is corrected before MediaPipe while preview still follows camera side', () => {
  for (const side of ['user','environment']) {
    for (const sourceMirrored of [false,true]) {
      const { detectorFlip, previewFlip } = cameraOrientation(side,sourceMirrored);
      assert.equal(detectorFlip !== sourceMirrored,true);
      assert.equal(previewFlip !== sourceMirrored,side==='user');
      assert.equal(previewFlip !== detectorFlip,side==='environment');
    }
  }
});

test('right-hand calibration requires one stable hand and recreates the training slots without changing coordinates', () => {
  const hand = Array.from({length:21}, (_,i)=>({x:i/32,y:.5,z:-.25}));
  const result = (label,score=.95) => ({multiHandLandmarks:[hand],multiHandedness:[{label,score}]});
  for (const detectorFlip of [false,true]) {
    for (const label of ['Left','Right']) {
      const sample = rightHandCalibration(detectorFlip);
      for (let i=0;i<4;i++) assert.equal(sample(result(label)),undefined);
      assert.equal(sample(result(label,.84)),undefined);
      for (let i=0;i<4;i++) assert.equal(sample(result(label)),undefined);
      const sourceMirrored = sample(result(label));
      assert.equal(cameraOrientation('user',sourceMirrored).detectorFlip, label==='Right' ? detectorFlip : !detectorFlip);
    }
  }
  const frame = features(result('Right'));
  assert.equal(frame.left,false);
  assert.equal(frame.right,true);
  assert.deepEqual([...frame.vector.slice(0,63)],Array(63).fill(0));
  assert.deepEqual([...frame.vector.slice(63,69)],[0,.5,-.25,1/32,.5,-.25]);
  const signs = windowedSigns();
  for(let i=0;i<30;i++) signs.sample(i*100,frame);
  assert.deepEqual(signs.sample(3000,frame),Float32Array.from({length:30*126},(_,i)=>frame.vector[i%126]));
});

test('brief tracking loss does not latch the same gesture twice', () => {
  const signs = windowedSigns();
  const accept = start => [0,200,400].map(diff => signs.accept(1,.9,start+diff));
  assert.deepEqual(accept(0),[false,false,true]);
  signs.sample(2500,{right:false,hands:0});
  signs.sample(2600,{right:false,hands:1});
  assert.deepEqual(accept(3000),[false,false,false]);
  signs.sample(4000,{right:false,hands:0});
  signs.sample(4500,{right:false,hands:0});
  assert.deepEqual(accept(5000),[false,false,true]);
});
