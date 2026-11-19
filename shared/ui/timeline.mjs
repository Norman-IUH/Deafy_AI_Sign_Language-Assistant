// The timeline presents existing history; it never sends commands or triggers audio.
export function timelineMessages(items, transcript) {
  const messages = [];
  for (const item of [...items].reverse()) {
    const time = Date.parse(item.created_at) || 0;
    if (item.kind === 'conversation' && item.transcript && messages.findLast(m => !m.own && m.sender !== 'AI')?.text !== item.transcript) messages.push({ id: `${item.id}-speech`, own: false, text: item.transcript, time });
    messages.push({ id: String(item.id), own: !['speech', 'ai_answer'].includes(item.kind), text: item.text, time, ...(item.kind === 'ai_answer' ? {sender:'AI'} : {}) });
  }
  const lastSpeech = messages.findLast(m => !m.own && m.sender !== 'AI');
  if (lastSpeech?.text === transcript) lastSpeech.live = true;
  return messages;
}

export function createTimeline(api) {
  const history = document.getElementById('timelineHistory');
  if (!history) return { refresh() {}, sent() {} };
  let version = '', run = 0, records = [], transcript = '';
  const live = document.querySelector('.speech-panel');
  const locals = [];
  const outgoing = document.getElementById('timelineOutgoing');
  const viewport = history.parentElement;
  function bubble(message) {
    const article = document.createElement('article');
    article.className = `timeline-message ${message.own ? 'outgoing' : 'incoming'}`;
    const label = document.createElement('span'); label.textContent = message.sender || (message.own ? 'Bạn' : 'Người đối diện');
    const text = document.createElement('p'); text.textContent = message.text;
    article.append(label, text); return article;
  }
  function render() {
    const rows = [...timelineMessages(records, transcript), ...locals].sort((a, b) => a.time - b.time);
    history.replaceChildren(...rows.map(m => m.live ? live : bubble(m)));
    if (!rows.some(m => m.live)) history.after(live);
    outgoing.replaceChildren();
  }
  function follow() { viewport.scrollTop = viewport.scrollHeight; }
  return {
    async refresh(next, connection) {
      transcript = next.transcript;
      const key = `${connection}:${next.history_count}`;
      if (key === version) return;
      version = key; const current = ++run;
      history.setAttribute('aria-busy', 'true');
      try {
        // shortcut: show the latest history page; use History for older entries until inline paging is needed.
        const result = await api('/api/history?offset=0');
        if (current !== run) return;
        const nearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 100;
        records = result.items;
        // Replace local utterances once the same utterance is explicitly saved.
        for (let i = locals.length - 1; i >= 0; i--) if (result.items.some(m => m.kind !== 'speech' && m.text === locals[i].text && Date.parse(m.created_at) >= locals[i].time - 1000)) locals.splice(i, 1);
        render();
        if (nearBottom) follow();
      } catch { if (current === run) version = ''; /* Retain rendered conversation during an unavailable history request. */ }
      finally { if (current === run) history.setAttribute('aria-busy', 'false'); }
    },
    sent(text) {
      if (!text) return;
      locals.push({ own: true, text, time: Date.now() });
      if (locals.length > 50) locals.shift();
      render(); follow();
    }
  };
}
