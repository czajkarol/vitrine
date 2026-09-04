// The rotation clock. Owns *when* the next artwork appears, never *what* it is —
// choosing and loading is injected as `prepare`, painting as `present`.

// Seconds, because the shortest rung is half a minute. 30s / 1m / 5m / 15m / 30m.
export const INTERVAL_SECONDS = [30, 60, 300, 900, 1800];
export const DEFAULT_INTERVAL_SECONDS = 300;

// How far ahead of the deadline the next artwork is fetched and decoded, so the swap
// itself is instant. Capped at a third of the interval so the shortest setting still
// spends most of its time showing a picture rather than preparing the next one — at 30
// seconds that is a 10-second lead, which a cached IIIF image and a local index clear.
const PRELOAD_LEAD_MS = 30_000;

// After a failed attempt, come back well before the next scheduled slot. The error the
// user is looking at says "retrying shortly", and on a 30-minute interval a full wait
// would make that a lie. Short enough to recover from a blip, long enough not to hammer
// an API that is already unhappy.
const RETRY_DELAY_MS = 20_000;

const SECOND_MS = 1000;

// A backstop on a server-supplied Retry-After. A limiter is not supposed to hand back
// anything like this much, and a display that has silently stopped for an hour because
// something upstream said so is worse than one that tries again and is refused again.
const MAX_RETRY_DELAY_MS = 120_000;

/**
 * How long to wait after a failure.
 *
 * When the server has said — a 429 carries `Retry-After` — believe it. Coming back on
 * our own 20-second schedule while a limiter is still counting down is exactly the
 * retry storm the limiter exists to stop, and it is our own request that would be
 * refused.
 */
function retryDelayMs(error) {
  const seconds = error?.retryAfterSeconds;
  if (!Number.isFinite(seconds) || seconds <= 0) return RETRY_DELAY_MS;
  return Math.min(seconds * SECOND_MS, MAX_RETRY_DELAY_MS);
}

/**
 * @param {object} deps
 * @param {() => Promise<object>} deps.prepare  resolve to a ready-to-paint artwork
 * @param {(prepared: object) => void} deps.present  paint one
 * @param {(error: Error) => void} deps.onError
 */
export function createRotation({ prepare, present, onError }) {
  let intervalMs = DEFAULT_INTERVAL_SECONDS * SECOND_MS;
  // A floor under the interval, applied without changing what the user chose.
  //
  // The accessibility description is the reason it exists. A spoken description takes the
  // better part of a minute to hear, and a display set to 30 seconds would rotate away
  // mid-sentence — so asking for one raises the floor to five minutes for the rest of the
  // session. A floor rather than an assignment, because the 30-second setting is still the
  // user's and should come back the moment this is lifted.
  let floorMs = 0;
  // Absolute wall-clock time, not a countdown. Browsers throttle timers in hidden tabs
  // to roughly once a minute, so a timer that "should" have fired may not have. Keeping
  // the deadline as a timestamp lets visibilitychange work out the truth from the clock
  // instead of trusting that the interval fired on schedule.
  let deadline = 0;
  let advanceTimer = null;
  let preloadTimer = null;
  let pending = null;
  let stopped = false;
  let running = false;
  // Held by the settings panel and by the expanded details. A flag rather than only
  // clearing the timers, because clearing them is not enough: an `advance()` that was
  // already in flight when the hold was asked for re-arms the clock in its own `finally`,
  // and the hold is silently lost. That window is a second or so on every advance —
  // fetching an artwork and decoding its image — and it is the *whole* window at page
  // load, which is where this was found: expanding the details half a second after the
  // app opened, and watching the artwork change 30 seconds later anyway.
  let paused = false;

  /** What the clock actually runs at: the chosen interval, or the floor if it is higher. */
  const effectiveMs = () => Math.max(intervalMs, floorMs);

  const leadMs = () => Math.min(PRELOAD_LEAD_MS, effectiveMs() / 3);

  function clearTimers() {
    clearTimeout(advanceTimer);
    clearTimeout(preloadTimer);
    advanceTimer = null;
    preloadTimer = null;
  }

  function startPreload() {
    if (pending || stopped) return;
    const work = prepare();
    // The rejection is handled where `pending` is awaited in advance(). Attaching a sink
    // here as well keeps a preload that fails early from surfacing as an unhandled
    // rejection minutes before anyone looks at it.
    work.catch(() => {});
    pending = work;
  }

  /** Set both timers from the current deadline. Safe to call repeatedly. */
  function arm() {
    clearTimers();
    if (stopped || paused) return;
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      void advance();
      return;
    }
    const preloadIn = remaining - leadMs();
    if (preloadIn <= 0) startPreload();
    else preloadTimer = setTimeout(startPreload, preloadIn);
    advanceTimer = setTimeout(() => void advance(), remaining);
  }

  async function advance() {
    if (stopped || running) return;
    running = true;
    clearTimers();
    const work = pending ?? prepare();
    pending = null;
    let failure = null;
    try {
      const prepared = await work;
      if (stopped) return;
      present(prepared);
    } catch (error) {
      failure = error ?? new Error('prepare failed');
      if (!stopped) onError(error);
    } finally {
      running = false;
      if (!stopped) {
        // Measured from when the artwork actually appeared, not from when it was due.
        deadline = Date.now() + (failure ? retryDelayMs(failure) : effectiveMs());
        arm();
      }
    }
  }

  function onVisibilityChange() {
    if (stopped || document.visibilityState !== 'visible') return;
    // Back in the foreground: believe the clock, not the timers. If the deadline slid
    // past while we were throttled, arm() advances immediately rather than waiting out
    // a stale timeout.
    arm();
  }

  document.addEventListener('visibilitychange', onVisibilityChange);

  return {
    /** Show one immediately, then keep going. */
    start() {
      stopped = false;
      paused = false;
      return advance();
    },

    /** Manual advance. Resets the interval, per docs/product-spec.md. */
    next() {
      // Advancing is the clock running, so it lifts a hold rather than working around
      // one. Closing the settings panel after changing a filter takes this path instead
      // of `resume()`, and without this the clock would stay held for ever.
      paused = false;
      return advance();
    },

    getIntervalSeconds() {
      return intervalMs / SECOND_MS;
    },

    /** What the clock is running at right now, floor included. */
    getEffectiveSeconds() {
      return effectiveMs() / SECOND_MS;
    },

    /**
     * Hold the interval at or above `seconds` without changing the saved preference.
     *
     * @returns {boolean} whether this actually slowed anything down, so the caller can say
     * so once rather than announcing a floor that was already below the chosen interval.
     */
    setFloorSeconds(seconds) {
      const next = Math.max(0, seconds) * SECOND_MS;
      if (next === floorMs) return false;
      const wasBinding = floorMs > intervalMs;
      floorMs = next;
      const isBinding = floorMs > intervalMs;
      // Only re-arm when the effective interval actually moved. Restarting the clock
      // because a floor was set below the chosen interval would reset the countdown for no
      // reason the user could see.
      if (wasBinding || isBinding) {
        deadline = Date.now() + effectiveMs();
        arm();
      }
      return isBinding;
    },

    /** Change the interval and restart the clock from now. */
    setIntervalSeconds(seconds) {
      if (!INTERVAL_SECONDS.includes(seconds)) {
        throw new Error(`unsupported interval: ${seconds}`);
      }
      intervalMs = seconds * SECOND_MS;
      deadline = Date.now() + effectiveMs();
      arm();
    },

    /**
     * Hold the clock — the settings panel is open, or the details are expanded. The
     * prepared artwork is kept.
     *
     * The flag matters as much as the `clearTimers()`: an advance already in flight will
     * otherwise re-arm on its way out and the hold will have done nothing.
     */
    pause() {
      paused = true;
      clearTimers();
    },

    /**
     * Throw away the preloaded artwork.
     *
     * Call this when the *criteria* change. The pending artwork was fetched under the old
     * mode and filter, so presenting it would show something the user has just excluded —
     * a coin arriving one time after they asked for paintings.
     */
    invalidate() {
      pending = null;
    },

    resume() {
      paused = false;
      deadline = Date.now() + effectiveMs();
      arm();
    },

    /** Whether the clock is currently held. Exposed for tests and for the e2e flow. */
    isPaused() {
      return paused;
    },

    destroy() {
      stopped = true;
      paused = false;
      clearTimers();
      pending = null;
      document.removeEventListener('visibilitychange', onVisibilityChange);
    },
  };
}
