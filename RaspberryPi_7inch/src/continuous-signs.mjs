export function appendStableSign(draft, caption) {
  const sign = caption.text?.trim();
  if (!sign || !(caption.remaining_ms > 0)) return draft;
  const result = [draft.trimEnd(), sign].filter(Boolean).join(' ');
  return result.length <= 2000 ? result : null;
}
