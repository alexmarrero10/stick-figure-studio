-- What each video shows on the public site, and whether it has been published there.
CREATE TABLE site_videos (
    project_id   INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    youtube_url  TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    remote_id    INTEGER,                 -- videos.id in the site database (NULL = not published)
    chunks       INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
