// The settings panel. M3 gives it mode and Explore filters; M4 adds language and AI.
//
// Opening it pauses rotation and closing resumes, per docs/product-spec.md — a panel you
// are reading should not have the picture change underneath it.

import { deleteAiKey, fetchAiKey, fetchFilters, saveAiKey } from './api.js';
import { t } from './i18n.js';
import { INTERVAL_SECONDS } from './rotation.js';

export function createPanel(elements, handlers) {
  const { panel, modeInputs, languageInputs, ambientInput, ambientGroup, intervalList,
    typeList, styleList, styleGroup, subjectList, subjectGroup, summary, aiProviderInputs,
    aiKeyInput, aiSaveButton, aiClearButton, aiStatusLine, aiStorageLine } = elements;

  // The three filter vocabularies, in the order the panel shows them. Each names the
  // radio group in the markup, the field it sets, where its options are rendered, and
  // which of the server's three lists it draws from.
  const FILTERS = [
    { group: 'artwork-type', field: 'artworkType', any: 'filter_any', source: 'artwork_types' },
    { group: 'style', field: 'style', any: 'filter_any_style', source: 'styles' },
    { group: 'subject', field: 'subject', any: 'filter_any_subject', source: 'subjects' },
  ];

  let open = false;
  let loaded = false;
  // The last answer from /api/ai/key: whether a provider is live, where its key is kept
  // and the last four characters of it. Never a key — the server has none to give.
  let keyStatus = null;
  // A transient line under the AI group: "Key saved", or why it was not. Kept as a key
  // rather than as text so a language change can say it again.
  let keyMessage = null;
  // The filter vocabulary as fetched. Kept so a language change can relabel the list
  // without asking the server for it again.
  let filters = null;
  // The panel's idea of the current settings, kept because the filter list is built
  // lazily on first open — long after preferences were restored at boot. Without this the
  // radio would read "Any type" while the rotation was actually filtered.
  let current = {
    mode: 'random',
    artworkType: null,
    style: null,
    subject: null,
    // Several at once, unlike the three above. See the Exclude sub-lists below.
    exclude: [],
    language: 'en',
    ambient: false,
    intervalSeconds: 300,
  };

  function applySelection() {
    for (const input of modeInputs) input.checked = input.value === current.mode;
    for (const input of languageInputs) input.checked = input.value === current.language;
    ambientInput.checked = current.ambient;
    for (const input of intervalList.querySelectorAll('input')) {
      input.checked = Number(input.value) === current.intervalSeconds;
    }
    for (const filter of FILTERS) {
      const inputs = [...panel.querySelectorAll(`input[name="${filter.group}"]`)];
      const target = inputs.find((input) => input.value === (current[filter.field] ?? ''));
      if (target) target.checked = true;
    }
  }

  /**
   * Fetch the vocabulary and draw it.
   *
   * Re-fetched whenever the selection changes, not cached after the first open: the
   * counts are dependent, so they are only true for the selection they were asked for.
   * It is one local query against an indexed table and the panel is already open.
   */
  async function loadFilters() {
    filters = await fetchFilters(currentSelection());
    loaded = true;
    renderFilters();
  }

  function currentSelection() {
    return {
      artworkType: current.artworkType,
      style: current.style,
      subject: current.subject,
      exclude: current.exclude,
    };
  }

  /** Tell the display, and redraw the counts under the new selection. */
  function announceFilterChange() {
    handlers.onFilterChange(currentSelection());
    void loadFilters();
  }

  /**
   * A facet's label: ours, not the museum's.
   *
   * Before M10 these were AIC's raw values and were deliberately left in English, because
   * they were data. A canonical facet label is interface text, so it comes from locales/
   * like everything else — falling back to the English the server sent, so a facet no
   * locale has caught up with reads as a word rather than as a slug.
   */
  function facetLabel(option) {
    const key = `facet_${option.value.replace(/\./g, '_')}`;
    return t(key, undefined, option.label ?? option.value);
  }

  /** How long a rung reads as: under a minute in seconds, otherwise in minutes. */
  function intervalLabel(seconds) {
    return seconds < 60
      ? t('interval_option_seconds', { seconds })
      : t('interval_option_minutes', { minutes: seconds / 60 });
  }

  /** The rotation menu, built from rotation.js so the list has one definition. */
  function renderIntervals() {
    intervalList.textContent = '';
    for (const seconds of INTERVAL_SECONDS) {
      const option = buildOption(intervalLabel(seconds), String(seconds), false, 'interval');
      option.querySelector('input').addEventListener('change', () => {
        current = { ...current, intervalSeconds: seconds };
        handlers.onIntervalChange(seconds);
      });
      intervalList.appendChild(option);
    }
  }

  /**
   * Build the three filter lists from `filters`. Idempotent, so a relabel is just another
   * call.
   *
   * Style and subject came with M3.5 and behave slightly differently from artwork type:
   * their vocabularies run to thousands of values, so the server sends only the most
   * populous few, and where the index has none of them the whole group is hidden rather
   * than shown empty.
   */
  function renderFilters() {
    if (!filters || filters.artwork_types.length === 0) {
      // No index yet, or nothing with enough behind it. Say so rather than showing an
      // empty box the user cannot interpret.
      typeList.textContent = '';
      styleGroup.hidden = true;
      subjectGroup.hidden = true;
      summary.textContent = filters?.indexed_total
        ? t('filters_too_thin', { minimum: filters.minimum_count })
        : t('filters_no_index');
      return;
    }

    summary.textContent = t('filters_summary', { total: filters.indexed_total });
    for (const filter of FILTERS) {
      const options = filters[filter.source] ?? [];
      renderFilterList(filter, options);
      renderExcludeList(filter, options);
    }
    styleGroup.hidden = (filters.styles ?? []).length === 0;
    subjectGroup.hidden = (filters.subjects ?? []).length === 0;
    // The lists were just rebuilt from scratch, and a fresh radio only knows the
    // `defaultChecked` it was built with — which is "Any". Without this the panel showed
    // "Any style" while the rotation was still filtered to Japanese, and clicking "Any"
    // to clear it fired no change event because it already looked checked. Seen in a
    // browser, and the state and the screen disagreed silently.
    applySelection();
  }

  /** One list of radios: an "any" entry, then the options the server thought worth it. */
  function renderFilterList(filter, options) {
    const list = listFor(filter.group);
    list.textContent = '';
    if (options.length === 0) return;
    // Each list says what it is letting through — "Any subject" under Subject, not the
    // artwork type's wording repeated three times.
    list.appendChild(buildOption(t(filter.any), '', true, filter.group));
    for (const option of options) {
      const label = t('filter_option', { value: facetLabel(option), count: option.count });
      const element = buildOption(label, option.value, false, filter.group);
      // Zero under the *current* selection. Disabled rather than removed: a list that
      // reshuffles under the cursor is worse than a greyed row, and the row is what says
      // the option exists but is empty right now.
      if (option.count === 0) disable(element);
      list.appendChild(element);
    }
  }

  /**
   * The "Exclude" sub-list under each group.
   *
   * Checkboxes, where inclusion is radios, and the difference is not an inconsistency.
   * `docs/product-spec.md`'s reasoning for radios is that "landscape AND portraits"
   * narrows to nothing — which is true of inclusion and simply not true of exclusion:
   * ruling several things out at once is ordinary and leaves plenty behind.
   *
   * Collapsed by default. Most of the time nobody wants it, and an ambient display's
   * settings panel should not open onto three lists of sixty checkboxes.
   */
  function renderExcludeList(filter, options) {
    const list = excludeListFor(filter.group);
    const group = excludeGroupFor(filter.group);
    if (!list || !group) return;
    list.textContent = '';
    group.hidden = options.length === 0;
    for (const option of options) {
      const wrapper = document.createElement('label');
      wrapper.className = 'panel-option';

      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = option.value;
      input.checked = current.exclude.includes(option.value);
      // Excluding what you have just asked for is contradictory rather than empty, and
      // the server would answer it with "nothing matches". Say so by not offering it.
      input.disabled = current[filter.field] === option.value;
      input.addEventListener('change', () => {
        const next = current.exclude.filter((facet) => facet !== option.value);
        if (input.checked) next.push(option.value);
        current = { ...current, exclude: next };
        announceFilterChange();
      });

      const text = document.createElement('span');
      text.textContent = facetLabel(option);

      wrapper.append(input, text);
      if (input.disabled) wrapper.classList.add('is-disabled');
      list.appendChild(wrapper);
    }
  }

  function listFor(group) {
    return { 'artwork-type': typeList, style: styleList, subject: subjectList }[group];
  }

  function excludeListFor(group) {
    return panel.querySelector(`[data-exclude-list="${group}"]`);
  }

  function excludeGroupFor(group) {
    return panel.querySelector(`[data-exclude-group="${group}"]`);
  }

  function disable(optionElement) {
    optionElement.classList.add('is-disabled');
    const input = optionElement.querySelector('input');
    if (input) input.disabled = true;
  }

  function buildOption(label, value, checked, group = 'artwork-type') {
    const wrapper = document.createElement('label');
    wrapper.className = 'panel-option';

    const input = document.createElement('input');
    input.type = 'radio';
    input.name = group;
    input.value = value;
    input.defaultChecked = checked;
    const filter = FILTERS.find((candidate) => candidate.group === group);
    if (filter) {
      input.addEventListener('change', () => {
        current = { ...current, [filter.field]: value || null };
        announceFilterChange();
      });
    }

    const text = document.createElement('span');
    text.textContent = label;

    wrapper.append(input, text);
    return wrapper;
  }

  /**
   * Say what the key situation is, in a settings panel that must never show a key.
   *
   * Three states, and they read differently on purpose. A key from `.env` is not the
   * user's to remove from here, so no button is offered for it. A key in the OS keyring
   * is fine. A key in the database is unencrypted, and `docs/ai-system.md` allows that
   * only on condition the UI says so — which is this line, shown before anything is typed
   * as well as after.
   */
  function renderAiKey() {
    if (!keyStatus) {
      aiStatusLine.textContent = t('ai_key_unknown');
      return;
    }

    if (keyMessage) {
      aiStatusLine.textContent = t(keyMessage);
    } else if (keyStatus.source === 'environment') {
      aiStatusLine.textContent = t('ai_key_environment', { provider: keyStatus.provider });
    } else if (keyStatus.enabled) {
      aiStatusLine.textContent = t('ai_key_active', {
        provider: keyStatus.provider,
        hint: keyStatus.key_hint,
      });
    } else {
      aiStatusLine.textContent = t('ai_key_none');
    }

    aiStorageLine.textContent =
      keyStatus.storage === 'keyring' ? t('ai_storage_keyring') : t('ai_storage_database');
    // Nothing to remove, and nothing this panel could remove: a key in .env is a file
    // the user edits themselves.
    aiClearButton.hidden = keyStatus.source === 'environment' || keyStatus.source === 'none';

    const target = [...aiProviderInputs].find((input) => input.value === keyStatus.provider);
    if (target) target.checked = true;
  }

  async function loadAiKey() {
    keyStatus = await fetchAiKey();
    renderAiKey();
  }

  function chosenProvider() {
    return [...aiProviderInputs].find((input) => input.checked)?.value ?? 'anthropic';
  }

  async function submitKey() {
    const apiKey = aiKeyInput.value.trim();
    if (!apiKey) return;
    aiSaveButton.disabled = true;
    try {
      keyStatus = await saveAiKey(chosenProvider(), apiKey);
      keyMessage = 'ai_key_saved';
      // Out of the field the moment it is stored. It is in the browser's memory for as
      // long as this node holds it, and there is no reason for that to be the rest of
      // the evening.
      aiKeyInput.value = '';
      handlers.onAiChange(keyStatus);
    } catch (error) {
      console.warn('Could not save the key.', error);
      // A key the shape check rejected and a keyring that refused are the user's two
      // fixable cases, and they are fixed differently. Everything else is one message.
      keyMessage = ['ai_key_invalid', 'key_store_unavailable'].includes(error?.code)
        ? error.code
        : 'ai_key_failed';
    } finally {
      aiSaveButton.disabled = false;
      renderAiKey();
    }
  }

  async function removeKey() {
    aiClearButton.disabled = true;
    try {
      keyStatus = await deleteAiKey();
      keyMessage = 'ai_key_removed';
      handlers.onAiChange(keyStatus);
    } catch (error) {
      console.warn('Could not remove the key.', error);
      keyMessage = 'ai_key_failed';
    } finally {
      aiClearButton.disabled = false;
      renderAiKey();
    }
  }

  aiSaveButton.addEventListener('click', () => void submitKey());
  aiClearButton.addEventListener('click', () => void removeKey());
  // Enter in the field is what anyone who has just pasted a key will press.
  aiKeyInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void submitKey();
    }
  });
  // A new keystroke means the old outcome is no longer what the user is looking at.
  aiKeyInput.addEventListener('input', () => {
    if (keyMessage) {
      keyMessage = null;
      renderAiKey();
    }
  });

  for (const input of modeInputs) {
    input.addEventListener('change', () => {
      current = { ...current, mode: input.value };
      handlers.onModeChange(current.mode);
    });
  }

  for (const input of languageInputs) {
    input.addEventListener('change', () => {
      current = { ...current, language: input.value };
      handlers.onLanguageChange(current.language);
    });
  }

  renderIntervals();

  ambientInput.addEventListener('change', () => {
    current = { ...current, ambient: ambientInput.checked };
    handlers.onAmbientChange(current.ambient);
  });

  /** Offer ambient mode only where the browser can actually do it. */
  function hideAmbient() {
    ambientGroup.remove();
  }

  return {
    async show() {
      open = true;
      panel.classList.add('visible');
      panel.removeAttribute('inert');
      await loadFilters();
      // Read fresh on every open rather than cached: the key can have been changed from
      // another tab, or the provider taken away by a restart.
      keyMessage = null;
      await loadAiKey();
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

    hideAmbient,

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
      renderIntervals();
      if (loaded) renderFilters();
      renderAiKey();
      applySelection();
    },
  };
}
