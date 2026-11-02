-- Video type: one true story, a topic explained, or a countdown of several stories.
ALTER TABLE ideas ADD COLUMN format TEXT NOT NULL DEFAULT 'story';      -- story | topic | list
ALTER TABLE projects ADD COLUMN format TEXT NOT NULL DEFAULT 'story';
ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;

-- The vertical Short cut from the start of the video, and its text for each app.
CREATE TABLE shorts (
    project_id  INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    caption     TEXT NOT NULL DEFAULT '',
    hashtags    TEXT NOT NULL DEFAULT '[]',                   -- JSON list
    youtube_url TEXT NOT NULL DEFAULT '',                     -- the full video, linked in every description
    rendered_at TEXT,
    duration_s  REAL
);

-- One row per upload attempt to YouTube, Instagram, Facebook or TikTok.
CREATE TABLE social_posts (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,                                -- youtube | instagram | facebook | tiktok
    status      TEXT NOT NULL,                                -- posted | processing | error
    post_id     TEXT,
    url         TEXT,
    error       TEXT,
    rendered_at TEXT,                                         -- which render of the Short was posted
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_social_posts_project ON social_posts(project_id, platform, id);
