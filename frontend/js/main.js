// Entry point: wiring. The pieces it joins each own one concern.

import { createAccess } from './access.js';
import { createAmbient, isSupported as ambientSupported } from './ambient.js';
import {
  clearFeedback,
  fetchHealth,
  fetchInterpretation,
  fetchPreferences,
  fetchRandomArtwork,
  fetchVisualDescription,
  saveFeedback,
  savePreferences,
} from './api.js';
import { createPanel } from './panel.js';
import { chooseWidth, loadImage, present } from './display.js';
import * as fullscreen from './fullscreen.js';
import { createHistory } from './history.js';
import { getLanguage, onLanguageChange, setLanguage, t } from './i18n.js';
import { createInterpretation } from './interpretation.js';
import { createOverlay } from './overlay.js';
import { DEFAULT_INTERVAL_SECONDS, createRotation } from './rotation.js';
import { bindShortcuts } from './shortcuts.js';
import { createSpeech } from './speech.js';
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

// The rotation floor the accessibility description imposes, in seconds.
//
// A spoken description takes the better part of a minute to hear, and the artwork rotating
// away mid-sentence would make the feature useless at the two shortest settings. Asked for
// by the owner as "at least five minutes", and applied as a floor rather than as a new
// interval: the user's 30-second choice is still theirs and comes back when this lifts.
const DESCRIBED_FLOOR_SECONDS = 300;

const elements = {
  artworkEl: document.getElementById('artwork'),
  layers: [document.getElementById('layer-a'), document.getElementById('layer-b')],
  status: document.getElementById('status'),
  body: document.body,
};

const stage = document.getElementById('stage');
const nextButton = document.getElementById('ov-next');
const backButton = document.getElementById('ov-back');
const likeButton = document.getElementById('ov-like');
const dislikeButton = document.getElementById('ov-dislike');
const describeButton = document.getElementById('ov-describe');
const hideButton = document.getElementById('ov-hide');
const settingsButton = document.getElementById('ov-settings');

// The verdict on the artwork on screen: 'like', 'dislike', 'hide' or null. Set from the
// server's answer, never guessed, so a failed save leaves the buttons telling the truth.
let verdict = null;

const overlay = createOverlay(
  {
    overlay: document.getElementById('overlay'),
    facts: document.getElementById('ov-facts'),
    title: document.getElementById('ov-title'),
    artist: document.getElementById('ov-artist'),
    meta: document.getElementById('ov-meta'),
    description: document.getElementById('ov-description'),
    extra: document.getElementById('ov-extra'),
    credit: document.getElementById('ov-credit'),
    attribution: document.getElementById('ov-attribution'),
    detailsHint: document.getElementById('ov-details-hint'),
  },
  {
    // Reading is not a moment to have the picture change. The idle fade was already
    // stretched for this; the clock was the other half of the same problem, and only one
    // of them had been solved.
    onExpandChange: (expanded) => {
      if (expanded) rotation.pause();
      else if (!panel.isOpen()) rotation.resume();
    },
  },
);

const ambient = createAmbient();
// Whether the ambient toggle was last set by hand. Going fullscreen turns ambient on for
// somebody who has never thought about it, and must not overrule somebody who has thought
// about it and said no — and a stored `false` cannot tell those two apart, because every
// save writes every field. Persisted, so the answer survives a reload.
let ambientByHand = false;
const speech = createSpeech();
const history = createHistory();

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

const access = createAccess(
  {
    section: document.getElementById('ov-access'),
    status: document.getElementById('access-status'),
    body: document.getElementById('access-body'),
    summary: document.getElementById('access-summary'),
    description: document.getElementById('access-description'),
    grounding: document.getElementById('access-grounding'),
    source: document.getElementById('access-source'),
    playButton: document.getElementById('access-play'),
    stopButton: document.getElementById('access-stop'),
  },
  speech,
);

// Whether the server has a provider at all, and whether that provider can also write an
// accessibility description. Read from /api/health, so the display never asks for
// something only to be told the feature is off.
let aiEnabled = false;
let aiDescribes = false;

// The in-flight requests, so an artwork change or a second press can cancel them. An
// abandoned generation still costs money on a real provider.
let interpretationRequest = null;
let describeRequest = null;

// What the display is currently asking for. Persisted, so it survives a reload.
// The three filter groups hold canonical facet keys and are ORed within a group and ANDed
// between them; `exclude` holds several, from any group — see app/domain/vocabulary.py,
// ADR-0009 and ADR-0014.
const query = {
  mode: 'random',
  museum: 'aic',
  artworkType: [],
  style: [],
  subject: [],
  exclude: [],
};

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
  try {
    return { artwork, image: await decodeFor(artwork) };
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
 * Decode one artwork's image at whatever width suits this screen.
 *
 * source_width matters as much as the viewport: AIC refuses to upscale, and asking for
 * more than the source has is a 403 and a skipped artwork. See chooseWidth(). A source
 * with no IIIF has already chosen the URL and the width is ignored — see loadImage().
 */
function decodeFor(artwork) {
  const width = chooseWidth(window.innerWidth, window.devicePixelRatio, artwork.source_width);
  return loadImage(artwork, width);
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
  if (!aiEnabled || !artwork || !canInterpret(artwork)) return;

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

/**
 * Ask for the accessibility description, or replay the one already here.
 *
 * Pressing `A` twice is a replay rather than a second generation: the text is on screen
 * and the server has it cached, so `access.speak()` costs nothing. That is the whole
 * reason replay is a control of its own.
 *
 * The first request also puts a floor under the rotation. A description takes most of a
 * minute to hear, and at the 30-second setting the artwork would be gone before the end of
 * it. The floor stays for the session — lifting it when the description was dismissed
 * would mean the clock speeding up under someone still listening.
 */
async function requestDescription() {
  const { artwork } = getState();
  if (!aiEnabled || !aiDescribes || !artwork || !canInterpret(artwork)) return;

  // Already on screen for this artwork: read it again, and do not ask anybody.
  if (access.hasContent()) {
    access.speak();
    return;
  }

  if (rotation.setFloorSeconds(DESCRIBED_FLOOR_SECONDS)) {
    flashStatus(t('access_slowed', { minutes: DESCRIBED_FLOOR_SECONDS / 60 }));
  }

  describeRequest?.abort();
  const controller = new AbortController();
  describeRequest = controller;

  access.loading();
  try {
    const payload = await fetchVisualDescription(artwork.id, getLanguage(), {
      signal: controller.signal,
    });
    if (controller.signal.aborted || getState().artwork?.id !== artwork.id) return;
    access.render(payload);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    if (error?.code === 'ai_disabled' || error?.code === 'access_unsupported') {
      // The server changed its mind since boot, or was never able to. Stop offering it.
      aiDescribes = false;
      syncDescribeButton();
      access.clear();
      return;
    }
    console.warn('Description failed.', error);
    // Three of these are ordinary states rather than faults, and each reads differently:
    // an artwork the museum has written nothing visual about, a spent budget, a provider
    // that is down.
    access.unavailable(
      ['access_not_describable', 'ai_budget_exhausted'].includes(error?.code)
        ? error.code
        : 'ai_unavailable',
    );
  } finally {
    if (describeRequest === controller) describeRequest = null;
  }
}

function cancelDescription() {
  describeRequest?.abort();
  describeRequest = null;
  access.clear();
}

/**
 * Record a verdict on what is on screen, or take it back.
 *
 * Pressing the same key twice clears it, which is what makes `L` and `D` reversible
 * without a third control. The state is set from what the server actually stored, not
 * optimistically: a display that says it saved your favourite and did not is worse than
 * one that says nothing.
 */
async function setVerdict(kind) {
  const { artwork } = getState();
  if (!artwork) return;
  const clearing = verdict === kind;
  try {
    if (clearing) {
      await clearFeedback(artwork.id, artwork.museum ?? 'aic');
      verdict = null;
    } else {
      await saveFeedback(artwork, kind);
      verdict = kind;
    }
  } catch (error) {
    console.warn('Could not save that.', error);
    flashStatus(t('feedback_failed'));
    return;
  }
  renderVerdict();
  flashStatus(t(clearing ? `un${kind}d` : `${kind}d`));
}

/**
 * Hide the artwork on screen: never show it again, in any mode.
 *
 * Advances afterwards, because the point of pressing it is not to look at this any more.
 * It goes through the shared cooldown like every other manual advance.
 */
async function hideArtwork() {
  const { artwork } = getState();
  if (!artwork) return;
  disarmHide();
  try {
    await saveFeedback(artwork, 'hide');
  } catch (error) {
    console.warn('Could not hide that.', error);
    flashStatus(t('feedback_failed'));
    return;
  }
  verdict = 'hide';
  renderVerdict();
  flashStatus(t('hidden'));
  // The preloaded artwork was chosen before this one was hidden, and is fine — but the
  // one just hidden must not come back on the next rotation.
  advance();
}

// --- Never show this one again, as a button --------------------------------------
//
// `docs/product-spec.md` refused this control until M18 and the reasoning was sound: the
// artwork leaves the screen the moment it lands, so a mis-click is a permanent decision the
// user cannot see well enough to undo. What was wrong was the conclusion. The answer to an
// irreversible control is a confirm step, not no control — leaving the one verdict that
// matters most reachable only by a key nobody had been told about.
//
// So it arms on the first click and acts on the second, and forgets after a few seconds.
// `X` stays a single press: a key nobody hits by accident does not need the guard.
const HIDE_CONFIRM_MS = 4000;

let hideArmed = false;
let hideArmTimer = null;

function disarmHide() {
  clearTimeout(hideArmTimer);
  hideArmTimer = null;
  if (!hideArmed) return;
  hideArmed = false;
  hideButton?.removeAttribute('data-armed');
  hideButton?.setAttribute('aria-label', t('hide_artwork'));
}

function armHide() {
  hideArmed = true;
  hideButton?.setAttribute('data-armed', 'true');
  // The label changes as well as the styling, so the state is not carried by colour alone
  // and a screen reader hears that the next press is the one that acts.
  hideButton?.setAttribute('aria-label', t('hide_artwork_confirm'));
  flashStatus(t('hide_confirm'));
  clearTimeout(hideArmTimer);
  hideArmTimer = setTimeout(disarmHide, HIDE_CONFIRM_MS);
}

function onHideClick() {
  if (hideArmed) void hideArtwork();
  else armHide();
}

function renderVerdict() {
  if (likeButton) {
    likeButton.setAttribute('aria-pressed', String(verdict === 'like'));
    // Filled when given, outline when not. The glyph carries the state as well as the
    // styling, so it survives a stylesheet that has not loaded.
    likeButton.textContent = verdict === 'like' ? '♥' : '♡';
  }
  if (dislikeButton) {
    dislikeButton.setAttribute('aria-pressed', String(verdict === 'dislike'));
    dislikeButton.textContent = verdict === 'dislike' ? '⬇' : '⇩';
  }
}

function syncNavButtons() {
  if (backButton) backButton.disabled = !history.canGoBack();
}

/**
 * Whether the AI features apply to this artwork at all.
 *
 * Only to the Art Institute's, and for two separate reasons that happen to agree. The
 * server can only find metadata for an artwork it can look up — the index, the bundled set
 * or AIC — and a live Cleveland record is in none of the three, so both endpoints would
 * answer "unknown artwork". And Cleveland has no `alt_text`, which is what grounds both
 * prompts: `CLAUDE.md` puts the museum's own visual description at the centre of this, and
 * a source without one would need a different prompt or no AI at all. ADR-0012 called
 * that a decision to take out loud rather than to arrive at by accident; ADR-0013 takes it,
 * and this line is where it is enforced.
 */
function canInterpret(artwork) {
  return (artwork?.museum ?? 'aic') === 'aic';
}

function syncDescribeButton() {
  if (!describeButton) return;
  const { artwork } = getState();
  describeButton.hidden = !(aiEnabled && aiDescribes && (!artwork || canInterpret(artwork)));
}

/**
 * Put one artwork on screen.
 *
 * @param {object} prepared  the artwork and its decoded image
 * @param {boolean} [record] whether this is a step *forward* worth remembering. False when
 * we are moving through the history stack, which must not push what it is replaying.
 */
function presentArtwork(prepared, { record = true } = {}) {
  const { artwork, image } = prepared;
  setArtwork(artwork);
  // The server sends it with the artwork, so the buttons are right on the first paint
  // rather than a moment later.
  verdict = artwork.feedback ?? (artwork.liked ? 'like' : null);
  renderVerdict();
  // An armed "never again" belongs to the artwork it was armed on. Carrying it across a
  // rotation would mean one click hiding a picture the user has not looked at yet.
  disarmHide();
  // The previous artwork's generated text is about a picture nobody is looking at.
  cancelInterpretation();
  cancelDescription();
  if (record) history.push(artwork);
  syncNavButtons();
  // The AI controls belong to the Art Institute's artworks — see canInterpret().
  syncDescribeButton();
  present(elements, artwork, image);
  overlay.render(artwork);
  // "For you" that is not personalising yet says so once, on the artwork it is showing
  // instead. Silently serving curated picks under a personal label is the one thing a
  // recommendation must not do.
  if (query.mode === 'personal' && artwork.personalised === false) {
    flashStatus(t('mode_personal_cold'));
  }
  // Surfaced briefly on every change: it says what you are looking at, and it is what
  // credits the museum, which CLAUDE.md makes non-negotiable. Stillness fades it.
  overlay.flash();
  showStatus(null);
  setLoading(false);
}

function onPrepareError(error) {
  setError(error);
  showStatus(error.code ?? 'artwork_unavailable');
  setLoading(false);
  // A refusal from the rate limiter is the one failure the user can make worse. Hold the
  // manual advance for as long as the server asked, so pressing Space at a limiter that
  // is already counting down cannot keep it counting. The rotation clock backs off on
  // its own — see retryDelayMs() in rotation.js.
  if (error.code === 'too_many_requests') holdAdvance(error.retryAfterSeconds);
}

const rotation = createRotation({
  prepare: () => {
    setLoading(true);
    return prepareArtwork();
  },
  present: presentArtwork,
  onError: onPrepareError,
});

/**
 * Go back, or forward, through what has already been shown.
 *
 * The image is re-decoded rather than held: a decoded 1686px bitmap is several megabytes
 * and this app runs for hours. It comes out of the browser's own HTTP cache, which is what
 * that cache is for, so this is normally instant and needs no request at all.
 *
 * Moving through history re-arms the clock the same way a manual advance does. Going back
 * to look at something and having it rotate away two seconds later is the opposite of what
 * the control is for.
 */
async function travel(delta) {
  const artwork = history.step(delta);
  if (!artwork) return;
  rotation.pause();
  showStatus('loading');
  try {
    const image = await decodeFor(artwork);
    presentArtwork({ artwork, image }, { record: false });
  } catch (error) {
    console.warn('Could not reload that artwork.', error);
    // AIC can unpublish an image between the first showing and the second. Step back to
    // where we were rather than leaving the cursor pointing at something unshowable.
    history.step(-delta);
    syncNavButtons();
    flashStatus(t('history_unavailable'));
  } finally {
    rotation.resume();
  }
}

const panel = createPanel(
  {
    panel: document.getElementById('panel'),
    modeGroup: document.getElementById('panel-mode-group'),
    modeInputs: [...document.querySelectorAll('input[name="mode"]')],
    museumInputs: [...document.querySelectorAll('input[name="museum"]')],
    languageInputs: [...document.querySelectorAll('input[name="language"]')],
    ambientInput: document.getElementById('panel-ambient'),
    ambientGroup: document.getElementById('panel-ambient-group'),
    intervalList: document.getElementById('panel-intervals'),
    // One entry per filter vocabulary, each pointing at the markup its group owns.
    // `group` names the markup; `prefix` names the facet namespace. They are the same
    // for two of the three and not for the first, which is exactly the sort of near-miss
    // that stays hidden until something matches on the wrong one.
    filterGroups: [
      { group: 'artwork-type', prefix: 'type', field: 'artworkType' },
      { group: 'style', prefix: 'style', field: 'style' },
      { group: 'subject', prefix: 'subject', field: 'subject' },
    ].map(({ group, prefix, field }) => ({
      group,
      prefix,
      field,
      root: document.querySelector(`[data-group="${group}"]`),
      list: document.querySelector(`[data-list="${group}"]`),
      count: document.querySelector(`[data-badge="${group}"]`),
      search: document.querySelector(`[data-search="${group}"]`),
    })),
    summary: document.getElementById('panel-summary'),
    // The sentence describing what a click does. It is `data-i18n` in the markup, but a
    // live source runs a two-state cycle and the panel rewrites it — see setExcludable.
    stateHint: document.getElementById('panel-filter-hint'),
    resetButton: document.getElementById('panel-reset-filters'),
    presetList: document.getElementById('panel-preset-list'),
    presetEmpty: document.getElementById('panel-preset-empty'),
    presetNote: document.getElementById('panel-preset-note'),
    presetNameInput: document.getElementById('panel-preset-name'),
    presetSaveButton: document.getElementById('panel-preset-save'),
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
    onMuseumChange: (museum, selection) => {
      query.museum = museum;
      applyFilters(selection);
      // Two museums, two id spaces and two vocabularies. A back stack that crossed them
      // would offer to return to an artwork the current source cannot show.
      history.clear();
      syncNavButtons();
      onQueryChanged();
      flashStatus(t(`museum_${museum}`));
    },
    onFilterChange: (selection) => {
      applyFilters(selection);
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
      // By hand, whichever way it was moved. Off is the half that matters — it is what
      // stops fullscreen turning it back on — but recording only that would leave "on by
      // hand" indistinguishable from "on by fullscreen", and the next thing to want this
      // would have to guess.
      ambientByHand = true;
      void ambient.setEnabled(on);
      persist();
    },
    // A key saved or removed changes what the display may ask for, right now and
    // without a reload — which is the whole point of taking the key here rather than
    // telling the user to edit .env and restart.
    onAiChange: (status) => {
      aiEnabled = status?.enabled === true;
      // A new key may be a different vendor, and only some vendors write descriptions.
      // Ask the server rather than guessing from the name — no module outside
      // providers/ai/ is allowed to know which vendors can do what.
      void refreshAiCapabilities();
      if (!aiEnabled) {
        cancelInterpretation();
        cancelDescription();
      } else if (getState().overlayPinned) void requestInterpretation();
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

function applyFilters({ artworkType, style, subject, exclude }) {
  query.artworkType = artworkType ?? [];
  query.style = style ?? [];
  query.subject = subject ?? [];
  query.exclude = exclude ?? [];
}

async function refreshAiCapabilities() {
  const health = await fetchHealth();
  aiEnabled = health?.ai?.enabled === true;
  aiDescribes = health?.ai?.describes === true;
  syncDescribeButton();
}

function persist() {
  void savePreferences({
    interval_seconds: rotation.getIntervalSeconds(),
    mode: query.mode,
    museum: query.museum,
    artwork_type: query.artworkType,
    style: query.style,
    subject: query.subject,
    exclude: query.exclude,
    language: getLanguage(),
    ambient: ambient.isEnabled(),
    ambient_by_hand: ambientByHand,
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
  holdAdvance();
  showStatus('loading');
  void rotation.next();
}

/**
 * Refuse manual advances for a while, and show that we are refusing them.
 *
 * Disabled and dimmed rather than hidden: a control that disappears under the cursor is
 * worse than one that visibly will not answer yet.
 *
 * @param {number} [seconds] how long, when the server has told us. Default is the
 * ordinary cooldown between two deliberate presses.
 */
function holdAdvance(seconds) {
  const ms = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : ADVANCE_COOLDOWN_MS;
  advanceReadyAt = Date.now() + ms;
  if (!nextButton) return;
  nextButton.disabled = true;
  clearTimeout(advanceTimer);
  advanceTimer = setTimeout(() => {
    nextButton.disabled = false;
    advanceTimer = null;
  }, ms);
}

/**
 * A left click on the artwork: take everything but the picture away. Click again for it back.
 *
 * **Windowed as well as fullscreen since M17.** It was fullscreen-only on the argument that
 * windowed there is chrome around the page already, so the gesture would be a click that
 * silently changed a mode. That was right about the silence and wrong about the remedy: the
 * way out of the mode is the same click that got you into it, on the same spot, and having
 * to enter fullscreen first to reach the one gesture the display has is a worse cost than
 * the one it was avoiding.
 *
 * **And it no longer says anything.** The status line used to name what had happened, on the
 * reasoning that a click hiding every control also hides the way back. But it does not: the
 * way back is to click again, which is what somebody who has just clicked is best placed to
 * discover. Meanwhile the message was chrome appearing at the top of the screen at the exact
 * moment the user asked for less of it, which is the opposite of what they clicked for.
 *
 * A click on one of the overlay's own buttons is not this — those stop the event themselves
 * by being buttons, and the check below keeps a click on the caption, or in the settings
 * panel, from counting either.
 *
 * **It waits a moment first, because a double click means something else now.** Doing the
 * work on the first click and again on the second would hide the chrome and put it back on
 * the way to fullscreen — a flicker at exactly the moment the display is changing size.
 * `event.detail` identifies the second click, and the pending first one is cancelled by the
 * `dblclick` handler below. The delay is only felt on the single-click gesture, and it is
 * shorter than the fade it starts.
 */
const DOUBLE_CLICK_MS = 250;

let stageClickTimer = null;

function isStageGesture(event) {
  return !event.target.closest('.ov-button, .facts, .ov-description, .panel');
}

function toggleSuppressed() {
  const suppressed = !overlay.isSuppressed();
  overlay.setSuppressed(suppressed);
  if (suppressed) {
    cancelInterpretation();
    cancelDescription();
    disarmHide();
    setOverlayPinned(false);
  }
}

function onStageClick(event) {
  if (event.button !== 0 || event.detail > 1) return;
  if (!isStageGesture(event)) return;
  clearTimeout(stageClickTimer);
  stageClickTimer = setTimeout(() => {
    stageClickTimer = null;
    toggleSuppressed();
  }, DOUBLE_CLICK_MS);
}

/**
 * Open the settings, or close them again.
 *
 * Toggle, not open. In fullscreen the browser owns Esc and uses it to leave fullscreen, so
 * a panel that only opens has no keyboard way out of the one state this app is meant to sit
 * in. QUESTIONS.md #2, amended.
 *
 * Shared by `S` and by the gear in the overlay. The gear exists because `S` is not an
 * affordance: somebody who has only ever used the mouse had no way to find out from the
 * screen that the app had settings at all.
 */
function toggleSettings() {
  if (panel.isOpen()) panel.hide();
  else void panel.show();
}

/**
 * A double click on the artwork: in or out of fullscreen.
 *
 * The gesture every video player and every image viewer has, and the app did not — `F` was
 * the only way in, and a key is not something anyone finds by using a display with a mouse.
 * It runs from the `dblclick` handler rather than from a counted pair of clicks because the
 * browser owns the threshold, and because `requestFullscreen` needs a user gesture to be
 * granted: a call out of a timer of our own is not one.
 */
function onStageDoubleClick(event) {
  if (event.button !== 0) return;
  if (!isStageGesture(event)) return;
  clearTimeout(stageClickTimer);
  stageClickTimer = null;
  void fullscreen.toggle();
}

/**
 * Going fullscreen turns ambient mode on.
 *
 * `docs/product-spec.md` argued ambient off by default because keeping somebody's screen
 * awake is a side effect on their machine. That argument holds windowed and does not hold
 * here: fullscreen *is* the ask, and a display that blanks ten minutes into the one mode
 * it was built for is the failure the wake lock exists to prevent. The spec carries the
 * amendment rather than the contradiction.
 *
 * Three things it must not do. It must not overrule a user who turned ambient off by hand
 * — hence `ambientByHand`. It must not touch the preference on a browser with no Screen
 * Wake Lock API, where the toggle is removed from the panel outright and saving `true`
 * would record a setting the user cannot see or undo. And it must not *say* the screen
 * will stay awake unless a lock is genuinely held: the request can be refused on battery,
 * and `setEnabled` swallows that by design.
 *
 * On `fullscreenchange` rather than on our own toggle, because F11 is fullscreen too and
 * never goes through `fullscreen.toggle()`. Leaving fullscreen does not turn it back off:
 * it is the user's saved preference now, shown in the panel and undoable there.
 */
async function onFullscreenChange() {
  if (!fullscreen.isFullscreen()) return;
  // No API, no toggle in the panel, and nothing here may imply otherwise.
  if (!ambientSupported()) return;
  if (ambientByHand || ambient.isEnabled()) return;
  await ambient.setEnabled(true);
  panel.sync({ ambient: ambient.isEnabled() });
  persist();
  // Only if it actually took. Enabled and holding are different questions.
  if (ambient.isHolding()) flashStatus(t('ambient_on_fullscreen'));
}

document.addEventListener('fullscreenchange', () => void onFullscreenChange());

// --- The pointer is chrome, and it goes away like the rest of it --------------------
//
// Slower than the overlay's own 3.5s fade on purpose. The overlay reappears on the next
// mouse movement and costs nothing to bring back; a cursor that vanishes while somebody
// is still deciding where to click is a different kind of annoyance, so it waits until
// the movement has genuinely stopped.
const CURSOR_IDLE_MS = 6000;

let cursorTimer = null;
let cursorHidden = false;

/**
 * One self-rescheduling timer, not a new one per mousemove.
 *
 * `pointermove` fires dozens of times a second and this display runs for hours; churning
 * a timer per event is the accumulation `frontend/CLAUDE.md` warns about, and it is the
 * same shape `overlay.js` uses for the same reason.
 *
 * This lives here rather than beside that one because it has to know whether the settings
 * panel is open, and `overlay.js` has no business knowing that. A cursor that disappears
 * while somebody is reading a form is worse than one that never disappears at all.
 */
function cursorTick() {
  const idle = Date.now() - lastPointerAt;
  if (idle < CURSOR_IDLE_MS) {
    cursorTimer = setTimeout(cursorTick, CURSOR_IDLE_MS - idle);
    return;
  }
  cursorTimer = null;
  if (panel.isOpen()) return;
  document.body.classList.add('cursor-idle');
  cursorHidden = true;
}

let lastPointerAt = Date.now();

function wakeCursor() {
  lastPointerAt = Date.now();
  if (cursorHidden) {
    document.body.classList.remove('cursor-idle');
    cursorHidden = false;
  }
  if (cursorTimer === null) cursorTimer = setTimeout(cursorTick, CURSOR_IDLE_MS);
}

// `pointermove` rather than `mousemove`: a touch or a pen should bring it back too.
// Passive, because nothing here calls preventDefault and the listener is on every move.
document.addEventListener('pointermove', wakeCursor, { passive: true });
// A press is presence too, and a click with a hidden pointer should put it back.
document.addEventListener('pointerdown', wakeCursor, { passive: true });
// Opening the panel with `S` must put the pointer back, or the first thing the user has
// to do in a form they just opened is find their mouse.
document.addEventListener('keydown', wakeCursor);
wakeCursor();

nextButton?.addEventListener('click', advance);
backButton?.addEventListener('click', () => void travel(-1));
likeButton?.addEventListener('click', () => void setVerdict('like'));
dislikeButton?.addEventListener('click', () => void setVerdict('dislike'));
describeButton?.addEventListener('click', () => void requestDescription());
hideButton?.addEventListener('click', onHideClick);
settingsButton?.addEventListener('click', () => void toggleSettings());
document.getElementById('access-play')?.addEventListener('click', () => access.speak());
document.getElementById('access-stop')?.addEventListener('click', () => access.stop());
stage?.addEventListener('click', onStageClick);
stage?.addEventListener('dblclick', onStageDoubleClick);

bindShortcuts({
  onNext: advance,
  onBack: () => void travel(-1),
  onForward: () => void travel(1),
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
  onSettings: toggleSettings,
  onExpandDetails: () => overlay.toggleDetails(),
  onHelp: () => void panel.showSection('panel-help'),
  onLike: () => void setVerdict('like'),
  onDislike: () => void setVerdict('dislike'),
  onHide: () => void hideArtwork(),
  onDescribe: () => void requestDescription(),
  onDismissOverlay: () => {
    overlay.dismiss();
    setOverlayPinned(false);
    cancelInterpretation();
    cancelDescription();
    disarmHide();
  },
  /**
   * Keep this one up a while longer.
   *
   * Says the running total rather than the step, because after three presses "five more
   * minutes" is the wrong number and the one thing somebody holding an artwork wants to
   * know is how long they have. At the ceiling it says so instead of silently doing
   * nothing, which is the difference between a limit and a broken key.
   */
  onHold: () => {
    const heldSeconds = rotation.extend();
    if (heldSeconds === null) {
      flashStatus(t('hold_limit'));
      return;
    }
    flashStatus(t('hold_extended', { minutes: Math.round(heldSeconds / 60) }));
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
  // i18n.applyTo has just written the resting label back over the armed one.
  if (hideArmed) hideButton?.setAttribute('aria-label', t('hide_artwork_confirm'));
  interpretation.retranslate();
  access.retranslate();
  if (statusKey) elements.status.textContent = t(statusKey);
  // The generated text is in the old language and cannot be translated locally — it has
  // to be asked for again, and only if it was on screen in the first place. The spoken
  // description is not re-read automatically: a voice starting up unprompted after a
  // settings change is not something anybody asked for.
  if (interpretation.hasContent()) void requestInterpretation();
  if (access.hasContent()) {
    access.clear();
    void requestDescription();
  }
}

onLanguageChange(retranslate);

/** Restore saved settings, then put the first artwork up. */
async function boot() {
  setIntervalSeconds(DEFAULT_INTERVAL_SECONDS);
  // The voice list loads asynchronously and is empty on first call in Chrome, so asking
  // for a Polish voice the moment somebody presses `A` would get the default one.
  speech.prime();

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
  if (saved?.museum) query.museum = saved.museum;
  applyFilters({
    artworkType: saved?.artwork_type,
    style: saved?.style,
    subject: saved?.subject,
    exclude: saved?.exclude,
  });

  if (ambientSupported()) {
    // No user gesture is needed for a wake lock, only a visible document, so a saved
    // preference can be honoured at boot rather than waiting to be re-clicked.
    if (saved?.ambient) await ambient.setEnabled(true);
    // Restored before anything can go fullscreen, because it is what decides whether
    // going fullscreen is allowed to change the preference at all.
    ambientByHand = saved?.ambient_by_hand === true;
  } else {
    panel.hideAmbient();
  }

  panel.sync({
    mode: query.mode,
    museum: query.museum,
    artworkType: query.artworkType,
    style: query.style,
    subject: query.subject,
    exclude: query.exclude,
    language: getLanguage(),
    ambient: ambient.isEnabled(),
    intervalSeconds: rotation.getIntervalSeconds(),
  });

  // Before the first artwork, so pinning the overlay immediately still works.
  await refreshAiCapabilities();
  syncNavButtons();

  await rotation.start();
}

void boot();
