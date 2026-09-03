-- The canonical facet layer. M10, and ADR-0009.
--
-- One table for all three filter groups, artwork type included as `type.*`. That is the
-- point of it. Until now, filtering on artwork type meant a WHERE on a column of
-- artwork_index while filtering on style or subject meant a subquery against
-- artwork_terms — two query shapes for one question, and the exclusion and dependent-count
-- work in this milestone would have had to be written twice and kept in step.
--
-- With everything here, "artworks matching this facet" is one shape:
--
--     id IN (SELECT artwork_id FROM artwork_facets WHERE facet = ?)
--
-- and so is its negation, and so is "how many artworks per facet", constrained or not.
--
-- The primary key deduplicates for free, which is not incidental: the whole purpose of the
-- facet layer is that several raw values collapse into one facet, and an artwork tagged
-- both `portrait` and `portraits` must count once, not twice.
--
-- Derived, and rebuildable. artwork_index.artwork_type and artwork_terms keep AIC's own
-- values forever; this table is rewritten wholesale by `build_index.py --retag`, which
-- needs no network. Editing app/domain/vocabulary.py and re-running --retag is the entire
-- procedure for changing the vocabulary.
--
-- WITHOUT ROWID for the same reason as artwork_terms: the primary key is the whole row.

CREATE TABLE IF NOT EXISTS artwork_facets (
    artwork_id INTEGER NOT NULL REFERENCES artwork_index(id) ON DELETE CASCADE,
    facet      TEXT    NOT NULL,
    PRIMARY KEY (artwork_id, facet)
) WITHOUT ROWID;

-- Counting artworks per facet, which the settings panel asks for every value in every
-- group each time it opens. Without this it is a full scan of the table per open.
CREATE INDEX IF NOT EXISTS idx_artwork_facets_facet ON artwork_facets (facet);

-- And the saved filters, which no longer mean anything.
--
-- Until now `artwork_type`, `style` and `subject` held AIC's own values — `Print`,
-- `Japanese (culture or style)`. They now hold facet keys, and an old value matches no
-- facet, so a display that has been running with a filter set would come back to a blank
-- "nothing matches those filters" and no obvious way to understand why.
--
-- Cleared rather than translated: mapping them forward is possible for most values and
-- wrong for the ones that merged, and starting from "no filter" is a state the user can
-- see and fix in one click. The same reasoning as migration 003.
DELETE FROM preferences WHERE key IN ('artwork_type', 'style', 'subject');
