// Where you have been, so you can go back to it.
//
// The server already keeps a `history` table, and it is not this. That one holds the last
// ~50 ids so the selection query can penalise a near-repeat; it does not hold the artwork
// payload, and re-fetching one by id would be a second endpoint and a round trip to answer
// a question the browser already knows the answer to.
//
// So this is a browser-side stack of artwork payloads, and it lives only as long as the
// page. That is the right lifetime: "go back to the one before" is about the last few
// minutes, and a back stack restored across a reload would offer to return to something
// nobody remembers seeing.
//
// **Payloads, not decoded images.** A decoded 1686px bitmap is several megabytes and this
// app runs for hours; twenty of them held live is a leak with a nice name. The image is
// re-requested on the way back and comes out of the browser's own HTTP cache, which is
// what that cache is for.

// How far back you can go. Deep enough to cover "wait, what was that one before last",
// shallow enough that the array is not a place things accumulate.
export const HISTORY_DEPTH = 20;

export function createHistory(depth = HISTORY_DEPTH) {
  // Oldest first. `cursor` is the index of what is on screen, or -1 before anything is.
  let entries = [];
  let cursor = -1;

  return {
    /**
     * Record an artwork that has just been put on screen by moving *forward*.
     *
     * Anything ahead of the cursor is dropped, which is the ordinary back-stack rule: once
     * you have gone back three and then asked for a new artwork, the three you came from
     * are a branch nobody is returning to.
     */
    push(artwork) {
      if (!artwork) return;
      // Guard against recording the same artwork twice in a row — a manual advance that
      // happened to land on the one already up would otherwise need two presses to leave.
      if (entries[cursor]?.id === artwork.id) return;
      entries = entries.slice(0, cursor + 1);
      entries.push(artwork);
      if (entries.length > depth) entries = entries.slice(entries.length - depth);
      cursor = entries.length - 1;
    },

    /** Move the cursor without adding anything — used when going back or forward. */
    step(delta) {
      const next = cursor + delta;
      if (next < 0 || next >= entries.length) return null;
      cursor = next;
      return entries[cursor];
    },

    canGoBack() {
      return cursor > 0;
    },

    canGoForward() {
      return cursor >= 0 && cursor < entries.length - 1;
    },

    current() {
      return entries[cursor] ?? null;
    },

    /**
     * Forget everything.
     *
     * Called when the *source* changes, because a back stack that crosses museums would
     * offer to return to a Cleveland print while the display is set to the Art Institute —
     * and going back to it would then be showing an artwork the current settings exclude.
     */
    clear() {
      entries = [];
      cursor = -1;
    },

    /** How many are behind and ahead, for a control that has to know whether to dim. */
    position() {
      return { back: Math.max(cursor, 0), forward: Math.max(entries.length - 1 - cursor, 0) };
    },
  };
}
