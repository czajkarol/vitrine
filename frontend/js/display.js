// The transition pipeline. The one genuinely tricky file — see docs/product-spec.md.
//
// Paint the lqip blur, decode the real image off-screen, and only crossfade once decode()
// resolves. Using decode() rather than the load event is what makes the fade flicker-free:
// load fires before the bitmap is paintable.

import { directImageUrl, proxiedImageUrl } from './api.js';

// Only the widths AIC keeps cached. An arbitrary width is an edge-cache miss.
const CACHED_WIDTHS = [200, 400, 600, 843, 1686];

// AIC's IIIF service is behind Cloudflare, which challenges <img> requests it cannot
// verify. We try direct first — where it works, AIC's edge cache serves it — and fall back
// to our own backend once. Remembered for the session so we stop paying the failed round
// trip on every rotation. See ADR-0008.
let preferProxy = false;

// Cloudflare does not reliably *reject* a blocked hotlink. Sometimes the request simply
// never answers, and img.decode() then neither resolves nor rejects — measured in a real
// browser. Without a deadline the rotation stalls on "Loading…" forever, which is the one
// failure docs/product-spec.md rules out. The direct load is only a probe, so it gets a
// short leash.
const DIRECT_TIMEOUT_MS = 6_000;
// The proxy is our own backend pulling a full-size image on our behalf. Slower, but it
// answers, so it gets longer before we give up on the artwork entirely.
const PROXY_TIMEOUT_MS = 20_000;

// Above this lightness in AIC's own dominant colour, the artwork gets the stronger
// overlay scrim. 60 rather than 50 because the caption sits along the bottom edge, and a
// work whose *average* is mid-grey usually has something darker down there; the works
// that actually defeat the default scrim are prints and drawings on white paper, which
// come back far higher than this. Checked against both in a browser, which is the only
// way this number could have been chosen.
const LIGHT_GROUND_L = 60;

/**
 * Pick a cached width for this screen, never asking for more pixels than exist.
 *
 * The clamp is not an optimisation. AIC's IIIF service answers `403` for a width larger
 * than the source image — it will not upscale — and the display treats a `403` as an
 * image that will not load and skips the artwork. On a monitor wide enough to want 1686,
 * that silently dropped **8,993 of the 57,607 indexed works, one in six**, including
 * every one of them at whatever size they do have. Found in a browser on a print that
 * turned out to be 1602px wide; invisible to the test suite, which never asked AIC for a
 * width the fixture could not honour.
 *
 * `sourceWidth` is `thumbnail.width`, already on every artwork response.
 *
 * One record in the index is narrower than the smallest rung, and it still 403s and is
 * still skipped. Adding a `full/max` request for one artwork would put an uncached URL
 * shape in the code for the rest of them, which is the trade the width ladder exists to
 * avoid (`frontend/CLAUDE.md`).
 */
export function chooseWidth(viewportWidth, pixelRatio, sourceWidth = null) {
  const wanted = viewportWidth * (pixelRatio || 1);
  const forScreen =
    CACHED_WIDTHS.find((w) => w >= wanted) ?? CACHED_WIDTHS[CACHED_WIDTHS.length - 1];
  if (!sourceWidth) return forScreen;
  // The largest rung the source can actually satisfy — and never below the smallest,
  // because there is no rung under it to ask for.
  const available =
    [...CACHED_WIDTHS].reverse().find((w) => w <= sourceWidth) ?? CACHED_WIDTHS[0];
  return Math.min(forScreen, available);
}

/** True once a direct load has failed and the proxy became the default. */
export function isUsingProxy() {
  return preferProxy;
}

/**
 * Load and decode an artwork's image, falling back to the proxy on failure.
 * @returns {Promise<HTMLImageElement>} a decoded, paintable image
 */
export async function loadImage(artwork, width) {
  // A source with no IIIF service has already chosen the URL, and there is nothing to
  // pick a width from or to proxy through. Cleveland is that source: three fixed URLs per
  // record, of which one is a TIFF — ADR-0013. Its CDN serves an <img> directly, so the
  // Cloudflare dance below is not just unnecessary, it would be a request to a backend
  // route that only knows how to fetch from AIC.
  if (artwork.image_url) {
    return decodeImage(artwork.image_url, artwork.alt_text, PROXY_TIMEOUT_MS);
  }

  const direct = () => directImageUrl(artwork.iiif_base, artwork.image_id, width);
  const proxied = () => proxiedImageUrl(artwork.image_id, width);

  if (preferProxy) {
    return decodeImage(proxied(), artwork.alt_text, PROXY_TIMEOUT_MS);
  }

  try {
    return await decodeImage(direct(), artwork.alt_text, DIRECT_TIMEOUT_MS);
  } catch (cause) {
    // Could be a Cloudflare challenge, a stalled request, or this one image being
    // unpublished. The retry distinguishes them: if the proxy succeeds, the image is fine
    // and hotlinking is not.
    const image = await decodeImage(proxied(), artwork.alt_text, PROXY_TIMEOUT_MS);
    preferProxy = true;
    console.info('Direct AIC image load failed; using the backend proxy for this session.', cause);
    return image;
  }
}

/**
 * Resolve once the image is safe to put on screen.
 *
 * `decode()` is what makes the crossfade flicker-free — it resolves only when the browser
 * holds a paintable bitmap, where the `load` event fires earlier than that. But Chrome
 * never settles `decode()` while the tab is hidden (measured: pending indefinitely, while
 * the `load` event on the same image fires normally). An ambient display is hidden or
 * minimised for much of its life, so waiting on `decode()` alone strands the rotation on
 * "Loading…" every time the user looks away.
 *
 * So: `decode()` decides while the tab is visible, which is the only time a flicker could
 * be seen. While it is hidden, a completed load is accepted instead.
 */
function whenPaintable(img) {
  let cleanup = () => {};
  const settled = new Promise((resolve, reject) => {
    const onError = () => reject(new Error(`image failed to load: ${img.src}`));
    const settleIfHidden = () => {
      if (document.hidden && img.complete && img.naturalWidth > 0) resolve(img);
    };

    img.addEventListener('error', onError, { once: true });
    img.addEventListener('load', settleIfHidden);
    // Covers the tab being hidden *after* the load event but before decode() settles.
    document.addEventListener('visibilitychange', settleIfHidden);

    cleanup = () => {
      img.removeEventListener('error', onError);
      img.removeEventListener('load', settleIfHidden);
      document.removeEventListener('visibilitychange', settleIfHidden);
    };

    img.decode().then(() => resolve(img), onError);
  });

  return settled.finally(() => cleanup());
}

function decodeImage(url, altText, timeoutMs) {
  const img = new Image();
  img.decoding = 'async';
  img.alt = altText || '';
  img.src = url;

  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      // Abandon the in-flight request. Left alone it holds a connection and a partially
      // decoded bitmap, and this app starts a fresh image every rotation for hours.
      img.src = '';
      reject(new Error(`image load timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  return Promise.race([whenPaintable(img), deadline]).finally(() => {
    clearTimeout(timer);
  });
}

/**
 * Crossfade a decoded image onto the stage, with its blur placeholder beneath it.
 */
export function present(elements, artwork, image) {
  const { artworkEl, layers, body } = elements;

  if (artwork.lqip) {
    const incoming = layers.find((l) => !l.classList.contains('visible')) ?? layers[0];
    incoming.style.backgroundImage = `url("${artwork.lqip}")`;
    incoming.classList.add('visible');
    layers.filter((l) => l !== incoming).forEach((l) => l.classList.remove('visible'));
  }

  // Tint the page behind the letterboxing with the artwork's dominant colour, heavily
  // desaturated and *lightened* so it reads as a ground rather than a colour cast.
  //
  // The ground was near-black until M17 and is now a warm dark wall rather than a void.
  // Four values were tried in a browser to get here: ecru was too bright, a dark brown
  // was muddy, and a neutral grey at the right lightness was legible and dead. The
  // lightness and the saturation below are what carries warmth without mud.
  //
  // **The hue is the artwork's own, and that is the point of doing it here rather than
  // in CSS.** The wall shifts with what is hanging on it — cool behind a blue print,
  // umber behind a bronze — which is the one thing about this that reads as deliberate
  // rather than as a colour someone picked.
  //
  // The same colour's lightness also decides how hard the overlay scrim has to work: a
  // white-ground print needs a stronger and taller gradient than an oil painting, and
  // the caption is illegible over the first without one. AIC gives us `l` on every
  // response, so this costs no field, no request and no reading of the image itself.
  // The threshold is a judgement, not a measurement — see LIGHT_GROUND_L.
  if (artwork.color) {
    const { h, s, l } = artwork.color;
    body.style.backgroundColor = `hsl(${h}deg ${Math.min(s, 22)}% 33%)`;
    body.dataset.ground = l > LIGHT_GROUND_L ? 'light' : 'dark';
  } else {
    body.style.backgroundColor = '';
    // No colour reported is not evidence of a dark artwork. The stronger scrim is the
    // safe default: it costs a little contrast against a dark painting and rescues the
    // caption entirely against a pale one.
    body.dataset.ground = 'light';
  }

  artworkEl.classList.remove('visible');
  artworkEl.src = image.src;
  artworkEl.alt = artwork.alt_text || artwork.title || '';
  // Force a synchronous style recalculation so the browser registers opacity 0 before we
  // set it to 1, which is what makes the change transition instead of snapping.
  //
  // This was a requestAnimationFrame callback. Chrome does not run rAF in a backgrounded
  // or occluded tab, so the class was never added and the artwork stayed at opacity 0
  // indefinitely — on an ambient display left running for hours, a blank screen. Reading
  // offsetWidth is synchronous and runs regardless of tab visibility.
  void artworkEl.offsetWidth;
  artworkEl.classList.add('visible');
}
