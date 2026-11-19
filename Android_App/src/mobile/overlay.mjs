export function landmarkProjection(videoWidth, videoHeight, width, height, previewMirrored, inputMirrored) {
  const scale = Math.min(width / videoWidth, height / videoHeight);
  const drawnWidth = videoWidth * scale, drawnHeight = videoHeight * scale;
  const x = (width - drawnWidth) / 2, y = (height - drawnHeight) / 2;
  return point => [x + (previewMirrored !== inputMirrored ? 1 - point.x : point.x) * drawnWidth,
    y + point.y * drawnHeight];
}
