-- Recall entries: things the bot wants to remember
CREATE TABLE IF NOT EXISTS recall_entries (
    id              SERIAL PRIMARY KEY,
    content         TEXT NOT NULL,
    source          TEXT,                          -- where the bot found this (URL, conversation, etc.)
    reason          TEXT,                          -- why the bot wants to remember it
    tags            TEXT[] DEFAULT '{}',            -- searchable tags
    status          TEXT NOT NULL DEFAULT 'pending', -- pending, approved, rejected, expired
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ DEFAULT (now() + INTERVAL '7 days')  -- pending entries expire after 7 days
);

CREATE INDEX IF NOT EXISTS idx_recall_status ON recall_entries(status);
CREATE INDEX IF NOT EXISTS idx_recall_created ON recall_entries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recall_tags ON recall_entries USING GIN(tags);
