// The settings panel. Mode, source, filters, rotation, ambient, AI, language and help.
//
// Opening it pauses rotation and closing resumes, per docs/product-spec.md — a panel you
// are reading should not have the picture change underneath it.
//
// The filter half moved to `filters.js` in M13. What is left here is orchestration: which
// groups exist, what the current selection is, and telling the display when it changed.

import {
  deleteAiKey,
  deletePreset,
  fetchAiKey,
  fetchFeedbackSummary,
  fetchFilters,
  fetchPresets,
  fetchScoring,
  saveAiKey,
  savePreset,
} from './api.js';
import { createFilterGroup } from './filters.js';
import { t } from './i18n.js';
import { INTERVAL_SECONDS } from './rotation.js';

export function createPanel(elements, handlers) {
  const { panel, modeInputs, museumInputs, languageInputs, ambientInput, ambientGroup,
    intervalList, filterGroups, summary, stateHint, resetButton, aiProviderInputs,
    aiKeyInput, aiSaveButton, aiClearButton, aiStatusLine, aiStorageLine,
    modeGroup, presetList, presetEmpty, presetNameInput,
    presetSaveButton } = elements;
  // Named apart from the `presetNote` state below on purpose: one is the element, the
  // other is what it should say.
  const presetNoteLine = elements.presetNote;

  // Queried from the panel rather than passed in from main.js, the way the scoring list and
  // the "For you" hint already are: these are the panel's own furniture, and main.js has no
  // reason to know the settings are laid out in tabs at all.
  const tabs = [...panel.querySelectorAll('[role="tab"]')];
  const tabPanels = [...panel.querySelectorAll('[role="tabpanel"]')];
  const aiExplain = panel.querySelector('#panel-ai-explain');
  const modeHint = panel.querySelector('#panel-mode-hint');
  const modeExplain = panel.querySelector('#panel-mode-explain');
  const aiStorageSummary = panel.querySelector('#panel-ai-storage-summary');

  let open = false;
  let loaded = false;
  // Which of the three tabs is showing. Session-lived, not persisted — see `selectTab`.
  let activeTab = tabs[0]?.dataset.tab ?? 'display';
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
  // Every /api/filters request this panel makes, numbered. A selection can change faster
  // than the server answers, and the answers do not come back in the order they were
  // asked for — an exclusion costs a NOT over the whole facet table and is reliably the
  // slower query, so the request that says "excluded" can land *after* the one that says
  // "cleared". Drawing that stale answer put a count of zero on a row whose state had
  // just gone back to off, and `buildRow` disables exactly that pair: the row went inert
  // and there was no way to click the facet back on. A response that is not the newest
  // is dropped rather than drawn.
  let filterRequest = 0;
  // Saved filter combinations, as the server last listed them. Read on every open rather
  // than cached for the life of the page: they are small, and a stale list is a button
  // that applies something that is no longer there.
  let presets = [];
  // A key for a line under the preset list — what was saved, what could not be, or which
  // of an applied preset's facets the index no longer offers. Kept as a key with its
  // substitutions rather than as text, so a language change can say it again.
  let presetNote = null;
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
        prefix: element.prefix,
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

  /**
   * Whether the current source is the indexed corpus.
   *
   * Three things hang off this and they used to spell it out separately: the modes that
   * rank against a score, the sentence under the filters, and — since the Cleveland
   * exclusion bug — whether a facet control has a third state at all. ADR-0013.
   */
  function isIndexed() {
    return current.museum === 'aic';
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
    renderModeExplain();
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
          // belong to it, matched on the facet namespace rather than on the group's own
          // name. Those are not the same string — the artwork-type group's facets are
          // `type.*` — and matching on the wrong one silently dropped every exclusion in
          // that group, so a facet clicked to "exclude" snapped back to "off" on the next
          // redraw. Found by the Playwright flow written for exactly this control.
          exclude: current.exclude.filter((facet) => facet.startsWith(`${group.prefix}.`)),
        },
        facetLabel,
      );
    }
    syncResetButton();
    syncPresetName();
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
    const ticket = ++filterRequest;
    const next = await fetchFilters(currentSelection());
    // Someone clicked again while this was in flight. Its counts describe a selection
    // that is no longer the one on screen, and the newer request will draw the right ones.
    if (ticket !== filterRequest) return;
    filters = next;
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
  /**
   * The five intervals, as one row rather than five stacked rows.
   *
   * They are the shortest labels in the panel — "30 sec", "5 min" — and each was taking a
   * full line with a radio dot beside it, which is a sixth of the panel's height spent on
   * a scale of five values. Laid out as a segmented row they read as the scale they are.
   * Still radios underneath: the input is hidden from view, not removed, so the group keeps
   * its keyboard behaviour and a screen reader still hears five options with one chosen.
   */
  function renderIntervals() {
    intervalList.textContent = '';
    for (const seconds of INTERVAL_SECONDS) {
      const option = buildRadio(intervalLabel(seconds), String(seconds), 'interval');
      option.classList.add('panel-segment');
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

    // How many states a control has follows from the source, not from whether its
    // vocabulary arrived — so it is settled before anything can return early. Exclusion
    // is a NOT over the canonical facet layer and only the indexed corpus has one
    // (ADR-0009, ADR-0013); a live source gets two states, and the sentence above the
    // groups says which cycle is running.
    for (const group of groups) group.setExcludable(isIndexed());
    if (stateHint) stateHint.textContent = t(groups[0]?.hintKey() ?? 'filter_state_hint');

    if (!filters || !anyOffered) {
      for (const group of groups) group.setOptions([], facetLabel);
      summary.textContent = filters?.indexed_total
        ? t('filters_too_thin', { minimum: filters.minimum_count })
        : t('filters_no_index');
      return;
    }

    summary.textContent = isIndexed()
      ? t('filters_summary', { total: filters.indexed_total })
      : t('filters_summary_live', { total: filters.indexed_total });
    for (const group of groups) group.setOptions(source[group.group] ?? [], facetLabel);
    // The lists were just rebuilt from scratch and know nothing about what is selected.
    applySelection();
  }

  // --- Saved filter combinations -----------------------------------------------------
  //
  // A preset is a museum plus the three inclusion lists plus the exclusion list — exactly
  // `currentSelection()`, under a name. Not a mode and not an interval: those are how the
  // display behaves rather than what it is showing.

  /**
   * What to call a selection nobody has named yet.
   *
   * Prefilled rather than left blank so that saving is one action for somebody who does
   * not want to invent a name, and it is a plain overwritable suggestion rather than a
   * generated identity: the field is a text input and whatever is in it is what gets
   * saved. Three labels is where a name stops being a name and starts being the filter
   * written out again.
   */
  function suggestedName() {
    const chosen = [];
    for (const group of groups) {
      const { include } = group.selection();
      for (const value of include) chosen.push(facetLabel(offeredOption(value)));
    }
    if (chosen.length === 0) return '';
    const head = chosen.slice(0, 3).join(', ');
    return chosen.length > 3 ? t('presets_name_more', { names: head, count: chosen.length - 3 })
      : head;
  }

  /**
   * The option the server sent for a facet key, or a bare stand-in for one it did not.
   *
   * `facetLabel` needs the whole option, not the key: English has no `facet_*` strings at
   * all and falls through to the label the server derived from the raw vocabulary. Handed
   * only a key it falls through to the key, and a name suggested as "type.print,
   * style.japanese" is a slug, not a name.
   */
  function offeredOption(value) {
    for (const list of [filters?.artwork_types, filters?.styles, filters?.subjects]) {
      const found = (list ?? []).find((option) => option.value === value);
      if (found) return found;
    }
    return { value };
  }

  /** Every facet in a preset, flat, for asking what the index still offers. */
  function presetFacets(preset) {
    return [
      ...(preset.artwork_type ?? []),
      ...(preset.style ?? []),
      ...(preset.subject ?? []),
      ...(preset.exclude ?? []),
    ];
  }

  /**
   * Which of a preset's facets the current vocabulary no longer offers.
   *
   * Nothing drops them — not the repository, not the route, not this. Dropping an
   * inclusion would quietly *widen* what the preset means, turning "Japanese prints" into
   * "prints", and that is the one failure the whole Explore path is written to avoid. So
   * they are applied as saved and counted here, and the panel says how many, because a
   * preset that has silently stopped meaning what its name says is worse than one that
   * says it has.
   */
  function staleFacets(preset) {
    if (!filters) return [];
    const offered = new Set(
      [
        ...(filters.artwork_types ?? []),
        ...(filters.styles ?? []),
        ...(filters.subjects ?? []),
      ].map((option) => option.value),
    );
    return presetFacets(preset).filter((facet) => !offered.has(facet));
  }

  function renderPresets() {
    if (!presetList) return;
    presetList.textContent = '';
    if (presetEmpty) presetEmpty.hidden = presets.length > 0;
    for (const preset of presets) {
      const row = document.createElement('div');
      row.className = 'preset';

      const apply = document.createElement('button');
      apply.type = 'button';
      apply.className = 'preset-apply';
      apply.textContent = preset.name;
      apply.dataset.presetId = String(preset.id);
      // The count of filters is what tells two similarly named presets apart, and it is
      // the only thing about a preset that is not its name.
      const count = presetFacets(preset).length;
      apply.setAttribute('aria-label', t('presets_apply_label', { name: preset.name, count }));
      apply.addEventListener('click', () => void applyPreset(preset));

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'preset-remove';
      remove.textContent = '\u00d7';
      remove.setAttribute('aria-label', t('presets_remove_label', { name: preset.name }));
      remove.addEventListener('click', () => void removePreset(preset));

      row.append(apply, remove);
      presetList.appendChild(row);
    }
    renderPresetNote();
  }

  function renderPresetNote() {
    if (!presetNoteLine) return;
    presetNoteLine.hidden = presetNote === null;
    if (presetNote) presetNoteLine.textContent = t(presetNote.key, presetNote.values);
  }

  function say(key, values) {
    presetNote = key === null ? null : { key, values };
    renderPresetNote();
  }

  /**
   * Put a saved selection back on screen.
   *
   * Routed through `onMuseumChange` when the source differs and `onFilterChange` when it
   * does not, rather than through a handler of its own: switching source also clears the
   * back stack, because the two museums have two id spaces and a stack that crossed them
   * would offer to return to an artwork the current source cannot show. The panel's own
   * museum radio clears the filters on the way; this does not go through that radio,
   * which is the whole reason a preset can carry a museum at all.
   */
  async function applyPreset(preset) {
    const changedMuseum = preset.museum !== current.museum;
    current = {
      ...current,
      museum: preset.museum,
      artworkType: [...(preset.artwork_type ?? [])],
      style: [...(preset.style ?? [])],
      subject: [...(preset.subject ?? [])],
      exclude: [...(preset.exclude ?? [])],
    };
    if (changedMuseum) handlers.onMuseumChange(current.museum, currentSelection());
    else handlers.onFilterChange(currentSelection());
    syncModes();
    await loadFilters();
    const stale = staleFacets(preset);
    say(stale.length ? 'presets_applied_stale' : 'presets_applied', {
      name: preset.name,
      count: stale.length,
    });
  }

  async function storePreset() {
    const name = presetNameInput?.value.trim() || suggestedName();
    if (!name) {
      say('presets_needs_name');
      return;
    }
    presetSaveButton.disabled = true;
    try {
      await savePreset(name, currentSelection());
      presets = await fetchPresets();
      if (presetNameInput) presetNameInput.value = '';
      renderPresets();
      say('presets_saved', { name });
    } catch (error) {
      console.warn('Could not save the preset.', error);
      say(error?.code === 'preset_limit_reached' ? 'presets_limit' : 'presets_failed');
    } finally {
      presetSaveButton.disabled = false;
    }
  }

  async function removePreset(preset) {
    try {
      await deletePreset(preset.id);
      presets = await fetchPresets();
      renderPresets();
      say('presets_removed', { name: preset.name });
    } catch (error) {
      console.warn('Could not remove the preset.', error);
      say('presets_failed');
    }
  }

  async function loadPresets() {
    presets = await fetchPresets();
    renderPresets();
  }

  /**
   * Keep the suggested name in step with what is actually selected.
   *
   * A placeholder rather than a value, so it never has to be cleared and never overwrites
   * a name somebody is halfway through typing. Recomputed on every selection change
   * rather than only when the panel opens: after applying a preset and adjusting it, the
   * suggestion for "save this as well" should describe what is on screen now.
   */
  function syncPresetName() {
    if (!presetNameInput) return;
    presetNameInput.placeholder = suggestedName() || t('presets_name_placeholder');
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

    // Where the key is kept, twice: the one-line version in the summary, which is on screen
    // whether or not anybody opens the disclosure, and the paragraph inside it. The short
    // line is what `docs/ai-system.md` requires the UI to say — that the key is unencrypted
    // where there is no password store — and the long one is why and what to do about it.
    const keyring = keyStatus.storage === 'keyring';
    aiStorageLine.textContent = t(keyring ? 'ai_storage_keyring' : 'ai_storage_database');
    if (aiStorageSummary) {
      aiStorageSummary.textContent = t(
        keyring ? 'ai_storage_keyring_short' : 'ai_storage_database_short',
      );
    }
    aiExplain?.classList.toggle('is-warning', !keyring);
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
      // The line under the row and what the triangle holds both follow the selection.
      renderModeExplain();
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

  presetSaveButton?.addEventListener('click', () => void storePreset());
  // Enter in the name field is what anyone who has just typed a name will press.
  presetNameInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void storePreset();
    }
  });

  ambientInput.addEventListener('change', () => {
    current = { ...current, ambient: ambientInput.checked };
    handlers.onAmbientChange(current.ambient);
  });

  /** Offer ambient mode only where the browser can actually do it. */
  function hideAmbient() {
    ambientGroup.remove();
  }

  /**
   * Show one tab's panel and hide the others.
   *
   * `hidden` rather than a class, so the controls in a tab nobody is looking at are out of
   * the tab order and off screen readers for free — the same reasoning as the `inert` on the
   * closed panel itself.
   *
   * Which tab is showing is remembered for the life of the page but not persisted. Coming
   * back to the tab you were last in is worth having inside a session; a *saved* tab means
   * the panel opens on the API key months later because that is where you once were.
   */
  function selectTab(name) {
    activeTab = name;
    for (const tab of tabs) {
      tab.setAttribute('aria-selected', String(tab.dataset.tab === name));
    }
    for (const tabPanel of tabPanels) {
      tabPanel.hidden = tabPanel.dataset.tab !== name;
    }
    // A tab is a different page of the panel, so it starts at the top of itself rather than
    // wherever the last one had been scrolled to.
    panel.scrollTop = 0;
  }

  for (const tab of tabs) {
    tab.addEventListener('click', () => selectTab(tab.dataset.tab));
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

  /**
   * What the selected mode does, in one line, and what is behind the triangle under it.
   *
   * The three modes were three stacked radios each carrying its own hint, plus a separate
   * disclosure for Curated — five lines and a triangle to offer three choices. One line and
   * one triangle now, both following the selection, so the panel explains the mode you are
   * in rather than all of them at once.
   *
   * "For you" says whether it is personalising *yet*, because below the threshold it is
   * not: a mode that quietly serves Curated picks while calling itself personal is the kind
   * of small lie that makes a panel untrustworthy.
   */
  function renderModeExplain() {
    if (modeHint) modeHint.textContent = modeHintText();
    const curated = document.getElementById('panel-explain-curated');
    const personal = document.getElementById('panel-explain-personal');
    if (curated) curated.hidden = current.mode !== 'curated';
    if (personal) personal.hidden = current.mode !== 'personal';
    // Random has nothing to open, so the triangle is not offered at all rather than
    // opening onto an empty box.
    if (modeExplain) {
      modeExplain.hidden = current.mode === 'random';
      if (modeExplain.hidden) modeExplain.open = false;
    }
  }

  function modeHintText() {
    if (current.mode === 'random') return t('mode_random_hint');
    if (current.mode === 'curated') return t('mode_curated_hint');
    if (!feedbackSummary) return t('mode_personal_hint');
    return feedbackSummary.personalising
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
    const indexed = isIndexed();
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
      // Also what draws the tabs for the first time: the markup ships with the first one
      // selected, and this is what makes the DOM agree with `activeTab` on every open after.
      selectTab(activeTab);
      // Read fresh on every open: someone may have liked several artworks since it was
      // last read, and "For you" saying it needs three more when it needs none is the kind
      // of small lie that makes a panel untrustworthy.
      // Built on first open rather than at construction: the panel is constructed before
      // boot() has loaded a locale, and drawing the interval menu then meant five
      // "missing translation" warnings for strings that were about to arrive.
      renderIntervals();
      feedbackSummary = await fetchFeedbackSummary();
      renderModeExplain();
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
      // Read on every open: another tab may have saved one, and a list of buttons that
      // apply things that are no longer there is worse than no list.
      say(null);
      await loadPresets();
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
      // The keyboard map sits below the tabs and needs none of this, but a section that
      // does live in one has to have its tab brought up first or it is `hidden` and
      // scrolling to it does nothing.
      const owner = section.closest('[role="tabpanel"]');
      if (owner) selectTab(owner.dataset.tab);
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
      renderModeExplain();
      if (loaded) renderFilters();
      else for (const group of groups) group.refresh(facetLabel);
      renderAiKey();
      renderPresets();
      applySelection();
    },
  };
}
