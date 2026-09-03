// Ambient mode: hold a Screen Wake Lock so the display does not go dark mid-rotation.
//
// This is a display feature and nothing more — no OS-level power management, no simulated
// input (docs/product-spec.md). The browser keeps the screen on while a lock is held, and
// the user can always take it back by closing the tab.
//
// The lock is not ours to keep. Browsers release it whenever the document stops being
// visible — another tab, a minimised window, a locked machine — and do not hand it back on
// their own. So `visibilitychange` is not an optimisation here, it is the whole mechanism:
// without it, ambient mode works until the first time anyone looks at something else.
//
// Requires a secure context; localhost qualifies.

/** Whether this browser can do it at all. The toggle is hidden when it cannot. */
export function isSupported() {
  return 'wakeLock' in navigator;
}

export function createAmbient() {
  let enabled = false;
  let sentinel = null;

  function onSentinelRelease() {
    // Released by the browser, not by us — the tab was hidden, or the OS intervened.
    // Nothing to do now; visibilitychange asks for it back when the tab returns.
    sentinel = null;
  }

  async function acquire() {
    if (!enabled || sentinel || document.visibilityState !== 'visible') return;
    try {
      sentinel = await navigator.wakeLock.request('screen');
      sentinel.addEventListener('release', onSentinelRelease, { once: true });
    } catch (error) {
      // A rejection here is ordinary rather than exceptional: the browser refuses while
      // the document is hidden, and some setups refuse on battery. It is not worth a
      // message on screen — the next visibilitychange tries again.
      sentinel = null;
      console.warn('Could not acquire a screen wake lock.', error);
    }
  }

  async function release() {
    if (!sentinel) return;
    const held = sentinel;
    sentinel = null;
    held.removeEventListener('release', onSentinelRelease);
    try {
      await held.release();
    } catch (error) {
      // Already gone. Our state says the same thing either way.
      console.warn('Releasing the screen wake lock failed.', error);
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') void acquire();
  }

  document.addEventListener('visibilitychange', onVisibilityChange);

  return {
    /** Turn ambient mode on or off. Safe to call with the value it already has. */
    async setEnabled(next) {
      if (next === enabled) return;
      enabled = next;
      if (enabled) await acquire();
      else await release();
    },

    isEnabled() {
      return enabled;
    },

    async destroy() {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      enabled = false;
      await release();
    },
  };
}
