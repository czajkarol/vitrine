// One filter group: a collapsible list of tri-state rows, with a search box when it is
// long enough to need one.
//
// **Why one control per facet instead of two lists.** Until M13 each group was a list of
// radios for inclusion plus a collapsed second list of checkboxes for exclusion — the same
// sixty facets written out twice, in two places, meaning two different things. Excluding
// something meant finding it again in a different list further down the panel.
//
// A facet has three states with respect to a filter, so the control has three states. Click
// once to include, again to exclude, again to clear. The state is a glyph *and* a colour
// *and* an `aria-pressed`-style label, because one of those alone is a guess.
//
// Split out of `panel.js`, which was already the largest file here and would otherwise have
// grown a second job.

import { t } from './i18n.js';

// Above this many options a group gets a search box. Below it, scanning is faster than
// typing, and a search box over eight rows is furniture.
const SEARCHABLE_FROM = 12;

export const STATES = ['off', 'include', 'exclude'];

/** What clicking a row does: off → include → exclude → off. */
function nextState(state) {
  return STATES[(STATES.indexOf(state) + 1) % STATES.length];
}

/**
 * @param {object} elements
 * @param {HTMLElement} elements.root      the <details> for this group
 * @param {HTMLElement} elements.list      where the rows go
 * @param {HTMLElement} elements.count     the "3 selected" badge in the summary
 * @param {HTMLInputElement} elements.search
 * @param {object} handlers
 * @param {(field: string, value: string, state: string) => void} handlers.onChange
 */
export function createFilterGroup({ group, field, elements }, handlers) {
  const { root, list, count, search } = elements;

  // Every option the server offered, and what each is currently set to.
  let options = [];
  let states = new Map();
  let query = '';

  function matches(option, label) {
    if (!query) return true;
    const needle = query.toLowerCase();
    return label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle);
  }

  function render(labelFor) {
    list.textContent = '';
    let shown = 0;
    for (const option of options) {
      const label = labelFor(option);
      const state = states.get(option.value) ?? 'off';
      // A row the search has filtered out still counts as selected, and hiding it would
      // make a selection invisible rather than absent. So a selected row always shows.
      if (state === 'off' && !matches(option, label)) continue;
      shown += 1;
      list.appendChild(buildRow(option, label, state));
    }
    if (shown === 0) {
      const empty = document.createElement('p');
      empty.className = 'panel-summary';
      empty.textContent = t('filter_no_matches');
      list.appendChild(empty);
    }
    syncCount();
  }

  function buildRow(option, label, state) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'facet';
    button.dataset.state = state;
    button.dataset.value = option.value;
    // Zero under the current selection. Still clickable when it is *excluded* — otherwise
    // there would be no way to undo an exclusion that emptied its own group — but not
    // worth including, so an off row at zero is inert and dimmed. A list that reshuffles
    // under the cursor is worse than a greyed row.
    button.disabled = option.count === 0 && state === 'off';

    const mark = document.createElement('span');
    mark.className = 'facet-mark';
    mark.setAttribute('aria-hidden', 'true');
    // The glyph carries the state as well as the colour does, so it survives a stylesheet
    // that has not loaded and a viewer who does not see the colour.
    mark.textContent = { off: '', include: '✓', exclude: '✕' }[state];

    const text = document.createElement('span');
    text.className = 'facet-label';
    text.textContent = label;

    const number = document.createElement('span');
    number.className = 'facet-count';
    number.textContent = String(option.count);

    button.append(mark, text, number);
    // The state in words, for a screen reader, because the glyph is hidden from it and
    // "Painting, 2,614" alone does not say whether it is on.
    button.setAttribute(
      'aria-label',
      `${label}. ${t(`filter_state_${state}`)}. ${t('filter_state_hint')}`,
    );
    button.addEventListener('click', () => {
      const next = nextState(states.get(option.value) ?? 'off');
      states.set(option.value, next);
      handlers.onChange(field, option.value, next);
    });
    return button;
  }

  function syncCount() {
    if (!count) return;
    const included = [...states.values()].filter((state) => state === 'include').length;
    const excluded = [...states.values()].filter((state) => state === 'exclude').length;
    const parts = [];
    if (included) parts.push(t('filter_badge_included', { count: included }));
    if (excluded) parts.push(t('filter_badge_excluded', { count: excluded }));
    count.textContent = parts.join(' · ');
    count.hidden = parts.length === 0;
    // A group with something set opens itself, so a filter that is on is never hidden
    // behind a collapsed heading the user has to remember to check.
    if (parts.length > 0) root.open = true;
  }

  search?.addEventListener('input', () => {
    query = search.value.trim();
    handlers.onSearch?.();
  });

  return {
    group,
    field,

    /** Replace the offered options. Does not change what is selected. */
    setOptions(next, labelFor) {
      options = next ?? [];
      // The search box earns its place only on a long list.
      if (search) search.hidden = options.length < SEARCHABLE_FROM;
      root.hidden = options.length === 0;
      render(labelFor);
    },

    /** Reflect a selection that came from somewhere else — restored preferences, a reset. */
    setSelection({ include = [], exclude = [] }, labelFor) {
      states = new Map();
      for (const value of include) states.set(value, 'include');
      for (const value of exclude) states.set(value, 'exclude');
      render(labelFor);
    },

    /** Redraw, keeping the selection and the search text. */
    refresh(labelFor) {
      render(labelFor);
    },

    /** What this group contributes to the query. */
    selection() {
      const include = [];
      const exclude = [];
      for (const [value, state] of states) {
        if (state === 'include') include.push(value);
        else if (state === 'exclude') exclude.push(value);
      }
      return { include, exclude };
    },

    isEmpty() {
      return [...states.values()].every((state) => state === 'off');
    },

    clear() {
      states = new Map();
      if (search) search.value = '';
      query = '';
    },
  };
}
