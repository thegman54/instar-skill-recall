-- Fuzzy search for recall: trigram matching over content/reason/source.
--
-- Replaces the substring-only ILIKE behaviour of recall_read, which missed word variants
-- ("cruise" vs "cruises") and any typo at all. Trigram similarity handles both and gives a
-- score to rank by, so the best match surfaces first instead of the most recent.
--
-- This does NOT widen visibility. Scope predicates (owner / this speaker / this session) are
-- applied separately and unchanged in recall_read — fuzzy matching only filters *within* what
-- the caller could already see. Cross-speaker connections belong in owner scope, approved by
-- the owner, not in a wider search.
--
-- Idempotent. Degrades safely: if the role cannot CREATE EXTENSION, the migration logs a
-- notice and succeeds without the extension, and recall_read falls back to ILIKE at runtime.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'pg_trgm requires elevated privileges; skipping. recall_read will fall back to ILIKE.';
    WHEN undefined_file THEN
        RAISE NOTICE 'pg_trgm is not available on this server; skipping. recall_read will fall back to ILIKE.';
END
$$;

-- Trigram indexes, only if the extension actually landed above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS idx_recall_content_trgm
            ON recall_entries USING GIN (content gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_recall_reason_trgm
            ON recall_entries USING GIN (reason gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS idx_recall_source_trgm
            ON recall_entries USING GIN (source gin_trgm_ops);
    END IF;
END
$$;
