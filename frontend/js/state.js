// All mutable state, in one place, behind explicit setters.
// No event bus, no global sprawl — there are only a handful of transitions.

const state = {
  artwork: null,
  loading: false,
  error: null,
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
