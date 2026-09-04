// Keyboard map from docs/product-spec.md. Inert while focus is in a text field.
//
// M13 added five: `D` for a dislike, `A` for the spoken description, the arrow keys for
// the history stack, and `?` for the map itself — which is the one that makes the other
// twelve discoverable, and should have been here from the start.

// Keys 1-5, shortest first, so the row reads as a scale. Values are seconds.
const INTERVAL_KEYS = { 1: 30, 2: 60, 3: 300, 4: 900, 5: 1800 };

// Input types that swallow a keystroke as text. Everything else — radio, checkbox,
// button — is an <input> that is not being typed into.
const TEXT_ENTRY_TYPES = new Set([
  'text',
  'search',
  'email',
  'password',
  'url',
  'tel',
  'number',
  'date',
  'datetime-local',
  'month',
  'week',
  'time',
]);

/**
 * Whether focus is somewhere a keystroke means text rather than a command.
 *
 * Matching on tag name alone was wrong and cost a real bug: clicking any radio in the
 * settings panel put focus on an <input>, which disabled every shortcut — including the
 * Esc that closes the panel, leaving the keyboard unable to undo what the mouse had done.
 */
function isTyping(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement) return true;
  // A select uses letters and arrows to pick an option.
  if (target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) return TEXT_ENTRY_TYPES.has(target.type);
  return false;
}

/**
 * Controls that act on Space themselves. Intercepting it would toggle the checkbox *and*
 * advance the artwork, or — since the handler calls preventDefault — neither.
 */
function actsOnSpace(target) {
  if (target instanceof HTMLButtonElement) return true;
  return (
    target instanceof HTMLInputElement &&
    ['checkbox', 'radio', 'button', 'submit', 'reset'].includes(target.type)
  );
}

/**
 * @returns {() => void} an unbind function — this app runs for hours and every listener
 * it adds has to be removable.
 */
export function bindShortcuts(handlers) {
  function onKeyDown(event) {
    if (event.defaultPrevented) return;
    // Escape is the exception to the typing rule. The settings panel now holds a text
    // field — the API key — and a field you cannot escape from is a panel you cannot
    // close from the keyboard, which is the same bug isTyping() was written to fix.
    if (isTyping(event.target) && event.key !== 'Escape') return;
    // Never shadow a browser or OS shortcut. Ctrl+F is find, not fullscreen.
    if (event.ctrlKey || event.metaKey || event.altKey) return;

    const intervalSeconds = INTERVAL_KEYS[event.key];
    if (intervalSeconds !== undefined) {
      event.preventDefault();
      handlers.onInterval(intervalSeconds);
      return;
    }

    switch (event.key) {
      case ' ':
        // Leave Space to a focused control that uses it, so the checkbox in the settings
        // panel can still be toggled from the keyboard.
        if (actsOnSpace(event.target)) return;
        // Otherwise Space scrolls by default, and there is nothing here to scroll.
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
      case 's':
      case 'S':
        event.preventDefault();
        handlers.onSettings();
        break;
      case 'l':
      case 'L':
        event.preventDefault();
        handlers.onLike();
        break;
      case 'd':
      case 'D':
        // Between `L` and `X`: less of this, but keep showing it. See ADR-0014.
        event.preventDefault();
        handlers.onDislike();
        break;
      case 'x':
      case 'X':
        event.preventDefault();
        handlers.onHide();
        break;
      case 'a':
      case 'A':
        // The accessibility description, read aloud. `A` because it is the key somebody
        // who cannot see the screen has the best chance of being told about, and because
        // every other letter this app uses is already spoken for.
        event.preventDefault();
        handlers.onDescribe();
        break;
      case 'ArrowLeft':
        event.preventDefault();
        handlers.onBack();
        break;
      case 'ArrowRight':
        event.preventDefault();
        handlers.onForward();
        break;
      case '?':
        // Where every keyboard map lives. Shift+/ on most layouts, and the browser does
        // nothing else with it.
        event.preventDefault();
        handlers.onHelp();
        break;
      case 'Escape':
        // Priority is most-transient-first, per the spec: settings, then overlay, then
        // fullscreen.
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
