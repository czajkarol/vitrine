// The metadata overlay: museum facts, revealed by mouse movement, faded by stillness.

import { t } from './i18n.js';

// "Fades after a few seconds of stillness" (docs/product-spec.md).
const IDLE_MS = 3500;

// While the description is expanded, someone is reading rather than glancing, and
// reading is not moving the mouse. 3.5s takes the text away mid-paragraph. This is long
// enough to read a clamped-open description and short enough that an unattended display
// still returns to the artwork on its own, which is what QUESTIONS.md #3 protects.
const IDLE_READING_MS = 20000;

/**
 * AIC's `description` is a CC BY field containing HTML markup. We want the words, not the
 * markup, and we will not hand a remote string to innerHTML. DOMParser builds an inert
 * document — no scripts run, no resources load — and textContent takes the prose out.
 */
function plainText(html) {
  if (!html) return '';
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  return (parsed.body.textContent ?? '').replace(/\s+/g, ' ').trim();
}

export function createOverlay(elements) {
  const { overlay, title, artist, meta, description, credit, attribution, expandButton } =
    elements;

  let pinned = false;
  let visible = false;
  let lastMove = 0;
  let hideTimer = null;
  let expanded = false;

  /**
   * Whether the clamp is actually hiding anything.
   *
   * Measured, not guessed from character count: the clamp is five *lines*, and how many
   * characters fit in five lines depends on the viewport, the font that won the
   * `font-display: swap` race, and the words themselves. A button offering to expand
   * text that is already fully visible is worse than no button.
   */
  function isClamped() {
    return !expanded && description.scrollHeight > description.clientHeight + 1;
  }

  function collapse() {
    if (!expanded) return;
    expanded = false;
    description.classList.remove('expanded');
    description.scrollTop = 0;
    syncExpandButton();
  }

  function syncExpandButton() {
    if (!expandButton) return;
    // Hidden when there is nothing to expand and when there is nothing expanded to
    // collapse — which for a short description is always.
    expandButton.hidden = !expanded && !isClamped();
    // The state goes on aria-expanded rather than into the label, so a screen reader
    // hears it without the label having to be swapped in two languages — and so the
    // stylesheet can show it too.
    expandButton.setAttribute('aria-expanded', String(expanded));
  }

  function show() {
    visible = true;
    overlay.classList.add('visible');
  }

  function hide() {
    if (pinned) return;
    visible = false;
    overlay.classList.remove('visible');
    // An expanded essay must never be what an unattended display settles on. The overlay
    // fading is the moment nobody is reading it any more.
    collapse();
  }

  /**
   * One self-rescheduling timer rather than a new one per mousemove. mousemove fires
   * dozens of times a second and this app runs for hours; churning a timer per event is
   * exactly the kind of accumulation the frontend rules warn about.
   */
  function idleLimit() {
    return expanded ? IDLE_READING_MS : IDLE_MS;
  }

  function tick() {
    const idle = Date.now() - lastMove;
    // Read fresh each time rather than captured when the timer was set: expanding the
    // description mid-countdown has to extend the countdown, not wait for the next one.
    const limit = idleLimit();
    if (idle >= limit) {
      hideTimer = null;
      hide();
    } else {
      hideTimer = setTimeout(tick, limit - idle);
    }
  }

  function nudge() {
    lastMove = Date.now();
    if (!visible) show();
    if (hideTimer === null) hideTimer = setTimeout(tick, idleLimit());
  }

  function onPointerMove() {
    nudge();
  }

  /**
   * The `i` button — show the whole description, or clamp it again.
   *
   * Deliberately not bound to the `I` key, which pins the whole overlay and means
   * something else (`docs/product-spec.md`). Two affordances, two meanings.
   */
  function toggleDescription() {
    expanded = !expanded;
    description.classList.toggle('expanded', expanded);
    if (!expanded) description.scrollTop = 0;
    syncExpandButton();
    // Reading is not moving the mouse, so without this the overlay fades out from under
    // the thing the user just asked to read.
    nudge();
    return expanded;
  }

  function onExpandClick() {
    toggleDescription();
  }

  // Scrolling a long description is the one way to be actively reading without moving
  // the pointer at all. Without this the overlay counts it as stillness.
  function onDescriptionScroll() {
    nudge();
  }

  window.addEventListener('pointermove', onPointerMove, { passive: true });
  expandButton?.addEventListener('click', onExpandClick);
  description.addEventListener('scroll', onDescriptionScroll, { passive: true });

  return {
    /** Fill in one artwork's facts. Does not change visibility. */
    render(artwork) {
      // AIC genuinely returns null titles. A caption with an empty heading reads as a
      // rendering fault, so say what it is instead.
      title.textContent = artwork.title || t('untitled');
      artist.textContent = artwork.artist ?? artwork.artist_display ?? '';

      // Date and medium on one line; an em dash between them only if both exist.
      meta.textContent = [artwork.date_display, artwork.medium_display]
        .filter(Boolean)
        .join(' — ');

      const prose = plainText(artwork.description);
      // A new artwork means a new description, so whatever was expanded is gone anyway.
      collapse();
      description.textContent = prose;
      description.hidden = prose === '';
      // After the text is in the DOM: scrollHeight is a measurement, not a prediction.
      syncExpandButton();

      credit.textContent = artwork.credit_line ?? '';
      credit.hidden = !artwork.credit_line;

      // The digital image is CC0 but courtesy is still owed. The description is CC BY 4.0
      // and its attribution is a licence condition, so it only appears when it is shown.
      attribution.textContent = prose ? t('attribution_with_description') : t('attribution');
    },

    /** Reveal briefly, then let stillness fade it. Used when the artwork changes. */
    flash() {
      nudge();
    },

    /** `I` — pin open, or unpin and start fading again. */
    toggle() {
      pinned = !pinned;
      if (pinned) show();
      else nudge();
      return pinned;
    },

    isPinned() {
      return pinned;
    },

    isVisible() {
      return visible;
    },

    toggleDescription,

    isDescriptionExpanded() {
      return expanded;
    },

    /** `Esc` — unpin and hide outright. */
    dismiss() {
      pinned = false;
      clearTimeout(hideTimer);
      hideTimer = null;
      visible = false;
      overlay.classList.remove('visible');
      collapse();
    },

    destroy() {
      window.removeEventListener('pointermove', onPointerMove);
      expandButton?.removeEventListener('click', onExpandClick);
      description.removeEventListener('scroll', onDescriptionScroll);
      clearTimeout(hideTimer);
      hideTimer = null;
    },
  };
}
