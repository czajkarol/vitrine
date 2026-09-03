// The only module that calls fetch(). Everything else takes data from here.

/**
 * Fetch one random public-domain artwork.
 * @returns {Promise<object>} the artwork payload
 * @throws {Error} with a `code` property keyed to a message the UI can translate
 */
export async function fetchRandomArtwork({ mode, artworkType } = {}) {
  const params = new URLSearchParams();
  if (mode && mode !== 'random') params.set('mode', mode);
  if (artworkType) params.set('artwork_type', artworkType);
  const query = params.toString();

  let response;
  try {
    response = await fetch(`/api/artwork/random${query ? `?${query}` : ''}`, {
      headers: { Accept: 'application/json' },
    });
  } catch (cause) {
    throw withCode(new Error('network request failed'), 'network_unreachable', cause);
  }

  if (!response.ok) {
    // 404 here means the filters matched nothing, which is the user's doing and needs a
    // different message from the museum being unreachable.
    const code =
      response.status === 404
        ? 'no_matching_artwork'
        : response.status === 503
          ? 'aic_unavailable'
          : 'artwork_unavailable';
    throw withCode(new Error(`HTTP ${response.status}`), code);
  }
  return response.json();
}

/** The Explore vocabulary: artwork types the index can actually sustain, with counts. */
export async function fetchFilters() {
  try {
    const response = await fetch('/api/filters', { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/** Build the direct AIC IIIF URL. */
export function directImageUrl(iiifBase, imageId, width) {
  return `${iiifBase.replace(/\/$/, '')}/${imageId}/full/${width},/0/default.jpg`;
}

/** Build the same-origin proxy URL — the ADR-0008 fallback. */
export function proxiedImageUrl(imageId, width) {
  return `/api/image/${encodeURIComponent(imageId)}?w=${width}`;
}

/** Read saved preferences. Failure is not fatal — the defaults still work. */
export async function fetchPreferences() {
  try {
    const response = await fetch('/api/preferences', { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/** Persist preferences. Fire-and-forget: a failed save must not interrupt the display. */
export async function savePreferences(preferences) {
  try {
    await fetch('/api/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preferences),
    });
  } catch (error) {
    console.warn('Could not save preferences.', error);
  }
}

function withCode(error, code, cause) {
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}
