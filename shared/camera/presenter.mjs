// Decode offscreen so a slow frame never replaces the last complete image.
export function createFramePresenter(image, empty, makeImage = () => new Image(), urls = URL) {
  let current, version = 0;
  return {
    clear() {
      version++;
      image.hidden = true; empty.hidden = false;
      image.removeAttribute('src');
      if (current) urls.revokeObjectURL(current);
      current = null;
    },
    async present(blob, valid = () => true) {
      const run = version;
      const next = urls.createObjectURL(blob);
      try {
        const decoded = makeImage(); decoded.src = next;
        await decoded.decode();
        if (run !== version || !valid()) return;
        const old = current;
        image.src = next; image.hidden = false; empty.hidden = true;
        current = next;
        if (old) urls.revokeObjectURL(old);
      } finally { if (next !== current) urls.revokeObjectURL(next); }
    }
  };
}
