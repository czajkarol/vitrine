// The only module that calls fetch(). Everything else takes data from here.

/**
 * Fetch one random public-domain artwork.
 * @returns {Promise<object>} the artwork payload
 * @throws {Error} with a `code` property keyed to a message the UI can translate
 */
export async function fetchRandomArtwork() {
  let response;
  try {
    response = await fetch('/api/artwork/random', { headers: { Accept: 'application/json' } });
  } catch (cause) {
    throw withCode(new Error('network request failed'), 'network_unreachable', cause);
  }

  if (!response.ok) {
    const code = response.status === 503 ? 'aic_unavailable' : 'artwork_unavailable';
    throw withCode(new Error(`HTTP ${response.status}`), code);
  }
  return response.json();
}

/** Build the direct AIC IIIF URL. */
export function directImageUrl(iiifBase, imageId, width) {
  return `${iiifBase.replace(/\/$/, '')}/${imageId}/full/${width},/0/default.jpg`;
}

/** Build the same-origin proxy URL — the ADR-0008 fallback. */
export function proxiedImageUrl(imageId, width) {
  return `/api/image/${encodeURIComponent(imageId)}?w=${width}`;
}

function withCode(error, code, cause) {
  error.code = code;
  if (cause) error.cause = cause;
  return error;
}
