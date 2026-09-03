// Fullscreen API wrapper. Thin, but it keeps the vendor-quirk handling out of main.js.

export function isFullscreen() {
  return document.fullscreenElement !== null;
}

/**
 * Requesting fullscreen needs a user gesture; calling this from a keydown handler
 * satisfies that. A rejection is not an error worth surfacing — the browser refused, the
 * app carries on windowed.
 */
export async function toggle(element = document.documentElement) {
  try {
    if (isFullscreen()) await document.exitFullscreen();
    else await element.requestFullscreen();
  } catch (error) {
    console.warn('Fullscreen request refused by the browser.', error);
  }
}

export async function exit() {
  if (!isFullscreen()) return;
  try {
    await document.exitFullscreen();
  } catch (error) {
    console.warn('Leaving fullscreen failed.', error);
  }
}
