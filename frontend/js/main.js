// Entry point: wiring. The pieces it joins each own one concern.

import { fetchPreferences, fetchRandomArtwork, savePreferences } from './api.js';
import { chooseWidth, loadImage, present } from './display.js';
import * as fullscreen from './fullscreen.js';
import { createOverlay } from './overlay.js';
import { DEFAULT_INTERVAL_MINUTES, createRotation } from './rotation.js';
import { bindShortcuts } from './shortcuts.js';
import { setArtwork, setError, setIntervalMinutes, setLoading, setOverlayPinned } from './state.js';

// Every user-visible string is keyed, including errors — they are the ones most often
// left hardcoded. M4 moves this table into locales/en.json and locales/pl.json.
const MESSAGES = {
  loading: 'Loading…',
  network_unreachable: 'Cannot reach the server.',
  aic_unavailable: 'The Art Institute is not responding. Retrying shortly.',
  artwork_unavailable: 'No artwork available right now.',
  image_unavailable: 'That image could not be loaded. Trying another.',
  attribution: 'Digital image courtesy of the Art Institute of Chicago.',
  attribution_with_description:
    'Digital image courtesy of the Art Institute of Chicago. Description: Art Institute of Chicago, CC BY 4.0.',
  interval_set: (minutes) => `Every ${minutes} min`,
  overlay_pinned: 'Details pinned',
  overlay_unpinned: 'Details unpinned',
};

// How many artworks to skip past before giving up, when images will not load. Each retry
// costs an AIC request, so this is deliberately small.
const MAX_IMAGE_ATTEMPTS = 3;

// How long a transient confirmation stays on screen.
const FLASH_MS = 1600;

const elements = {
  artworkEl: document.getElementById('artwork'),
  layers: [document.getElementById('layer-a'), document.getElementById('layer-b')],
  status: document.getElementById('status'),
  body: document.body,
};

const overlay = createOverlay(
  {
    overlay: document.getElementById('overlay'),
    title: document.getElementById('ov-title'),
    artist: document.getElementById('ov-artist'),
    meta: document.getElementById('ov-meta'),
    description: document.getElementById('ov-description'),
    credit: document.getElementById('ov-credit'),
    attribution: document.getElementById('ov-attribution'),
  },
  MESSAGES,
);

let flashTimer = null;

function showStatus(key) {
  clearTimeout(flashTimer);
  flashTimer = null;
  if (!key) {
    elements.status.classList.remove('visible');
    return;
  }
  elements.status.textContent = MESSAGES[key] ?? key;
  elements.status.classList.add('visible');
}

/** A confirmation that takes itself away again — interval changes, pin toggles. */
function flashStatus(text) {
  clearTimeout(flashTimer);
  elements.status.textContent = text;
  elements.status.classList.add('visible');
  flashTimer = setTimeout(() => {
    elements.status.classList.remove('visible');
    flashTimer = null;
  }, FLASH_MS);
}

/**
 * Fetch one artwork and decode its image, so that presenting it later is instant.
 * Skips past artworks whose image will not load, which is the spec's "drop it from the
 * rotation and advance" rule.
 */
async function prepareArtwork(attemptsLeft = MAX_IMAGE_ATTEMPTS) {
  const artwork = await fetchRandomArtwork();
  const width = chooseWidth(window.innerWidth, window.devicePixelRatio);
  try {
    const image = await loadImage(artwork, width);
    return { artwork, image };
  } catch (cause) {
    console.warn('Image failed for artwork', artwork.id, cause);
    if (attemptsLeft > 1) return prepareArtwork(attemptsLeft - 1);
    const error = new Error('image unavailable after retries');
    error.code = 'image_unavailable';
    error.cause = cause;
    throw error;
  }
}

function presentArtwork({ artwork, image }) {
  setArtwork(artwork);
  present(elements, artwork, image);
  overlay.render(artwork);
  // Surfaced briefly on every change: it says what you are looking at, and it is what
  // credits the Art Institute, which CLAUDE.md makes non-negotiable. Stillness fades it.
  overlay.flash();
  showStatus(null);
  setLoading(false);
}

function onPrepareError(error) {
  setError(error);
  showStatus(error.code ?? 'artwork_unavailable');
  setLoading(false);
}

const rotation = createRotation({
  prepare: () => {
    setLoading(true);
    return prepareArtwork();
  },
  present: presentArtwork,
  onError: onPrepareError,
});

bindShortcuts({
  onNext: () => {
    showStatus('loading');
    void rotation.next();
  },
  onFullscreen: () => void fullscreen.toggle(),
  onToggleOverlay: () => {
    const pinned = overlay.toggle();
    setOverlayPinned(pinned);
    flashStatus(pinned ? MESSAGES.overlay_pinned : MESSAGES.overlay_unpinned);
  },
  onInterval: (minutes) => {
    rotation.setIntervalMinutes(minutes);
    setIntervalMinutes(minutes);
    void savePreferences({ interval_minutes: minutes });
    flashStatus(MESSAGES.interval_set(minutes));
  },
  onDismissOverlay: () => {
    overlay.dismiss();
    setOverlayPinned(false);
  },
  onExitFullscreen: () => void fullscreen.exit(),
  // Settings is M4. These two keep the Esc priority chain honest until it exists.
  isSettingsOpen: () => false,
  onCloseSettings: () => {},
  isOverlayVisible: () => overlay.isVisible(),
});

/** Restore saved settings, then put the first artwork up. */
async function boot() {
  setIntervalMinutes(DEFAULT_INTERVAL_MINUTES);
  showStatus('loading');

  const saved = await fetchPreferences();
  if (saved?.interval_minutes) {
    rotation.setIntervalMinutes(saved.interval_minutes);
    setIntervalMinutes(saved.interval_minutes);
  }

  await rotation.start();
}

void boot();
