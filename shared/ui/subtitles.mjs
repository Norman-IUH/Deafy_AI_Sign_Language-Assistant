// The server owns the latest stable recognition and its expiry.
export function createSubtitles(button, pick, clock = globalThis) {
  const text = button.firstElementChild;
  const hint = button.lastElementChild;
  let caption, timer, lastId, deadline, pending = false;
  const now = () => clock.performance?.now() ?? Date.now();
  function display(message, action = '', enabled = false) {
    if (text.textContent !== message) text.textContent = message;
    if (hint.textContent !== action) hint.textContent = action;
    button.disabled = !enabled;
    button.title = message;
  }
  function expire() {
    clock.clearTimeout(timer);
    caption = null;
    display('Chờ ký hiệu mới');
  }
  button.onclick = async () => {
    if (!caption || pending) return;
    const selected = caption;
    pending = true;
    button.disabled = true;
    try { await pick(selected); }
    finally {
      pending = false;
      if (caption) button.disabled = false;
    }
  };
  return {
    reset() { expire(); button.hidden = true; },
    update(snapshot, automaticHint = '') {
      const pi = snapshot?.pi;
      button.hidden = !snapshot?.camera?.running || !pi?.enabled || pi.mode !== 'ai' || !Object.hasOwn(pi, 'caption');
      const next = button.hidden || pi.settling ? null : pi.caption;
      if (!next?.text || next.remaining_ms <= 0) {
        expire();
        if (['collecting', 'stabilizing', 'uncertain'].includes(snapshot?.recognition?.status))
          display('Đang nhận diện…');
        return;
      }
      const limit = now() + next.remaining_ms;
      deadline = next.id === lastId ? Math.min(deadline, limit) : limit;
      lastId = next.id;
      if (deadline <= now()) { expire(); return; }
      caption = next;
      display(next.text, automaticHint || 'Nhấn để thêm', !pending && !automaticHint);
      clock.clearTimeout(timer);
      timer = clock.setTimeout(expire, deadline - now());
    },
  };
}
