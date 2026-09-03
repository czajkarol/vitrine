// The only module that calls fetch(). Everything else takes data from here.

/**
 * Fetch one random public-domain artwork.
 * @returns {Promise<object>} the artwork payload
 * @throws {Error} with a `code` property keyed to a message the UI can translate
 */
export async function fetchRandomArtwork({ mode, artworkType, style, subject, exclude } = {}) {
  const params = new URLSearchParams();
  if (mode && mode !== 'random') params.set('mode', mode);
  if (artworkType) params.set('artwork_type', artworkType);
  if (style) params.set('style', style);
  if (subject) params.set('subject', subject);
  // Repeatable, unlike the three above: excluding several things at once is ordinary.
  for (const facet of exclude ?? []) params.append('exclude', facet);
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
        : response.status === 429
          ? 'too_many_requests'
          : response.status === 503
            ? 'aic_unavailable'
            : 'artwork_unavailable';
    const error = withCode(new Error(`HTTP ${response.status}`), code);
    // The server said how long to wait. Carrying it on the error is what lets the
    // rotation wait exactly that long instead of guessing, and is the difference between
    // backing off and retry-storming a limiter that is already refusing us.
    if (response.status === 429) error.retryAfterSeconds = retryAfter(response);
    throw error;
  }
  return response.json();
}

/**
 * `Retry-After`, in seconds, or null if the header is missing or unusable.
 *
 * Only the delta-seconds form is read. The HTTP-date form is also legal, and no server we
 * talk to sends it — parsing a date against a clock that may be wrong, to decide how long
 * to wait, is a worse answer than the caller's own default.
 */
function retryAfter(response) {
  const raw = response.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/**
 * The Explore vocabulary: the facets the index can actually sustain, with counts.
 *
 * The current selection goes with the request so the counts come back *dependent* — each
 * group counted under the other groups' choices. Without it the panel would show what a
 * facet is worth in the whole index while the rotation is already narrowed, which is the
 * number that is not useful.
 */
export async function fetchFilters({ artworkType, style, subject, exclude } = {}) {
  const params = new URLSearchParams();
  if (artworkType) params.set('artwork_type', artworkType);
  if (style) params.set('style', style);
  if (subject) params.set('subject', subject);
  for (const facet of exclude ?? []) params.append('exclude', facet);
  const query = params.toString();
  try {
    const response = await fetch(`/api/filters${query ? `?${query}` : ''}`, {
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Ask for one artwork's interpretation. Called only when someone asks for it — never on
 * rotation, which is where the cost of this feature would otherwise come from.
 *
 * @throws {Error} with a `code`: `ai_disabled` when nothing is configured, which is an
 * ordinary state, or `ai_unavailable` when a provider was there and did not answer.
 */
export async function fetchInterpretation(artworkId, language, { signal } = {}) {
  let response;
  try {
    response = await fetch(
      `/api/interpretation/${encodeURIComponent(artworkId)}?language=${encodeURIComponent(language)}`,
      { headers: { Accept: 'application/json' }, signal },
    );
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause;
    throw withCode(new Error('network request failed'), 'network_unreachable', cause);
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => null);
    throw withCode(new Error(`HTTP ${response.status}`), detail ?? 'ai_unavailable');
  }
  return response.json();
}

/** What the server can do. Read once at boot to decide whether to offer AI at all. */
export async function fetchHealth() {
  try {
    const response = await fetch('/api/health', { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * The key situation: whether a provider is live, where its key is kept, and the last
 * four characters of it. Never the key — the server has no endpoint that returns one.
 */
export async function fetchAiKey() {
  try {
    const response = await fetch('/api/ai/key', { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Save the user's own API key. Takes effect without a restart, so the answer carries the
 * new state and the caller does not have to ask again.
 *
 * @throws {Error} with a `code`: `ai_key_invalid` for something that cannot be a key,
 * `key_store_unavailable` when the keyring refused, `ai_key_failed` otherwise.
 */
export async function saveAiKey(provider, apiKey) {
  let response;
  try {
    response = await fetch('/api/ai/key', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey }),
    });
  } catch (cause) {
    throw withCode(new Error('network request failed'), 'network_unreachable', cause);
  }
  if (!response.ok) {
    // 422 is the shape check in app/api/schemas.py: whitespace, length, non-ASCII. It
    // says nothing about whether the vendor would accept the key, and neither do we.
    throw withCode(
      new Error(`HTTP ${response.status}`),
      response.status === 422
        ? 'ai_key_invalid'
        : response.status === 503
          ? 'key_store_unavailable'
          : 'ai_key_failed',
    );
  }
  return response.json();
}

/** Forget the stored key. The server falls back to .env, or to no AI at all. */
export async function deleteAiKey() {
  let response;
  try {
    response = await fetch('/api/ai/key', { method: 'DELETE' });
  } catch (cause) {
    throw withCode(new Error('network request failed'), 'network_unreachable', cause);
  }
  if (!response.ok) {
    throw withCode(new Error(`HTTP ${response.status}`), 'ai_key_failed');
  }
  return response.json();
}

/**
 * Like or hide one artwork.
 *
 * The snapshot goes with it because the server may never have seen this artwork: the
 * display's second and third tiers serve straight from AIC and from the bundled set, and
 * a favourite has to survive a rebuilt index either way.
 */
export async function saveFeedback(artwork, kind) {
  const response = await fetch(`/api/favorites/${encodeURIComponent(artwork.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      kind,
      title: artwork.title ?? null,
      artist: artwork.artist ?? null,
      image_id: artwork.image_id ?? null,
    }),
  });
  if (!response.ok) throw withCode(new Error(`HTTP ${response.status}`), 'feedback_failed');
  return response.json();
}

/** Forget a like or a hide. Idempotent — forgetting nothing is not an error. */
export async function clearFeedback(artworkId) {
  const response = await fetch(`/api/favorites/${encodeURIComponent(artworkId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw withCode(new Error(`HTTP ${response.status}`), 'feedback_failed');
}

/** Everything liked (or hidden), most recent first. */
export async function fetchFavorites(kind = 'like') {
  try {
    const response = await fetch(`/api/favorites?kind=${encodeURIComponent(kind)}`, {
      headers: { Accept: 'application/json' },
    });
    return response.ok ? await response.json() : [];
  } catch {
    return [];
  }
}

/** How much "For you" has to work with. Null when the server will not say. */
export async function fetchFeedbackSummary() {
  try {
    const response = await fetch('/api/favorites/summary', {
      headers: { Accept: 'application/json' },
    });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

/** The curated weights, straight from the code, so the panel's explanation cannot drift. */
export async function fetchScoring() {
  try {
    const response = await fetch('/api/scoring', { headers: { Accept: 'application/json' } });
    return response.ok ? await response.json() : null;
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
