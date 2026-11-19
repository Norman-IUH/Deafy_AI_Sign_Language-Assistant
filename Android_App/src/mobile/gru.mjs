function dot(weights, offset, values) {
  let sum = 0;
  for (let i=0; i<values.length; i++) sum += weights[offset+i] * values[i];
  return sum;
}
const sigmoid = value => 1 / (1 + Math.exp(-value));

// PyTorch GRU gate order is reset, update, new; reset multiplies the recurrent new gate.
export function createGru(weights, labels) {
  const h = 64;
  const sizes = [126, h];
  const count = sizes.reduce((sum, size) => sum + 3*h*(size+h+2),0) + labels*(h+1);
  if (weights.length !== count || !weights.every(Number.isFinite)) throw Error('Invalid Model 2 weights');
  let offset = 0;
  const take = length => weights.subarray(offset, offset += length);
  const layers = sizes.map(size => ({
    input:take(3*h*size), recurrent:take(3*h*h), inputBias:take(3*h), recurrentBias:take(3*h),
  }));
  const linear = take(labels*h), bias = take(labels);
  return sequence => {
    if (sequence.length !== 30*126) throw Error('Invalid Model 2 input');
    const states = layers.map(() => new Float32Array(h));
    const next = new Float32Array(h);
    for (let step=0;step<30;step++) {
      let values = sequence.subarray(step*126,(step+1)*126);
      layers.forEach((layer,index) => {
        const previous = states[index];
        const inputGate = i => dot(layer.input,i*values.length,values) + layer.inputBias[i];
        const recurrentGate = i => dot(layer.recurrent,i*h,previous) + layer.recurrentBias[i];
        for (let i=0;i<h;i++) {
          const reset = sigmoid(inputGate(i)+recurrentGate(i));
          const update = sigmoid(inputGate(h+i)+recurrentGate(h+i));
          const value = Math.tanh(inputGate(2*h+i)+reset*recurrentGate(2*h+i));
          next[i] = (1-update)*value + update*previous[i];
        }
        previous.set(next);
        values = previous;
      });
    }
    return Array.from(bias,(value,i) => value + dot(linear,i*h,states[1]));
  };
}
