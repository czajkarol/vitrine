// Entry point: wiring. The pieces it joins each own one concern.

import { fetchPreferences, fetchRandomArtwork, savePreferences } from './api.js';
import { createPanel } from './panel.js';
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
  no_matching_artwork: 'Nothing in the index matches those filters.',
  filter_any: 'Any type',
  filters_no_index: 'No local index yet — run scripts/build_index.py to enable filters.',
  filters_summary: (total) => `${total.toLocaleString()} artworks indexed.`,
  filters_too_thin: (minimum) =>
    `No type has ${minimum} or more artworks behind it yet. Index more to enable filters.`,
  mode_set: (mode) => (mode === 'curated' ? 'Curated' : 'Random'),
  untitled: 'Untitled',
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

// What the display is currently asking for. Persisted, so it survives a reload.
const query = { mode: 'random', artworkType: null };

// Set when the criteria change while the panel is open, so closing it shows the result
// straight away instead of leaving the user to wait out the rest of the interval.
let queryChanged = false;

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
  const artwork = await fetchRandomArtwork(query);
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

const panel = createPanel(
  {
    panel: document.getElementById('panel'),
    modeInputs: [...document.querySelectorAll('input[name="mode"]')],
    typeList: document.getElementById('panel-types'),
    summary: document.getElementById('panel-summary'),
  },
  MESSAGES,
  {
    // A panel you are reading should not have the picture change underneath it.
    onOpen: () => rotation.pause(),
    onClose: () => {
      if (!queryChanged) {
        rotation.resume();
        return;
      }
      queryChanged = false;
      // next() re-arms the timer itself, so there is no resume() to pair with this.
      showStatus('loading');
      void rotation.next();
    },
    onModeChange: (mode) => {
      query.mode = mode;
      onQueryChanged();
      flashStatus(MESSAGES.mode_set(mode));
    },
    onFilterChange: (artworkType) => {
      query.artworkType = artworkType;
      onQueryChanged();
    },
  },
);

function persist() {
  void savePreferences({
    interval_minutes: rotation.getIntervalMinutes(),
    mode: query.mode,
    artwork_type: query.artworkType,
  });
}

function onQueryChanged() {
  queryChanged = true;
  // The preloaded artwork was chosen under the old criteria. Keeping it would show one
  // last excluded work after the user changed their mind.
  rotation.invalidate();
  persist();
}

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
    persist();
    flashStatus(MESSAGES.interval_set(minutes));
  },
  onSettings: () => void panel.show(),
  onDismissOverlay: () => {
    overlay.dismiss();
    setOverlayPinned(false);
  },
  onExitFullscreen: () => void fullscreen.exit(),
  isSettingsOpen: () => panel.isOpen(),
  onCloseSettings: () => panel.hide(),
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
  if (saved?.mode) query.mode = saved.mode;
  if (saved?.artwork_type) query.artworkType = saved.artwork_type;
  panel.sync({ mode: query.mode, artworkType: query.artworkType });

  await rotation.start();
}

void boot();
