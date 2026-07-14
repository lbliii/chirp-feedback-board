CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 3 AND 80),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 10 AND 600),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'planned', 'in_progress', 'shipped')),
    vote_count INTEGER NOT NULL DEFAULT 0 CHECK (vote_count >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS votes (
    suggestion_id TEXT NOT NULL REFERENCES suggestions(id) ON DELETE CASCADE,
    voter_key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (suggestion_id, voter_key_hash)
);

CREATE INDEX IF NOT EXISTS suggestions_status_created_idx
    ON suggestions (status, created_at);

CREATE INDEX IF NOT EXISTS suggestions_votes_idx
    ON suggestions (vote_count, created_at);
