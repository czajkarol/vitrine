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

/** Pick a cached width for this screen. */
export function chooseWidth(viewportWidth, pixelRatio) {
  const wanted = viewportWidth * (pixelRatio || 1);
  return CACHED_WIDTHS.find((w) => w >= wanted) ?? CACHED_WIDTHS[CACHED_WIDTHS.length - 1];
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
  const direct = () => directImageUrl(artwork.iiif_base, artwork.image_id, width);
  const proxied = () => proxiedImageUrl(artwork.image_id, width);

  if (preferProxy) {
    return decodeImage(proxied(), artwork.alt_text);
  }

  try {
    return await decodeImage(direct(), artwork.alt_text);
  } catch (cause) {
    // Could be a Cloudflare challenge, or this one image being unpublished. The retry
    // distinguishes them: if the proxy succeeds, the image is fine and hotlinking is not.
    const image = await decodeImage(proxied(), artwork.alt_text);
    preferProxy = true;
    console.info('Direct AIC image load failed; using the backend proxy for this session.', cause);
    return image;
  }
}

function decodeImage(url, altText) {
  const img = new Image();
  img.decoding = 'async';
  img.alt = altText || '';
  img.src = url;
  return img.decode().then(() => img);
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
  // desaturated and darkened so it reads as a ground rather than a colour cast.
  if (artwork.color) {
    const { h, s } = artwork.color;
    body.style.backgroundColor = `hsl(${h}deg ${Math.min(s, 30)}% 7%)`;
  } else {
    body.style.backgroundColor = '';
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
