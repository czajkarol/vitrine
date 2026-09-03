// The rotation clock. Owns *when* the next artwork appears, never *what* it is —
// choosing and loading is injected as `prepare`, painting as `present`.

export const INTERVAL_MINUTES = [1, 5, 15, 30];
export const DEFAULT_INTERVAL_MINUTES = 5;

// How far ahead of the deadline the next artwork is fetched and decoded, so the swap
// itself is instant. Capped at a third of the interval so the 1-minute setting still
// spends most of its time showing a picture rather than preparing the next one.
const PRELOAD_LEAD_MS = 30_000;

// After a failed attempt, come back well before the next scheduled slot. The error the
// user is looking at says "retrying shortly", and on a 30-minute interval a full wait
// would make that a lie. Short enough to recover from a blip, long enough not to hammer
// an API that is already unhappy.
const RETRY_DELAY_MS = 20_000;

const MINUTE_MS = 60_000;

/**
 * @param {object} deps
 * @param {() => Promise<object>} deps.prepare  resolve to a ready-to-paint artwork
 * @param {(prepared: object) => void} deps.present  paint one
 * @param {(error: Error) => void} deps.onError
 */
export function createRotation({ prepare, present, onError }) {
  let intervalMs = DEFAULT_INTERVAL_MINUTES * MINUTE_MS;
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

  const leadMs = () => Math.min(PRELOAD_LEAD_MS, intervalMs / 3);

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
    if (stopped) return;
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
    let failed = false;
    try {
      const prepared = await work;
      if (stopped) return;
      present(prepared);
    } catch (error) {
      failed = true;
      if (!stopped) onError(error);
    } finally {
      running = false;
      if (!stopped) {
        // Measured from when the artwork actually appeared, not from when it was due.
        deadline = Date.now() + (failed ? RETRY_DELAY_MS : intervalMs);
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
      return advance();
    },

    /** Manual advance. Resets the interval, per docs/product-spec.md. */
    next() {
      return advance();
    },

    getIntervalMinutes() {
      return intervalMs / MINUTE_MS;
    },

    /** Change the interval and restart the clock from now. */
    setIntervalMinutes(minutes) {
      if (!INTERVAL_MINUTES.includes(minutes)) {
        throw new Error(`unsupported interval: ${minutes}`);
      }
      intervalMs = minutes * MINUTE_MS;
      deadline = Date.now() + intervalMs;
      arm();
    },

    /** Hold the clock while the settings panel is open. The prepared artwork is kept. */
    pause() {
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
      deadline = Date.now() + intervalMs;
      arm();
    },

    destroy() {
      stopped = true;
      clearTimers();
      pending = null;
      document.removeEventListener('visibilitychange', onVisibilityChange);
    },
  };
}
