// Entry point. M0 puts one artwork on the screen; rotation and shortcuts arrive in M1.

import { fetchRandomArtwork } from './api.js';
import { chooseWidth, loadImage, present } from './display.js';
import { setArtwork, setError, setLoading } from './state.js';

// Every user-visible string is keyed, including errors — they are the ones most often
// left hardcoded. M4 moves this table into locales/en.json and locales/pl.json.
const MESSAGES = {
  loading: 'Loading…',
  network_unreachable: 'Cannot reach the server.',
  aic_unavailable: 'The Art Institute is not responding. Retrying shortly.',
  artwork_unavailable: 'No artwork available right now.',
  image_unavailable: 'That image could not be loaded. Trying another.',
};

const elements = {
  artworkEl: document.getElementById('artwork'),
  layers: [document.getElementById('layer-a'), document.getElementById('layer-b')],
  caption: document.getElementById('caption'),
  captionTitle: document.getElementById('caption-title'),
  captionArtist: document.getElementById('caption-artist'),
  status: document.getElementById('status'),
  body: document.body,
};

function showStatus(key) {
  if (!key) {
    elements.status.classList.remove('visible');
    return;
  }
  elements.status.textContent = MESSAGES[key] ?? key;
  elements.status.classList.add('visible');
}

function showCaption(artwork) {
  elements.captionTitle.textContent = artwork.title ?? '';
  const parts = [artwork.artist, artwork.date_display].filter(Boolean);
  elements.captionArtist.textContent = parts.join(', ');
  elements.caption.classList.add('visible');
}

/** Fetch, decode and present one artwork. Retries a few times on a dead image. */
async function showNextArtwork(attemptsLeft = 3) {
  setLoading(true);
  showStatus('loading');

  let artwork;
  try {
    artwork = await fetchRandomArtwork();
  } catch (error) {
    setError(error);
    showStatus(error.code ?? 'artwork_unavailable');
    setLoading(false);
    return;
  }

  const width = chooseWidth(window.innerWidth, window.devicePixelRatio);
  try {
    const image = await loadImage(artwork, width);
    setArtwork(artwork);
    present(elements, artwork, image);
    showCaption(artwork);
    showStatus(null);
  } catch (error) {
    // Both the direct URL and the proxy failed: treat the artwork as unusable and move
    // on rather than showing a broken frame.
    console.warn('Image failed for artwork', artwork.id, error);
    if (attemptsLeft > 1) {
      await showNextArtwork(attemptsLeft - 1);
      return;
    }
    setError(error);
    showStatus('image_unavailable');
  } finally {
    setLoading(false);
  }
}

showNextArtwork();
