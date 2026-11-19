// Only explicit utterances are spoken; snapshots and microphone results are not utterances.
export function createAudioRouter(speak, allowed) {
  const seen = new Set();
  return async event => {
    if (!event || !['sign_confirmed', 'manual_message_sent', 'chat_response'].includes(event.source)
      || typeof event.text !== 'string' || !event.text.trim() || !event.id || seen.has(event.id)) return false;
    seen.add(event.id);
    if (seen.size > 256) seen.delete(seen.values().next().value);
    if (!allowed(event)) return false;
    await speak(event.text);
    return true;
  };
}
