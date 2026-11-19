export function cameraOrientation(side, sourceMirrored) {
  return { detectorFlip: !sourceMirrored, previewFlip: (side === 'user') !== sourceMirrored };
}

export function rightHandCalibration(detectorFlip) {
  let previous, count = 0;
  return result => {
    const hand = result.multiHandLandmarks?.length === 1 && result.multiHandedness?.length === 1
      ? result.multiHandLandmarks[0] : null;
    const side = result.multiHandedness?.[0];
    if (hand?.length !== 21 || hand.some(({x,y,z}) => ![x,y,z].every(Number.isFinite)) || !['Right','Left'].includes(side?.label) ||
        !Number.isFinite(side.score) || side.score < .85) {
      previous = null; count = 0;
      return;
    }
    count = previous === side.label ? count + 1 : 1;
    previous = side.label;
    if (count === 5) return side.label === 'Right' ? !detectorFlip : detectorFlip;
  };
}
