// The accessibility description: its own section in the overlay, and its own voice.
//
// Shaped after `interpretation.js` on purpose — one section, its own states, and no
// writing into the museum's half of the overlay. It differs in two ways that matter.
//
// **It is meant to be heard, not glanced at.** The section is `role="region"` with a live
// area, the controls are real buttons in the tab order, and reaching it from the keyboard
// is the primary path rather than the accessible one.
//
// **It says where its words came from.** A listener cannot check a description against the
// artwork. What they can be told is that no model saw the picture: the text is the Art
// Institute's own visual description, expanded. That line is not a disclaimer bolted on,
// it is the thing that makes the feature honest, so it renders with the text rather than
// under a "details" fold.

import { t } from './i18n.js';

export function createAccess(elements, speech) {
  const { section, status, body, summary, description, source, grounding, playButton,
    stopButton } = elements;

  // What is on screen, kept so a replay costs nothing and a language change can redraw it.
  let current = null;
  let state = 'idle';
  let unavailableKey = 'ai_unavailable';

  function setState(next, message) {
    state = next;
    section.hidden = next === 'idle';
    body.hidden = next !== 'ready';
    status.hidden = next === 'ready';
    status.textContent = message ?? '';
    syncControls();
  }

  function syncControls() {
    const ready = state === 'ready';
    // Hidden rather than disabled when there is nothing to read: a play button on an
    // empty panel is a control that does nothing, which is worse than no control.
    if (playButton) playButton.hidden = !ready || !speech.isSupported();
    if (stopButton) stopButton.hidden = !ready || !speech.isSupported() || !speech.isSpeaking();
    if (playButton) {
      // The label changes rather than the glyph, because a screen reader reads the label
      // and "replay" is the word that says this costs nothing.
      playButton.setAttribute(
        'aria-label',
        t(speech.isSpeaking() ? 'access_stop' : 'access_play'),
      );
    }
  }

  speech.onChange(syncControls);

  return {
    loading() {
      current = null;
      setState('loading', t('access_loading'));
    },

    /**
     * @param {string} [key] which quiet line. An artwork the museum has written nothing
     * visual about, and a provider that does not do this, are ordinary states rather than
     * faults, and each reads differently.
     */
    unavailable(key = 'ai_unavailable') {
      current = null;
      unavailableKey = key;
      setState('unavailable', t(key));
    },

    /** Fill in one description, and start reading it. */
    render(payload, { speak = true } = {}) {
      current = payload;
      summary.textContent = payload.summary;
      description.textContent = payload.description;
      // Which museum field the words came from. The two read differently: alt text is the
      // museum describing the image, a catalogue description is the museum describing the
      // work, and a listener deciding how much to trust this should be told which.
      grounding.textContent = t(
        payload.grounded_in === 'alt_text' ? 'access_grounded_alt' : 'access_grounded_description',
      );
      source.textContent = t('ai_source', {
        provider: payload.provider,
        model: payload.model,
      });
      setState('ready');
      if (speak) this.speak();
    },

    /**
     * Read what is on screen, or stop reading it.
     *
     * Replay is free — the description is cached on the server and the text is right here —
     * which is why this is a control of its own rather than a second request.
     */
    speak() {
      if (state !== 'ready' || !current) return;
      if (speech.isSpeaking()) {
        speech.stop();
        return;
      }
      speech.speak(`${current.summary} ${current.description}`, current.language);
    },

    stop() {
      speech.stop();
    },

    clear() {
      speech.stop();
      current = null;
      setState('idle');
    },

    hasContent() {
      return state === 'ready';
    },

    /** Whether anything here is currently costing the display its attention. */
    isActive() {
      return state !== 'idle';
    },

    retranslate() {
      if (state === 'ready' && current) this.render(current, { speak: false });
      else if (state === 'loading') setState('loading', t('access_loading'));
      else if (state === 'unavailable') setState('unavailable', t(unavailableKey));
    },
  };
}
