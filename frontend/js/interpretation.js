// The AI interpretation panel inside the overlay.
//
// It owns one section and nothing else. What it will never do is write into the museum's
// half of the overlay: `docs/product-spec.md` requires generated text to be labelled and
// visually separated, and the cheapest way to guarantee that is for the two never to
// share an element.
//
// Everything here is inert until someone asks. Nothing on this path runs on rotation.

import { t } from './i18n.js';

export function createInterpretation(elements) {
  const { section, status, body, visual, reading, themes, lookCloser, source } = elements;

  // What is on screen, kept so a language change can redraw it without another call.
  let current = null;
  let state = 'idle';
  // Which note is showing, so a language change can say the same thing again.
  let unavailableKey = 'ai_unavailable';

  function setState(next, message) {
    state = next;
    section.hidden = next === 'idle';
    body.hidden = next !== 'ready';
    status.hidden = next === 'ready';
    status.textContent = message ?? '';
  }

  return {
    /** Waiting on the provider. Says so rather than leaving the panel empty. */
    loading() {
      current = null;
      setState('loading', t('ai_loading'));
    },

    /**
     * A provider that is down or simply slow. One quiet line — never a dialog, and never
     * at the expense of the museum text above it.
     *
     * @param {string} [key] which quiet line. A spent budget is not a failure and says
     * so; `docs/product-spec.md` asks for the two to read differently.
     */
    unavailable(key = 'ai_unavailable') {
      current = null;
      unavailableKey = key;
      setState('unavailable', t(key));
    },

    /** Fill in one interpretation. */
    render(payload) {
      current = payload;
      visual.textContent = payload.visual_description;
      reading.textContent = payload.interpretation;
      // The list separator is a locale question the moment there is a second language,
      // so it goes through Intl rather than being a hardcoded comma.
      themes.textContent = `${t('ai_themes')}: ${formatList(payload.themes)}`;
      lookCloser.textContent = `${t('ai_look_closer')}: ${payload.look_closer}`;
      // Naming the model is part of not passing this off as a museum text.
      source.textContent = t('ai_source', {
        provider: payload.provider,
        model: payload.model,
      });
      setState('ready');
    },

    /** Take it away — the artwork changed, or the overlay was dismissed. */
    clear() {
      current = null;
      setState('idle');
    },

    /** Whether there is anything worth keeping on screen. */
    hasContent() {
      return state === 'ready';
    },

    /**
     * Redraw the labels after a language change. The generated text itself is in the old
     * language and cannot be translated here — main.js asks for it again.
     */
    retranslate() {
      if (state === 'ready' && current) this.render(current);
      else if (state === 'loading') setState('loading', t('ai_loading'));
      else if (state === 'unavailable') setState('unavailable', t(unavailableKey));
    },
  };
}

function formatList(items) {
  // Intl.ListFormat gives "a, b and c" in English and "a, b i c" in Polish.
  const language = document.documentElement.lang || 'en';
  try {
    return new Intl.ListFormat(language, { style: 'long', type: 'conjunction' }).format(items);
  } catch {
    // A browser without ListFormat still gets a readable line.
    return items.join(', ');
  }
}
