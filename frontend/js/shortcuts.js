// Keyboard map from docs/product-spec.md. Inert while focus is in a text field.

const INTERVAL_KEYS = { 1: 1, 2: 5, 3: 15, 4: 30 };

function isTyping(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return /^(input|textarea|select)$/i.test(target.tagName);
}

/**
 * @returns {() => void} an unbind function — this app runs for hours and every listener
 * it adds has to be removable.
 */
export function bindShortcuts(handlers) {
  function onKeyDown(event) {
    if (event.defaultPrevented || isTyping(event.target)) return;
    // Never shadow a browser or OS shortcut. Ctrl+F is find, not fullscreen.
    if (event.ctrlKey || event.metaKey || event.altKey) return;

    const interval = INTERVAL_KEYS[event.key];
    if (interval !== undefined) {
      event.preventDefault();
      handlers.onInterval(interval);
      return;
    }

    switch (event.key) {
      case ' ':
        // Space scrolls by default, and there is nothing here to scroll.
        event.preventDefault();
        handlers.onNext();
        break;
      case 'f':
      case 'F':
        event.preventDefault();
        handlers.onFullscreen();
        break;
      case 'i':
      case 'I':
        event.preventDefault();
        handlers.onToggleOverlay();
        break;
      case 'Escape':
        // Priority is most-transient-first, per the spec: settings, then overlay, then
        // fullscreen. Settings arrives in M4; the seam is here so the order cannot be
        // quietly got wrong later.
        if (handlers.isSettingsOpen()) handlers.onCloseSettings();
        else if (handlers.isOverlayVisible()) handlers.onDismissOverlay();
        else handlers.onExitFullscreen();
        break;
      default:
        break;
    }
  }

  window.addEventListener('keydown', onKeyDown);
  return () => window.removeEventListener('keydown', onKeyDown);
}
