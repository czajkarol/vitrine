// The metadata overlay: museum facts, revealed by mouse movement, faded by stillness.

// "Fades after a few seconds of stillness" (docs/product-spec.md).
const IDLE_MS = 3500;

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

export function createOverlay(elements, messages) {
  const { overlay, title, artist, meta, description, credit, attribution } = elements;

  let pinned = false;
  let visible = false;
  let lastMove = 0;
  let hideTimer = null;

  function show() {
    visible = true;
    overlay.classList.add('visible');
  }

  function hide() {
    if (pinned) return;
    visible = false;
    overlay.classList.remove('visible');
  }

  /**
   * One self-rescheduling timer rather than a new one per mousemove. mousemove fires
   * dozens of times a second and this app runs for hours; churning a timer per event is
   * exactly the kind of accumulation the frontend rules warn about.
   */
  function tick() {
    const idle = Date.now() - lastMove;
    if (idle >= IDLE_MS) {
      hideTimer = null;
      hide();
    } else {
      hideTimer = setTimeout(tick, IDLE_MS - idle);
    }
  }

  function nudge() {
    lastMove = Date.now();
    if (!visible) show();
    if (hideTimer === null) hideTimer = setTimeout(tick, IDLE_MS);
  }

  function onPointerMove() {
    nudge();
  }

  window.addEventListener('pointermove', onPointerMove, { passive: true });

  return {
    /** Fill in one artwork's facts. Does not change visibility. */
    render(artwork) {
      // AIC genuinely returns null titles. A caption with an empty heading reads as a
      // rendering fault, so say what it is instead.
      title.textContent = artwork.title || messages.untitled;
      artist.textContent = artwork.artist ?? artwork.artist_display ?? '';

      // Date and medium on one line; an em dash between them only if both exist.
      meta.textContent = [artwork.date_display, artwork.medium_display]
        .filter(Boolean)
        .join(' — ');

      const prose = plainText(artwork.description);
      description.textContent = prose;
      description.hidden = prose === '';

      credit.textContent = artwork.credit_line ?? '';
      credit.hidden = !artwork.credit_line;

      // The digital image is CC0 but courtesy is still owed. The description is CC BY 4.0
      // and its attribution is a licence condition, so it only appears when it is shown.
      attribution.textContent = prose
        ? messages.attribution_with_description
        : messages.attribution;
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

    /** `Esc` — unpin and hide outright. */
    dismiss() {
      pinned = false;
      clearTimeout(hideTimer);
      hideTimer = null;
      visible = false;
      overlay.classList.remove('visible');
    },

    destroy() {
      window.removeEventListener('pointermove', onPointerMove);
      clearTimeout(hideTimer);
      hideTimer = null;
    },
  };
}
