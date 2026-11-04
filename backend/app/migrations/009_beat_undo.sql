-- Snapshots taken before each split or merge on the Beats step, so the latest ones can be undone:
-- the beats' word ranges and the image prompts that went with them (JSON).
CREATE TABLE beat_undo (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    snapshot    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
