export function setupImmersive(panel, trigger, exit) {
  let active = false;
  let native = false;
  const toolbar = panel.querySelector('.immersive-toolbar');
  const modeBar = document.querySelector('.pi-mode-bar');
  const composer = document.querySelector('.compose-panel');
  const cameraButton = panel.querySelector('.camera-toggle');
  const banner = document.getElementById('errorBanner');
  const diagnostics = panel.querySelector('.camera-diagnostics');
  const recognition = panel.querySelector('.recognition-result');
  const answer = document.getElementById('piAnswerPanel');
  const toast = document.getElementById('toast');
  const desktop = matchMedia('(min-width: 1100px) and (min-height: 640px)');
  function syncAnswerLayout() {
    const integrated = desktop.matches && !active;
    if (document.body.classList.contains('desktop-assistant') === integrated) return;
    document.body.classList.toggle('desktop-assistant', integrated);
    answer.open = integrated;
  }
  desktop.addEventListener('change', syncAnswerLayout);
  syncAnswerLayout();
  const moved = [toolbar, modeBar, composer, cameraButton, banner, diagnostics, recognition, toast].map(element => ({
    element, marker: document.createComment('fullscreen position')
  }));
  function moveControls() {
    for (const { element, marker } of moved) element.before(marker);
    panel.prepend(toolbar);
    toolbar.insertBefore(modeBar, exit);
    toolbar.insertBefore(cameraButton, exit);
    panel.append(composer);
    panel.append(toast);
    composer.prepend(banner);
    recognition.append(diagnostics);
    toolbar.append(recognition);
    answer.open = false;
    document.getElementById('signSuggestions').open = false;
  }
  const finish = () => {
    active = false; native = false;
    answer.open = false;
    document.getElementById('signSuggestions').open = false;
    for (const { element, marker } of moved) marker.replaceWith(element);
    panel.classList.remove('immersive');
    document.body.classList.remove('camera-immersive');
    syncAnswerLayout();
    panel.removeAttribute('role'); panel.removeAttribute('aria-modal');
    trigger.setAttribute('aria-expanded', 'false'); trigger.focus();
  };
  const close = async () => {
    if (document.fullscreenElement === panel) await document.exitFullscreen().catch(() => {});
    if (active) finish();
  };
  trigger.onclick = async () => {
    if (active) return;
    active = true;
    syncAnswerLayout();
    moveControls();
    panel.classList.add('immersive'); document.body.classList.add('camera-immersive');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    trigger.setAttribute('aria-expanded', 'true'); exit.focus();
    try { if (panel.requestFullscreen) { await panel.requestFullscreen(); native = true; } }
    catch { /* CSS immersive view remains available when fullscreen is denied. */ }
  };
  exit.onclick = close;
  document.addEventListener('fullscreenchange', () => { if (active && native && document.fullscreenElement !== panel) finish(); });
  document.addEventListener('keydown', event => {
    if (!active || panel.querySelector('dialog[open]')) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const controls = [...panel.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter(el => el.getClientRects().length);
      const index = controls.indexOf(document.activeElement);
      if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === controls.length - 1)) {
        event.preventDefault(); controls[event.shiftKey ? controls.length - 1 : 0]?.focus();
      }
    }
  });
  window.addEventListener('hashchange', () => { if (active) close(); });
}
