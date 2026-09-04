// Reading the accessibility description out loud.
//
// **The Web Speech API, not a cloud voice.** `speechSynthesis` is built into the browser,
// costs nothing per word, needs no key and works with the network down — which matters
// here more than voice quality does, because the alternative is a per-character bill on
// the one feature whose whole point is that somebody can rely on it. `docs/ai-system.md`
// has the arithmetic: a cloud TTS voice would cost several times the model that wrote the
// text, every time it is replayed.
//
// It is also the only speech the browser will let a page produce without a network, and
// this app is meant to keep working with one museum unreachable.
//
// Two things about the API that are not obvious and are both handled below:
//
// - **Voices load asynchronously.** `getVoices()` returns `[]` on first call in Chrome and
//   fills in later, announced by a `voiceschanged` event. Asking for a Polish voice at the
//   moment the page loads therefore gets you the default one.
// - **A long utterance is cut off** in some builds after roughly fifteen seconds unless
//   something keeps the queue alive. The description is bounded at 4,000 characters, which
//   is well past that, so it is split into sentence-sized utterances — which also makes
//   `cancel()` responsive, because it takes effect at the next boundary rather than after
//   the whole thing.

/** Whether this browser can speak at all. The controls are hidden when it cannot. */
export function isSupported() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

// Roughly a sentence. Split on terminal punctuation followed by a space, keeping the
// punctuation, so the synthesiser still hears the full stop and pauses for it.
const SENTENCE = /[^.!?…]+[.!?…]*\s*/g;

// Below this, a fragment is not worth its own utterance — a stray "Mr." split, say — and
// gets appended to the previous one.
const MIN_CHUNK = 24;

function chunk(text) {
  const parts = text.match(SENTENCE) ?? [text];
  const chunks = [];
  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const last = chunks[chunks.length - 1];
    if (last !== undefined && trimmed.length < MIN_CHUNK) chunks[chunks.length - 1] = `${last} ${trimmed}`;
    else chunks.push(trimmed);
  }
  return chunks;
}

export function createSpeech() {
  const synth = isSupported() ? window.speechSynthesis : null;
  // Set while this module is the one that cancelled, so the `end` event of an utterance we
  // deliberately stopped does not read as the reading having finished.
  let stopping = false;
  let onStateChange = () => {};
  let speaking = false;

  function voiceFor(language) {
    if (!synth) return null;
    const voices = synth.getVoices();
    // Exact locale first — `pl-PL` — then the bare language. A browser with no Polish voice
    // installed gets its default one, which reads Polish badly but audibly; refusing to
    // speak at all would be worse.
    return (
      voices.find((voice) => voice.lang?.toLowerCase().startsWith(`${language}-`)) ??
      voices.find((voice) => voice.lang?.toLowerCase() === language) ??
      null
    );
  }

  function setSpeaking(next) {
    if (speaking === next) return;
    speaking = next;
    onStateChange(speaking);
  }

  return {
    /** Whether this browser can speak. Asked on the instance so callers hold one thing. */
    isSupported() {
      return synth !== null;
    },

    /** Called whenever speech starts or stops, so a button can show which it is. */
    onChange(listener) {
      onStateChange = listener;
    },

    isSpeaking() {
      return speaking;
    },

    /**
     * Read `text` aloud in `language`, replacing anything already being read.
     *
     * @returns {boolean} whether speech actually started. False means this browser cannot,
     * and the caller leaves the text on screen without pretending otherwise.
     */
    speak(text, language = 'en') {
      if (!synth || !text) return false;
      this.stop();
      const voice = voiceFor(language);
      const parts = chunk(text);
      parts.forEach((part, index) => {
        const utterance = new SpeechSynthesisUtterance(part);
        utterance.lang = voice?.lang ?? language;
        if (voice) utterance.voice = voice;
        // A shade slower than default. This is a description of a picture, not a
        // notification, and the listener is building an image from it.
        utterance.rate = 0.95;
        if (index === 0) utterance.addEventListener('start', () => setSpeaking(true));
        if (index === parts.length - 1) {
          utterance.addEventListener('end', () => {
            if (!stopping) setSpeaking(false);
          });
        }
        utterance.addEventListener('error', () => {
          // Ordinary rather than exceptional: `cancel()` raises this on the queued
          // utterances it discards. Nothing to report — the state is set by the caller.
          if (!stopping) setSpeaking(false);
        });
        synth.speak(utterance);
      });
      return true;
    },

    /** Stop immediately. Safe to call when nothing is being read. */
    stop() {
      if (!synth) return;
      stopping = true;
      synth.cancel();
      stopping = false;
      setSpeaking(false);
    },

    /**
     * Warm the voice list.
     *
     * `getVoices()` is empty on first call in Chrome and fills in asynchronously, so a page
     * that asks for a Polish voice the moment it loads gets the default one instead. Called
     * once at boot; the event fires later and there is nothing to wait for.
     */
    prime() {
      if (!synth) return;
      synth.getVoices();
      synth.addEventListener?.('voiceschanged', () => synth.getVoices(), { once: true });
    },
  };
}
