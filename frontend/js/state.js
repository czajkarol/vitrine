// All mutable state, in one place, behind explicit setters.
// No event bus, no global sprawl — there are only a handful of transitions.
//
// Timer bookkeeping is deliberately not here: rotation.js owns its own deadline. What
// lives here is the state a user would recognise, which is what M4 persists.

const state = {
  artwork: null,
  loading: false,
  error: null,
  intervalSeconds: 300,
  overlayPinned: false,
};

export function getState() {
  return { ...state };
}

export function setArtwork(artwork) {
  state.artwork = artwork;
  state.error = null;
}

export function setLoading(loading) {
  state.loading = loading;
}

export function setError(error) {
  state.error = error;
}

export function setIntervalSeconds(seconds) {
  state.intervalSeconds = seconds;
}

export function setOverlayPinned(pinned) {
  state.overlayPinned = pinned;
}
