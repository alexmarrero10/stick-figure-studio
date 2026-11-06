-- Source documents downloaded for a project's research (the pages themselves and their chunks live
-- in the shared vector database; this is the local list shown on the Script step).
CREATE TABLE project_sources (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'web',      -- 'wikipedia' or 'web'
    status      TEXT NOT NULL DEFAULT 'ok',       -- 'ok' (stored) or 'skipped'
    reason      TEXT NOT NULL DEFAULT '',         -- why it was skipped
    words       INTEGER NOT NULL DEFAULT 0,
    chunks      INTEGER NOT NULL DEFAULT 0,
    reused      INTEGER NOT NULL DEFAULT 0,       -- 1 if it was already in the vector database
    remote_id   INTEGER,                          -- documents.id in the vector database
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, url)
);
