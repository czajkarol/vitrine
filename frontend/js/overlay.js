// The metadata overlay: museum facts, revealed by mouse movement, faded by stillness.

import { t } from './i18n.js';

// "Fades after a few seconds of stillness" (docs/product-spec.md).
const IDLE_MS = 3500;

// While the details are expanded, someone is reading rather than glancing, and reading is
// not moving the mouse. 3.5s takes the text away mid-paragraph. This is long enough to read
// an expanded description and short enough that an unattended display still returns to the
// artwork on its own, which is what QUESTIONS.md #3 protects.
//
// Since M13 the rotation is also held while this is open, so the display no longer changes
// picture underneath a reader either — the fade and the clock were two halves of the same
// problem and only one of them had been solved.
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

export function createOverlay(elements, handlers = {}) {
  const { overlay, title, artist, meta, description, credit, attribution,
    facts, extra, detailsHint } = elements;

  let pinned = false;
  let visible = false;
  let lastMove = 0;
  let hideTimer = null;
  let expanded = false;
  // Set by a left click in fullscreen: the overlay stops appearing at all, so the artwork
  // is on screen with nothing over it. Movement does not bring it back — that is the whole
  // request — and a second click restores it. See `setSuppressed`.
  let suppressed = false;
  // Whether the current artwork has a description at all. It changes what expanding means
  // — the description plus the catalogue facts, or only the facts — and so what the hover
  // hint offers to do.
  let hasDescription = false;

  function collapse() {
    if (!expanded) return;
    expanded = false;
    description.classList.remove('expanded');
    if (facts) facts.classList.remove('expanded');
    if (extra) extra.hidden = true;
    description.scrollTop = 0;
    syncHint();
    handlers.onExpandChange?.(false);
  }

  /**
   * The one thing on screen that says the caption is a control.
   *
   * There was an `i` button here until M18 and there is not one now. It was shown on every
   * artwork, including the roughly seven in eight with no description at all, because a
   * control that vanishes reads as a rendering fault — which was the right fix for the
   * wrong problem. A caption you click is a target the size of a caption rather than of a
   * 1.9rem circle, it needs no explaining, and it takes the app's only permanent piece of
   * overlay chrome off the screen.
   *
   * What replaces the button is a line that appears on hover and nowhere else, so the
   * display at rest is unchanged. It is `aria-hidden`: it is an affordance for a pointer,
   * and a screen reader is told about `E` in the keyboard map instead.
   */
  function syncHint() {
    if (!detailsHint) return;
    detailsHint.textContent = t(
      expanded ? 'details_hint_close' : hasDescription ? 'details_hint_open' : 'details_hint_facts',
    );
  }

  function show() {
    if (suppressed) return;
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
    if (suppressed) return;
    lastMove = Date.now();
    if (!visible) show();
    if (hideTimer === null) hideTimer = setTimeout(tick, idleLimit());
  }

  function onPointerMove() {
    nudge();
  }

  /**
   * Open the details, or close them again.
   *
   * Deliberately not bound to the `I` key, which pins the whole overlay and means something
   * else (`docs/product-spec.md`). Two affordances, two meanings — `E` is this one.
   *
   * Opening it holds the rotation as well as stretching the idle fade. Those were two
   * halves of the same problem: the text staying put while the picture underneath it
   * changed is no better than the text going away.
   */
  function toggleDetails() {
    expanded = !expanded;
    description.classList.toggle('expanded', expanded);
    // The whole panel goes up a size when it is being read rather than glanced at. A
    // caption sized for a glance across a room is not a size anybody reads a paragraph at.
    if (facts) facts.classList.toggle('expanded', expanded);
    if (extra) extra.hidden = !expanded;
    if (!expanded) description.scrollTop = 0;
    syncHint();
    // Reading is not moving the mouse, so without this the overlay fades out from under
    // the thing the user just asked to read.
    nudge();
    handlers.onExpandChange?.(expanded);
    return expanded;
  }

  /**
   * Whether the pointer is finishing a text selection rather than asking for anything.
   *
   * Dragging across an expanded description to copy a sentence ends in a click on the
   * caption, and without this that click collapses the paragraph the user was selecting
   * from. Only a selection *inside* the caption counts, so a stale one left somewhere else
   * on the page cannot make the caption stop responding.
   */
  function isSelectingInside() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !facts) return false;
    return facts.contains(selection.anchorNode) || facts.contains(selection.focusNode);
  }

  /**
   * A click anywhere in the caption.
   *
   * The second click of a double click is ignored rather than undoing the first: a double
   * click on the stage is the fullscreen gesture, and somebody who lands one on the caption
   * by mistake should get one expansion rather than a flicker back to where they started.
   */
  function onFactsClick(event) {
    if (event.button !== 0 || event.detail > 1) return;
    if (isSelectingInside() || isOnScrollbar(event)) return;
    toggleDetails();
  }

  /**
   * A click on the expanded description's own scrollbar, which is not a click on the text.
   *
   * `offsetX` is measured from the padding box, so a press in the scrollbar gutter lands
   * past `clientWidth`. Without this, dragging the scrollbar of a long description closes
   * the description — the one gesture somebody reading four hundred words is most likely
   * to make.
   */
  function isOnScrollbar(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return false;
    return event.offsetX > target.clientWidth || event.offsetY > target.clientHeight;
  }

  // Scrolling a long description is the one way to be actively reading without moving the
  // pointer at all. Without this the overlay counts it as stillness.
  function onDescriptionScroll() {
    nudge();
  }

  window.addEventListener('pointermove', onPointerMove, { passive: true });
  // A press counts as presence too. Without this a click that lands while the overlay has
  // faded is simply lost — the overlay is `visibility: hidden`, so its buttons are not
  // hit-testable — and the display looks unresponsive to somebody whose hand never left
  // the mouse. Now the first click brings the controls back, which is what every media
  // player does and what the fullscreen toggle above already assumed happened.
  window.addEventListener('pointerdown', onPointerMove, { passive: true });
  facts?.addEventListener('click', onFactsClick);
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
      hasDescription = prose !== '';
      // A new artwork means new details, so whatever was expanded is gone anyway.
      collapse();
      description.textContent = prose;
      description.hidden = !hasDescription;
      syncHint();

      // The facts that do not earn a line at rest but are worth having when someone has
      // asked to read about the work. All of them were already on the response and none of
      // them were on screen anywhere.
      if (extra) {
        const rows = [
          [t('detail_origin'), artwork.place_of_origin],
          [t('detail_type'), artwork.artwork_type],
          [t('detail_reference'), artwork.main_reference_number],
          [t('detail_museum'), t(`museum_${artwork.museum ?? 'aic'}`)],
        ].filter(([, value]) => value);
        extra.textContent = '';
        for (const [label, value] of rows) {
          const row = document.createElement('div');
          row.className = 'ov-detail';
          const name = document.createElement('span');
          name.className = 'ov-detail-label';
          name.textContent = label;
          const text = document.createElement('span');
          text.textContent = value;
          row.append(name, text);
          extra.appendChild(row);
        }
      }

      credit.textContent = artwork.credit_line ?? '';
      credit.hidden = !artwork.credit_line;

      // The digital image is CC0 but courtesy is still owed, and which museum is owed it
      // depends on which one sent this. The description is CC BY 4.0 at the Art Institute
      // and its attribution is a licence condition, so that half only appears when it is
      // actually shown.
      const museum = artwork.museum === 'cma' ? 'cma' : 'aic';
      attribution.textContent = t(
        hasDescription && museum === 'aic'
          ? 'attribution_with_description'
          : `attribution_${museum}`,
      );
    },

    /** Reveal briefly, then let stillness fade it. Used when the artwork changes. */
    flash() {
      nudge();
    },

    /** `I` — pin open, or unpin and start fading again. */
    toggle() {
      if (suppressed) return false;
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

    toggleDetails,

    isExpanded() {
      return expanded;
    },

    /**
     * Hide the overlay outright, or let it behave normally again.
     *
     * The "just the picture" state: a left click in fullscreen takes the title, the
     * description and every control off screen, and movement no longer brings them back.
     * That last part is the point — an overlay that reappears the moment the mouse twitches
     * is exactly what somebody asking for this is trying to get rid of.
     */
    setSuppressed(next) {
      suppressed = next;
      if (!suppressed) {
        // **Clearing the flag is not the same as putting the overlay back.**
        // It used to be just the `return`, and the overlay then stayed hidden until the
        // next pointer *movement* happened to call nudge(). A click does not move the
        // mouse, so the gesture that is supposed to restore the chrome restored nothing:
        // the status line said "controls shown" and nothing appeared, and it only ever
        // worked on whichever press the user happened to jog the mouse on. Reported as
        // the left button taking several presses to do anything.
        nudge();
        return;
      }
      pinned = false;
      visible = false;
      clearTimeout(hideTimer);
      hideTimer = null;
      overlay.classList.remove('visible');
      collapse();
    },

    isSuppressed() {
      return suppressed;
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
      window.removeEventListener('pointerdown', onPointerMove);
      facts?.removeEventListener('click', onFactsClick);
      description.removeEventListener('scroll', onDescriptionScroll);
      clearTimeout(hideTimer);
      hideTimer = null;
    },
  };
}
