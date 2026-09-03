// Entry point: wiring. The pieces it joins each own one concern.

import { createAmbient, isSupported as ambientSupported } from './ambient.js';
import {
  fetchHealth,
  fetchInterpretation,
  fetchPreferences,
  fetchRandomArtwork,
  savePreferences,
} from './api.js';
import { createPanel } from './panel.js';
import { chooseWidth, loadImage, present } from './display.js';
import * as fullscreen from './fullscreen.js';
import { getLanguage, onLanguageChange, setLanguage, t } from './i18n.js';
import { createInterpretation } from './interpretation.js';
import { createOverlay } from './overlay.js';
import { DEFAULT_INTERVAL_SECONDS, createRotation } from './rotation.js';
import { bindShortcuts } from './shortcuts.js';
import {
  getState,
  setArtwork,
  setError,
  setIntervalSeconds,
  setLoading,
  setOverlayPinned,
} from './state.js';

// How many artworks to skip past before giving up, when images will not load. Each retry
// costs an AIC request, so this is deliberately small.
const MAX_IMAGE_ATTEMPTS = 3;

// How long a transient confirmation stays on screen.
const FLASH_MS = 1600;

// The floor between manual advances, shared by Space and the overlay's next button.
// Holding Space down, or leaning on the button, otherwise walks the collection at the
// keyboard's repeat rate — every one of which is an image fetch from AIC's CDN. A repeat
// inside the window is ignored, never queued: a queued advance arrives after the user has
// stopped asking for it. The backend limit in M9 is the real ceiling; this is the part
// that keeps the display from being the thing that needs limiting.
const ADVANCE_COOLDOWN_MS = 1500;

const elements = {
  artworkEl: document.getElementById('artwork'),
  layers: [document.getElementById('layer-a'), document.getElementById('layer-b')],
  status: document.getElementById('status'),
  body: document.body,
};

const nextButton = document.getElementById('ov-next');

const overlay = createOverlay({
  overlay: document.getElementById('overlay'),
  title: document.getElementById('ov-title'),
  artist: document.getElementById('ov-artist'),
  meta: document.getElementById('ov-meta'),
  description: document.getElementById('ov-description'),
  credit: document.getElementById('ov-credit'),
  attribution: document.getElementById('ov-attribution'),
  expandButton: document.getElementById('ov-expand'),
});

const ambient = createAmbient();

const interpretation = createInterpretation({
  section: document.getElementById('ov-ai'),
  status: document.getElementById('ai-status'),
  body: document.getElementById('ai-body'),
  visual: document.getElementById('ai-visual'),
  reading: document.getElementById('ai-reading'),
  themes: document.getElementById('ai-themes'),
  lookCloser: document.getElementById('ai-look-closer'),
  source: document.getElementById('ai-source'),
});

// Whether the server has a provider at all. Read once from /api/health, so the display
// never asks for an interpretation only to be told the feature is off.
let aiEnabled = false;

// The in-flight request, so an artwork change or a second press can cancel it. An
// abandoned generation still costs money on a real provider.
let interpretationRequest = null;

// What the display is currently asking for. Persisted, so it survives a reload.
const query = { mode: 'random', artworkType: null, style: null, subject: null };

// Set when the criteria change while the panel is open, so closing it shows the result
// straight away instead of leaving the user to wait out the rest of the interval.
let queryChanged = false;

let flashTimer = null;

// When the next manual advance is allowed, and the timer that re-enables the button.
let advanceReadyAt = 0;
let advanceTimer = null;

// What the status line is saying, so a language change can say it again in the new
// language. An error can sit on screen for the whole retry delay.
let statusKey = null;

function showStatus(key) {
  clearTimeout(flashTimer);
  flashTimer = null;
  statusKey = key ?? null;
  if (!key) {
    elements.status.classList.remove('visible');
    return;
  }
  elements.status.textContent = t(key);
  elements.status.classList.add('visible');
}

/** A confirmation that takes itself away again — interval changes, pin toggles. */
function flashStatus(text) {
  clearTimeout(flashTimer);
  // Not retranslated on a language change: it is gone in under two seconds.
  statusKey = null;
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
  // source_width matters as much as the viewport: AIC refuses to upscale, and asking
  // for more than the source has is a 403 and a skipped artwork. See chooseWidth().
  const width = chooseWidth(window.innerWidth, window.devicePixelRatio, artwork.source_width);
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

/**
 * Ask for an interpretation of what is on screen.
 *
 * On demand only. This is called when someone pins the overlay open, never when the
 * overlay flashes on rotation — `docs/ai-system.md` puts an order of magnitude of cost on
 * that distinction, because most artworks are shown and never asked about.
 */
async function requestInterpretation() {
  const { artwork } = getState();
  if (!aiEnabled || !artwork) return;

  interpretationRequest?.abort();
  const controller = new AbortController();
  interpretationRequest = controller;

  interpretation.loading();
  try {
    const payload = await fetchInterpretation(artwork.id, getLanguage(), {
      signal: controller.signal,
    });
    // The artwork may have rotated away while we waited.
    if (controller.signal.aborted || getState().artwork?.id !== artwork.id) return;
    interpretation.render(payload);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    if (error?.code === 'ai_disabled') {
      // The server changed its mind since boot. Stop offering it rather than showing a
      // note about something the user never asked to be told.
      aiEnabled = false;
      interpretation.clear();
      return;
    }
    console.warn('Interpretation failed.', error);
    // A spent budget is a decision, not a fault, and reads differently on screen.
    interpretation.unavailable(
      error?.code === 'ai_budget_exhausted' ? 'ai_budget_exhausted' : 'ai_unavailable',
    );
  } finally {
    if (interpretationRequest === controller) interpretationRequest = null;
  }
}

function cancelInterpretation() {
  interpretationRequest?.abort();
  interpretationRequest = null;
  interpretation.clear();
}

function presentArtwork({ artwork, image }) {
  setArtwork(artwork);
  // The previous artwork's interpretation is about a picture nobody is looking at.
  cancelInterpretation();
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
    languageInputs: [...document.querySelectorAll('input[name="language"]')],
    ambientInput: document.getElementById('panel-ambient'),
    ambientGroup: document.getElementById('panel-ambient-group'),
    intervalList: document.getElementById('panel-intervals'),
    typeList: document.getElementById('panel-types'),
    styleList: document.getElementById('panel-styles'),
    styleGroup: document.getElementById('panel-style-group'),
    subjectList: document.getElementById('panel-subjects'),
    subjectGroup: document.getElementById('panel-subject-group'),
    summary: document.getElementById('panel-summary'),
    aiProviderInputs: [...document.querySelectorAll('input[name="ai-provider"]')],
    aiKeyInput: document.getElementById('panel-ai-key'),
    aiSaveButton: document.getElementById('panel-ai-save'),
    aiClearButton: document.getElementById('panel-ai-clear'),
    aiStatusLine: document.getElementById('panel-ai-status'),
    aiStorageLine: document.getElementById('panel-ai-storage'),
  },
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
      flashStatus(t(`mode_${mode}`));
    },
    onFilterChange: ({ artworkType, style, subject }) => {
      query.artworkType = artworkType;
      query.style = style;
      query.subject = subject;
      onQueryChanged();
    },
    onIntervalChange: (seconds) => {
      applyInterval(seconds);
      // applyInterval re-arms the clock, and the panel is open — hold it again, or the
      // picture starts changing underneath someone reading the settings. Closing the
      // panel starts the new interval from then.
      rotation.pause();
    },
    onAmbientChange: (on) => {
      void ambient.setEnabled(on);
      persist();
    },
    // A key saved or removed changes what the display may ask for, right now and
    // without a reload — which is the whole point of taking the key here rather than
    // telling the user to edit .env and restart.
    onAiChange: (status) => {
      aiEnabled = status?.enabled === true;
      if (!aiEnabled) cancelInterpretation();
      else if (getState().overlayPinned) void requestInterpretation();
    },
    onLanguageChange: async (code) => {
      await setLanguage(code);
      // A locale that would not load leaves the old one in effect, so the radio has to
      // be told what actually happened rather than being trusted to be right.
      panel.sync({ language: getLanguage() });
      persist();
    },
  },
);

function persist() {
  void savePreferences({
    interval_seconds: rotation.getIntervalSeconds(),
    mode: query.mode,
    artwork_type: query.artworkType,
    style: query.style,
    subject: query.subject,
    language: getLanguage(),
    ambient: ambient.isEnabled(),
  });
}

function onQueryChanged() {
  queryChanged = true;
  // The preloaded artwork was chosen under the old criteria. Keeping it would show one
  // last excluded work after the user changed their mind.
  rotation.invalidate();
  persist();
}

/**
 * Advance, unless we just did. The one path for every manual "next" — Space and the
 * overlay's button share the cooldown, because a user with both is still one user.
 *
 * Rotation's own timer does not come through here: it is already paced, and pausing the
 * clock to press Space should not then make the clock late.
 */
function advance() {
  if (Date.now() < advanceReadyAt) return;
  advanceReadyAt = Date.now() + ADVANCE_COOLDOWN_MS;
  armAdvanceButton();
  showStatus('loading');
  void rotation.next();
}

/** Dim and disable the button for the rest of the cooldown, then give it back. */
function armAdvanceButton() {
  if (!nextButton) return;
  nextButton.disabled = true;
  clearTimeout(advanceTimer);
  advanceTimer = setTimeout(() => {
    nextButton.disabled = false;
    advanceTimer = null;
  }, ADVANCE_COOLDOWN_MS);
}

nextButton?.addEventListener('click', advance);

bindShortcuts({
  onNext: advance,
  onFullscreen: () => void fullscreen.toggle(),
  onToggleOverlay: () => {
    const pinned = overlay.toggle();
    setOverlayPinned(pinned);
    flashStatus(t(pinned ? 'overlay_pinned' : 'overlay_unpinned'));
    // Pinning is the deliberate "I want to read about this", which is what the spec
    // means by generating on demand. The overlay's own flash on every rotation is not.
    if (pinned) void requestInterpretation();
    else cancelInterpretation();
  },
  onInterval: (seconds) => {
    applyInterval(seconds);
    panel.sync({ intervalSeconds: seconds });
  },
  // Toggle, not open. In fullscreen the browser owns Esc and uses it to leave
  // fullscreen, so a panel that only opens has no keyboard way out of the one state
  // this app is meant to sit in. QUESTIONS.md #2, amended.
  onSettings: () => (panel.isOpen() ? panel.hide() : void panel.show()),
  onDismissOverlay: () => {
    overlay.dismiss();
    setOverlayPinned(false);
    cancelInterpretation();
  },
  onExitFullscreen: () => void fullscreen.exit(),
  isSettingsOpen: () => panel.isOpen(),
  onCloseSettings: () => panel.hide(),
  isOverlayVisible: () => overlay.isVisible(),
});

/** Set the rotation interval, save it, and say so. Shared by the keys and the panel. */
function applyInterval(seconds) {
  rotation.setIntervalSeconds(seconds);
  setIntervalSeconds(seconds);
  persist();
  // Under a minute reads as seconds; the rest read as minutes. "Every 0.5 min" is not
  // something anyone says.
  flashStatus(
    seconds < 60
      ? t('interval_set_seconds', { seconds })
      : t('interval_set_minutes', { minutes: seconds / 60 }),
  );
}

/**
 * Retranslate the text this module and the panel own. Markup with a `data-i18n` key is
 * handled inside i18n.js; what is left is text built from data — the caption of the
 * artwork already on screen, the filter list, a status message mid-retry.
 */
function retranslate() {
  const { artwork } = getState();
  if (artwork) overlay.render(artwork);
  panel.retranslate();
  interpretation.retranslate();
  if (statusKey) elements.status.textContent = t(statusKey);
  // The generated text is in the old language and cannot be translated locally — it has
  // to be asked for again, and only if it was on screen in the first place.
  if (interpretation.hasContent()) void requestInterpretation();
}

onLanguageChange(retranslate);

/** Restore saved settings, then put the first artwork up. */
async function boot() {
  setIntervalSeconds(DEFAULT_INTERVAL_SECONDS);

  const saved = await fetchPreferences();
  // Before anything paints. Both calls are same-origin and quick, and starting in
  // English only to redraw in Polish a moment later is a flash on a display whose whole
  // point is that nothing moves unless it means to.
  await setLanguage(saved?.language);
  showStatus('loading');
  if (saved?.interval_seconds) {
    rotation.setIntervalSeconds(saved.interval_seconds);
    setIntervalSeconds(saved.interval_seconds);
  }
  if (saved?.mode) query.mode = saved.mode;
  if (saved?.artwork_type) query.artworkType = saved.artwork_type;
  if (saved?.style) query.style = saved.style;
  if (saved?.subject) query.subject = saved.subject;

  if (ambientSupported()) {
    // No user gesture is needed for a wake lock, only a visible document, so a saved
    // preference can be honoured at boot rather than waiting to be re-clicked.
    if (saved?.ambient) await ambient.setEnabled(true);
  } else {
    panel.hideAmbient();
  }

  panel.sync({
    mode: query.mode,
    artworkType: query.artworkType,
    style: query.style,
    subject: query.subject,
    language: getLanguage(),
    ambient: ambient.isEnabled(),
    intervalSeconds: rotation.getIntervalSeconds(),
  });

  // Before the first artwork, so pinning the overlay immediately still works.
  const health = await fetchHealth();
  aiEnabled = health?.ai?.enabled === true;

  await rotation.start();
}

void boot();
