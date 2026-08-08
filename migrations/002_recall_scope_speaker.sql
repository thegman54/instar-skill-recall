-- Scope axis for recall: memories can now belong to the owner (global), a specific speaker
-- (per-person flavor, keyed on the authenticated session's speaker), or a single session
-- (ephemeral notes that die with the conversation). Backwards compatible: existing rows are
-- owner-scoped. Idempotent.

ALTER TABLE recall_entries ADD COLUMN IF NOT EXISTS scope            TEXT NOT NULL DEFAULT 'owner';  -- owner | speaker | session
ALTER TABLE recall_entries ADD COLUMN IF NOT EXISTS speaker_id       TEXT;   -- authenticated speaker key, e.g. 'slack:U123' (server-resolved, never bot-supplied)
ALTER TABLE recall_entries ADD COLUMN IF NOT EXISTS speaker_label    TEXT;   -- human-friendly label for the speaker
ALTER TABLE recall_entries ADD COLUMN IF NOT EXISTS source_interface TEXT;   -- interface the memory came from (slack, registerabot, ...)
ALTER TABLE recall_entries ADD COLUMN IF NOT EXISTS session_id       TEXT;   -- set for scope='session' (ephemeral notes)

-- 'session' is a new status meaning "ephemeral, live now, not pending approval, not permanent".
-- Owner/speaker proposals still use 'pending' → 'approved'/'rejected'.

CREATE INDEX IF NOT EXISTS idx_recall_scope_speaker ON recall_entries(scope, speaker_id, status);
CREATE INDEX IF NOT EXISTS idx_recall_session ON recall_entries(session_id) WHERE scope = 'session';
