export function features(result) {
  const vector = new Float32Array(126), counts = [0, 0];
  result.multiHandLandmarks?.forEach((hand, index) => {
    const side = result.multiHandedness?.[index];
    if (!side || !Number.isFinite(side.score) || side.score < .7 || !['Left', 'Right'].includes(side.label)) return;
    const slot = side.label === 'Left' ? 0 : 1, offset = slot * 63;
    if (counts[slot] && ++counts[slot] > 1) { vector.fill(0, offset, offset + 63); return; }
    if (hand.length !== 21 || hand.some(p => ![p.x, p.y, p.z].every(Number.isFinite))) return;
    counts[slot] = 1;
    hand.forEach(({x,y,z}, i) => {
      const position = offset + i * 3;
      vector[position] = x; vector[position + 1] = y; vector[position + 2] = z;
    });
  });
  return {vector, right: counts[1] === 1, left: counts[0] === 1};
}

export function windowedSigns(allowTransientLoss = false) {
  const frames = [];
  const coverage = () => frames.length > 1 ? frames.at(-1).now - frames[0].now : 0;
  let candidate, consecutive, latched, missingSince, gapMs, distinct = 0, lastEmit = -Infinity, lastPredict = -Infinity;
  let revision = 0;
  function clearWindow() { frames.length = 0; candidate = null; consecutive = distinct = 0; revision++; }
  function reset() { clearWindow(); latched = missingSince = gapMs = null; lastPredict = -Infinity; }
  return {
    reset, coverage, count: () => frames.length, distinct: () => distinct, gap: () => gapMs, revision: () => revision,
    sample(now, {vector, right, hands = Number(right)}) {
      if (!right) {
        const previous = frames.at(-1)?.now;
        // Skip short tracking misses; only genuine right-hand frames enter the tensor.
        if (allowTransientLoss && previous !== undefined && now > previous && now - previous <= 200) return;
        clearWindow();
        gapMs = null;
        if (hands) missingSince = null;
        else {
          missingSince ??= now;
          if (now - missingSince >= 500) latched = null;
        }
        return;
      }
      missingSince = null;
      const previous = frames.at(-1)?.now;
      if (previous !== undefined && (now <= previous || now - previous > 200)) {
        clearWindow(); gapMs = Math.round(now - previous);
      }
      frames.push({now, vector});
      const start = now - 3000;
      while (frames[1]?.now <= start) frames.shift();
      if (frames[0].now > start || now - lastPredict < 200) return;
      const input = new Float32Array(30 * 126);
      // Pi TimeWindow uses the same nearest-frame grid, including reuse when the gap is at most 200 ms.
      let index = 0, used = -1;
      distinct = 0;
      for (let i = 0; i < 30; i++) {
        const target = start + i * 100;
        while (frames[index + 1] && Math.abs(frames[index + 1].now - target) < Math.abs(frames[index].now - target)) index++;
        if (index !== used) distinct++;
        used = index;
        input.set(frames[index].vector, i * 126);
      }
      lastPredict = now;
      gapMs = null;
      return input;
    },
    accept(index, confidence, now) {
      if (confidence < .7) { candidate = null; consecutive = 0; return false; }
      consecutive = index === candidate ? consecutive + 1 : 1;
      candidate = index;
      if (consecutive < 3 || latched === index || now - lastEmit < 2000) return false;
      latched = index;
      lastEmit = now;
      return true;
    },
  };
}
