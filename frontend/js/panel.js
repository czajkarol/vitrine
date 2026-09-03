// The settings panel. M3 gives it mode and Explore filters; M4 adds language and AI.
//
// Opening it pauses rotation and closing resumes, per docs/product-spec.md — a panel you
// are reading should not have the picture change underneath it.

import { fetchFilters } from './api.js';

export function createPanel(elements, messages, handlers) {
  const { panel, modeInputs, typeList, summary } = elements;

  let open = false;
  let loaded = false;
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
    const data = await fetchFilters();
    typeList.textContent = '';

    if (!data || data.artwork_types.length === 0) {
      // No index yet, or nothing with enough behind it. Say so rather than showing an
      // empty box the user cannot interpret.
      summary.textContent = data?.indexed_total
        ? messages.filters_too_thin(data.minimum_count)
        : messages.filters_no_index;
      return;
    }

    summary.textContent = messages.filters_summary(data.indexed_total);
    typeList.appendChild(buildOption(messages.filter_any, '', true));
    for (const option of data.artwork_types) {
      typeList.appendChild(buildOption(`${option.value} (${option.count})`, option.value, false));
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
  };
}
