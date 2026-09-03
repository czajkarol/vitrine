// Translation. Every user-visible string comes from locales/, error messages included —
// those are the ones most often left hardcoded, so they get no exemption here.
//
// Templates carry `{name}` placeholders, filled from a params object. Numbers are
// formatted for the active locale on the way in: 57,607 in English, 57 607 in Polish.
//
// Markup is translated by attribute rather than by lookup from JS, so a label lives in
// one place: `data-i18n="key"` sets textContent, `data-i18n-aria-label="key"` sets the
// label a screen reader reads. The English text stays in index.html as what the browser
// paints before the locale arrives.

export const SUPPORTED_LANGUAGES = ['en', 'pl'];
const FALLBACK_LANGUAGE = 'en';

const TEXT_ATTRIBUTE = 'data-i18n';
const ARIA_LABEL_ATTRIBUTE = 'data-i18n-aria-label';

let language = FALLBACK_LANGUAGE;
let strings = {};
// English is kept loaded alongside whatever is current, so a key a translation has not
// caught up with shows the English words rather than its own name.
let fallbackStrings = {};

const listeners = new Set();

export function isSupported(candidate) {
  return SUPPORTED_LANGUAGES.includes(candidate);
}

export function getLanguage() {
  return language;
}

async function fetchLocale(code) {
  const response = await fetch(`/locales/${code}.json`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} loading locale ${code}`);
  return response.json();
}

async function ensureFallbackLoaded() {
  if (Object.keys(fallbackStrings).length > 0) return;
  try {
    fallbackStrings = await fetchLocale(FALLBACK_LANGUAGE);
  } catch (error) {
    // Only reachable if the static files themselves are broken. t() then echoes keys,
    // which is ugly but honest — better than a screen of blank labels.
    console.warn('Could not load the English locale; keys will show through.', error);
  }
}

/**
 * Load a language and make it current, then retranslate the document.
 *
 * A locale that will not load leaves the current one in place: a failed language switch
 * should cost the user their choice, not the words on screen.
 *
 * @returns {Promise<string>} the language actually in effect afterwards
 */
export async function setLanguage(code) {
  const target = isSupported(code) ? code : FALLBACK_LANGUAGE;
  await ensureFallbackLoaded();

  if (target === FALLBACK_LANGUAGE) {
    strings = fallbackStrings;
  } else {
    try {
      strings = await fetchLocale(target);
    } catch (error) {
      console.warn(`Could not load locale ${target}; staying on ${language}.`, error);
      return language;
    }
  }

  language = target;
  // Screen readers and hyphenation both key off this, and it is wrong the moment the
  // language changes if nobody updates it.
  document.documentElement.lang = language;
  applyTo(document);
  for (const listener of listeners) listener(language);
  return language;
}

/**
 * Translate one key.
 * @param {string} key
 * @param {Record<string, string | number>} [params] values for `{name}` placeholders
 */
export function t(key, params) {
  const template = strings[key] ?? fallbackStrings[key];
  if (template === undefined) {
    console.warn(`Missing translation for "${key}".`);
    return key;
  }
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (placeholder, name) =>
    name in params ? formatValue(params[name]) : placeholder,
  );
}

function formatValue(value) {
  return typeof value === 'number' ? value.toLocaleString(language) : String(value);
}

/** Re-translate every `data-i18n` element under `root`. */
export function applyTo(root = document) {
  for (const element of root.querySelectorAll(`[${TEXT_ATTRIBUTE}]`)) {
    element.textContent = t(element.getAttribute(TEXT_ATTRIBUTE));
  }
  for (const element of root.querySelectorAll(`[${ARIA_LABEL_ATTRIBUTE}]`)) {
    element.setAttribute('aria-label', t(element.getAttribute(ARIA_LABEL_ATTRIBUTE)));
  }
}

/**
 * Run `listener` whenever the language changes — for text this module cannot reach,
 * such as the current artwork's caption or a list built from API data.
 *
 * @returns {() => void} an unsubscribe function
 */
export function onLanguageChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
