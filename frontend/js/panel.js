// The settings panel. Mode, source, filters, rotation, ambient, AI, language and help.
//
// Opening it pauses rotation and closing resumes, per docs/product-spec.md — a panel you
// are reading should not have the picture change underneath it.
//
// The filter half moved to `filters.js` in M13. What is left here is orchestration: which
// groups exist, what the current selection is, and telling the display when it changed.

import {
  deleteAiKey,
  fetchAiKey,
  fetchFeedbackSummary,
  fetchFilters,
  fetchScoring,
  saveAiKey,
} from './api.js';
import { createFilterGroup } from './filters.js';
import { t } from './i18n.js';
import { INTERVAL_SECONDS } from './rotation.js';

export function createPanel(elements, handlers) {
  const { panel, modeInputs, museumInputs, languageInputs, ambientInput, ambientGroup,
    intervalList, filterGroups, summary, resetButton, aiProviderInputs, aiKeyInput,
    aiSaveButton, aiClearButton, aiStatusLine, aiStorageLine, modeGroup } = elements;

  let open = false;
  let loaded = false;
  // The last answer from /api/ai/key: whether a provider is live, where its key is kept
  // and the last four characters of it. Never a key — the server has none to give.
  let keyStatus = null;
  // A transient line under the AI group: "Key saved", or why it was not. Kept as a key
  // rather than as text so a language change can say it again.
  let keyMessage = null;
  // The curated weights, read once from /api/scoring. They cannot change while the app
  // is running — they are constants in the code the server is running.
  let scoring = null;
  // How many likes there are, so "For you" can say whether it is personalising yet.
  let feedbackSummary = null;
  // The filter vocabulary as fetched. Kept so a language change can relabel the list
  // without asking the server for it again.
  let filters = null;
  // The panel's idea of the current settings, kept because the filter list is built lazily
  // on first open — long after preferences were restored at boot. Without this the panel
  // showed nothing selected while the rotation was actually filtered.
  let current = {
    mode: 'random',
    museum: 'aic',
    artworkType: [],
    style: [],
    subject: [],
    exclude: [],
    language: 'en',
    ambient: false,
    intervalSeconds: 300,
  };

  // One per group, in the order the panel shows them. `field` names the array in `current`
  // that this group's inclusions go into; exclusions from every group share one list,
  // because the server NOTs them all at once.
  const groups = filterGroups.map((element) =>
    createFilterGroup(
      {
        group: element.group,
        field: element.field,
        elements: element,
      },
      {
        onChange: onFacetChange,
        // Re-render this group only. A search is a view of what is already loaded and must
        // not cost a request.
        onSearch: () => renderFilters(),
      },
    ),
  );

  /**
   * A facet moved between off, include and exclude.
   *
   * The whole selection is rebuilt from the groups rather than patched, because a facet can
   * move from `include` to `exclude` in one click and patching would have to remember to
   * remove it from the first list — the sort of thing that works until it does not.
   */
  function onFacetChange() {
    const exclude = [];
    for (const group of groups) {
      const { include, exclude: excluded } = group.selection();
      current[group.field] = include;
      exclude.push(...excluded);
    }
    current.exclude = exclude;
    handlers.onFilterChange(currentSelection());
    void loadFilters();
  }

  function currentSelection() {
    return {
      museum: current.museum,
      artworkType: current.artworkType,
      style: current.style,
      subject: current.subject,
      exclude: current.exclude,
    };
  }

  function applySelection() {
    for (const input of modeInputs) input.checked = input.value === current.mode;
    for (const input of museumInputs) input.checked = input.value === current.museum;
    for (const input of languageInputs) input.checked = input.value === current.language;
    ambientInput.checked = current.ambient;
    for (const input of intervalList.querySelectorAll('input')) {
      input.checked = Number(input.value) === current.intervalSeconds;
    }
    for (const group of groups) {
      group.setSelection(
        {
          include: current[group.field] ?? [],
          // Every group is handed the whole exclusion list and keeps the entries that
          // belong to it. A facet key starts with its group, so this is exact.
          exclude: current.exclude.filter((facet) => facet.startsWith(`${group.group}.`)),
        },
        facetLabel,
      );
    }
    syncResetButton();
  }

  /**
   * Fetch the vocabulary and draw it.
   *
   * Re-fetched whenever the selection changes, not cached after the first open: the counts
   * are dependent, so they are only true for the selection they were asked for. It is one
   * local query against an indexed table and the panel is already open. A live source
   * answers this from its own cache — see `providers/cma/client.py`.
   */
  async function loadFilters() {
    filters = await fetchFilters(currentSelection());
    loaded = true;
    renderFilters();
  }

  /**
   * A facet's label: ours, not the museum's.
   *
   * Before M10 these were AIC's raw values and were deliberately left in English, because
   * they were data. A canonical facet label is interface text, so it comes from locales/
   * like everything else — falling back to the English the server sent, so a facet no
   * locale has caught up with reads as a word rather than as a slug. A live source's own
   * vocabulary has no facet keys at all and always falls through to its label.
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
      const option = buildRadio(intervalLabel(seconds), String(seconds), 'interval');
      option.querySelector('input').addEventListener('change', () => {
        current = { ...current, intervalSeconds: seconds };
        handlers.onIntervalChange(seconds);
      });
      intervalList.appendChild(option);
    }
  }

  function buildRadio(label, value, name) {
    const wrapper = document.createElement('label');
    wrapper.className = 'panel-option';
    const input = document.createElement('input');
    input.type = 'radio';
    input.name = name;
    input.value = value;
    const text = document.createElement('span');
    text.textContent = label;
    wrapper.append(input, text);
    return wrapper;
  }

  /**
   * Draw the filter groups from `filters`. Idempotent, so a relabel is just another call.
   *
   * A live source offers one group and no style, subject or exclusion at all — it has no
   * index behind it and therefore no facet layer (ADR-0013). The groups it does not offer
   * are hidden rather than shown empty, which is the same rule M3.5 already applied to a
   * vocabulary too thin to sustain a rotation.
   */
  function renderFilters() {
    const source = {
      'artwork-type': filters?.artwork_types,
      style: filters?.styles,
      subject: filters?.subjects,
    };
    const anyOffered = Object.values(source).some((options) => (options ?? []).length > 0);

    if (!filters || !anyOffered) {
      for (const group of groups) group.setOptions([], facetLabel);
      summary.textContent = filters?.indexed_total
        ? t('filters_too_thin', { minimum: filters.minimum_count })
        : t('filters_no_index');
      return;
    }

    summary.textContent =
      current.museum === 'aic'
        ? t('filters_summary', { total: filters.indexed_total })
        : t('filters_summary_live', { total: filters.indexed_total });
    for (const group of groups) group.setOptions(source[group.group] ?? [], facetLabel);
    // The lists were just rebuilt from scratch and know nothing about what is selected.
    applySelection();
  }

  function syncResetButton() {
    if (!resetButton) return;
    resetButton.hidden = groups.every((group) => group.isEmpty());
  }

  function clearFilters() {
    for (const group of groups) group.clear();
    current = { ...current, artworkType: [], style: [], subject: [], exclude: [] };
    handlers.onFilterChange(currentSelection());
    void loadFilters();
  }

  /**
   * Say what the key situation is, in a settings panel that must never show a key.
   *
   * Three states, and they read differently on purpose. A key from `.env` is not the user's
   * to remove from here, so no button is offered for it. A key in the OS keyring is fine. A
   * key in the database is unencrypted, and `docs/ai-system.md` allows that only on
   * condition the UI says so — which is this line, shown before anything is typed as well
   * as after.
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
    // Nothing to remove, and nothing this panel could remove: a key in .env is a file the
    // user edits themselves.
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
      // long as this node holds it, and there is no reason for that to be the rest of the
      // evening.
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

  /**
   * Switching museum clears the filters as well as the source.
   *
   * The two vocabularies have nothing in common — one is canonical facet keys over an
   * index, the other is Cleveland's own artwork types — so carrying a selection across
   * would leave the panel showing a filter that silently matches nothing. Clearing it is
   * the honest answer, and the display says so.
   */
  for (const input of museumInputs) {
    input.addEventListener('change', () => {
      if (!input.checked) return;
      for (const group of groups) group.clear();
      current = {
        ...current,
        museum: input.value,
        artworkType: [],
        style: [],
        subject: [],
        exclude: [],
      };
      handlers.onMuseumChange(current.museum, currentSelection());
      // Curated and "For you" rank against a score only the index carries, so switching to
      // a live source has to take them away — and put the mode back to Random if one of
      // them was selected. Without this the panel kept showing Curated while the display
      // was serving plain random picks, which is the same silent lie the "For you" cold
      // start message exists to prevent. Seen in a browser.
      syncModes();
      void loadFilters();
    });
  }

  for (const input of languageInputs) {
    input.addEventListener('change', () => {
      current = { ...current, language: input.value };
      handlers.onLanguageChange(current.language);
    });
  }

  resetButton?.addEventListener('click', clearFilters);

  ambientInput.addEventListener('change', () => {
    current = { ...current, ambient: ambientInput.checked };
    handlers.onAmbientChange(current.ambient);
  });

  /** Offer ambient mode only where the browser can actually do it. */
  function hideAmbient() {
    ambientGroup.remove();
  }

  /**
   * The curated weights, as a share of the total.
   *
   * The wording of each signal is a translated string; only the numbers come from the
   * server. That is the whole point of `/api/scoring` — retuning a weight in the code
   * changes what this says, instead of quietly making it wrong.
   */
  function renderScoring() {
    const list = elements.scoringList ?? document.getElementById('panel-scoring');
    if (!list) return;
    list.textContent = '';
    for (const entry of scoring?.weights ?? []) {
      const item = document.createElement('li');
      const name = document.createElement('span');
      // Falls back to the server's own name, so a signal added to WEIGHTS shows up as
      // something readable before anyone writes a translation for it.
      name.textContent = t(`scoring_${entry.name}`, undefined, entry.name);
      const share = document.createElement('span');
      share.className = 'weight-share';
      share.textContent = t('scoring_share', { percent: Math.round(entry.share * 100) });
      item.append(name, share);
      list.appendChild(item);
    }
  }

  /** "For you" says what it is doing, because below the threshold it is not doing it. */
  function renderPersonalHint() {
    const hint = document.getElementById('panel-personal-hint');
    if (!hint || !feedbackSummary) return;
    hint.textContent = feedbackSummary.personalising
      ? t('mode_personal_hint_active', { likes: feedbackSummary.likes })
      : t('mode_personal_hint_cold', {
          likes: feedbackSummary.likes,
          minimum: feedbackSummary.minimum_likes,
        });
  }

  /**
   * Curated and "For you" rank against a score the index carries, and a live source has no
   * index. Offering them anyway would be offering a mode that silently is not one.
   */
  function syncModes() {
    const indexed = current.museum === 'aic';
    for (const input of modeInputs) {
      if (input.value === 'random') continue;
      input.disabled = !indexed;
      input.closest('.panel-option')?.classList.toggle('is-disabled', !indexed);
    }
    modeGroup?.querySelector('.panel-mode-note')?.toggleAttribute('hidden', indexed);
    if (!indexed && current.mode !== 'random') {
      current = { ...current, mode: 'random' };
      handlers.onModeChange('random');
      applySelection();
    }
  }

  return {
    async show() {
      open = true;
      panel.classList.add('visible');
      panel.removeAttribute('inert');
      // Read fresh on every open: someone may have liked several artworks since it was
      // last read, and "For you" saying it needs three more when it needs none is the kind
      // of small lie that makes a panel untrustworthy.
      // Built on first open rather than at construction: the panel is constructed before
      // boot() has loaded a locale, and drawing the interval menu then meant five
      // "missing translation" warnings for strings that were about to arrive.
      renderIntervals();
      feedbackSummary = await fetchFeedbackSummary();
      renderPersonalHint();
      if (scoring === null) {
        scoring = await fetchScoring();
        renderScoring();
      }
      syncModes();
      await loadFilters();
      // Read fresh on every open rather than cached: the key can have been changed from
      // another tab, or the provider taken away by a restart.
      keyMessage = null;
      await loadAiKey();
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

    /** Open the panel with one section expanded — used by the `?` shortcut for help. */
    async showSection(id) {
      if (!open) await this.show();
      const section = document.getElementById(id);
      if (!(section instanceof HTMLDetailsElement)) return;
      section.open = true;
      section.scrollIntoView({ block: 'nearest' });
      section.querySelector('summary')?.focus();
    },

    /** Reflect restored preferences without firing change handlers. */
    sync(next) {
      current = { ...current, ...next };
      applySelection();
      syncModes();
    },

    /**
     * Relabel everything this module built itself. The markup's own labels are handled by
     * i18n.applyTo(); this covers the lists built from /api/filters.
     */
    retranslate() {
      if (open) renderIntervals();
      renderScoring();
      renderPersonalHint();
      if (loaded) renderFilters();
      else for (const group of groups) group.refresh(facetLabel);
      renderAiKey();
      applySelection();
    },
  };
}
