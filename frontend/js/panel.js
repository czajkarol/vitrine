// The settings panel. M3 gives it mode and Explore filters; M4 adds language and AI.
//
// Opening it pauses rotation and closing resumes, per docs/product-spec.md — a panel you
// are reading should not have the picture change underneath it.

import { fetchFilters } from './api.js';
import { t } from './i18n.js';

export function createPanel(elements, handlers) {
  const { panel, modeInputs, typeList, summary } = elements;

  let open = false;
  let loaded = false;
  // The filter vocabulary as fetched. Kept so a language change can relabel the list
  // without asking the server for it again.
  let filters = null;
  // The panel's idea of the current settings, kept because the filter list is built
  // lazily on first open — long after preferences were restored at boot. Without this the
  // radio would read "Any type" while the rotation was actually filtered.
  let current = { mode: 'random', artworkType: null };

  function applySelection() {
    for (const input of modeInputs) input.checked = input.value === current.mode;
    const target = [...typeList.querySelectorAll('input')].find(
      (input) => input.value === (current.artworkType ?? ''),
    );
    if (target) target.checked = true;
  }

  async function loadFilters() {
    if (loaded) return;
    loaded = true;
    filters = await fetchFilters();
    renderFilters();
  }

  /** Build the type list from `filters`. Idempotent, so a relabel is just another call. */
  function renderFilters() {
    typeList.textContent = '';

    if (!filters || filters.artwork_types.length === 0) {
      // No index yet, or nothing with enough behind it. Say so rather than showing an
      // empty box the user cannot interpret.
      summary.textContent = filters?.indexed_total
        ? t('filters_too_thin', { minimum: filters.minimum_count })
        : t('filters_no_index');
      return;
    }

    summary.textContent = t('filters_summary', { total: filters.indexed_total });
    typeList.appendChild(buildOption(t('filter_any'), '', true));
    for (const option of filters.artwork_types) {
      // The type names themselves are AIC's vocabulary and arrive in English. They are
      // data, not interface text, so they are not translated.
      const label = t('filter_option', { value: option.value, count: option.count });
      typeList.appendChild(buildOption(label, option.value, false));
    }
  }

  function buildOption(label, value, checked) {
    const wrapper = document.createElement('label');
    wrapper.className = 'panel-option';

    const input = document.createElement('input');
    input.type = 'radio';
    input.name = 'artwork-type';
    input.value = value;
    input.defaultChecked = checked;
    input.addEventListener('change', () => {
      current = { ...current, artworkType: value || null };
      handlers.onFilterChange(current.artworkType);
    });

    const text = document.createElement('span');
    text.textContent = label;

    wrapper.append(input, text);
    return wrapper;
  }

  for (const input of modeInputs) {
    input.addEventListener('change', () => {
      current = { ...current, mode: input.value };
      handlers.onModeChange(current.mode);
    });
  }

  return {
    async show() {
      open = true;
      panel.classList.add('visible');
      panel.removeAttribute('inert');
      await loadFilters();
      // After the list exists, not before — see `current` above.
      applySelection();
      handlers.onOpen();
    },

    hide() {
      if (!open) return;
      open = false;
      panel.classList.remove('visible');
      // inert keeps the hidden panel out of the tab order and off screen readers.
      panel.setAttribute('inert', '');
      handlers.onClose();
    },

    isOpen() {
      return open;
    },

    /** Reflect restored preferences without firing change handlers. */
    sync(next) {
      current = { ...current, ...next };
      applySelection();
    },

    /**
     * Relabel everything this module built itself. The markup's own labels are handled
     * by i18n.applyTo(); this covers the list built from /api/filters.
     */
    retranslate() {
      if (!loaded) return;
      renderFilters();
      applySelection();
    },
  };
}
