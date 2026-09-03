-- `classification` held AIC's `artwork_type_title` ("Painting"). AIC also has a real
-- `classification_title` field which means something else entirely — on a Seurat it reads
-- "oil on canvas". Keeping our column under the colliding name invited someone to reach
-- for the wrong one. See the vocabulary table in docs/aic-api.md.

ALTER TABLE artwork_index RENAME COLUMN classification TO artwork_type;

DROP INDEX IF EXISTS idx_artwork_index_classification;
CREATE INDEX IF NOT EXISTS idx_artwork_index_artwork_type ON artwork_index (artwork_type);
