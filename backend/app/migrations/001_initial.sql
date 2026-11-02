CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    idea_id     INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE ideas (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    hook          TEXT NOT NULL DEFAULT '',
    why_it_works  TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    era           TEXT NOT NULL DEFAULT '',
    documentation TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'suggested',  -- suggested | user
    saved         INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE research_briefs (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]',          -- JSON list of {title, url}
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE script_versions (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,                        -- generated | manual | ai_revision
    instruction TEXT,
    word_count  INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE revision_messages (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,                        -- user | assistant
    content     TEXT NOT NULL,
    edits       TEXT,                                 -- JSON list of proposed edits
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE beats (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    script_version_id INTEGER NOT NULL REFERENCES script_versions(id) ON DELETE CASCADE,
    idx               INTEGER NOT NULL,
    word_start        INTEGER NOT NULL,
    word_end          INTEGER NOT NULL,               -- inclusive
    text              TEXT NOT NULL,
    UNIQUE (project_id, idx)
);

CREATE TABLE voiceovers (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    script_version_id INTEGER NOT NULL REFERENCES script_versions(id) ON DELETE CASCADE,
    audio_path        TEXT NOT NULL,
    duration_s        REAL NOT NULL,
    warnings          TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE words (
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    start_s     REAL NOT NULL,
    end_s       REAL NOT NULL,
    PRIMARY KEY (project_id, idx)
);

CREATE TABLE style_guides (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    style_prefix TEXT NOT NULL,
    characters  TEXT NOT NULL DEFAULT '[]',           -- JSON list of {name, marker}
    setting_notes TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE image_prompts (
    beat_id     INTEGER PRIMARY KEY REFERENCES beats(id) ON DELETE CASCADE,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_no    INTEGER NOT NULL,
    scene       TEXT NOT NULL,
    edited      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE images (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_no    INTEGER NOT NULL,
    path        TEXT NOT NULL,
    sort_key    REAL NOT NULL,
    sort_source TEXT NOT NULL,                        -- metadata | mtime | filename
    position    INTEGER NOT NULL,                     -- order within the batch
    UNIQUE (project_id, path)
);

CREATE TABLE shots (
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    image_path  TEXT NOT NULL,
    start_frame INTEGER NOT NULL,
    end_frame   INTEGER NOT NULL,
    scale       REAL NOT NULL,
    beat_ids    TEXT NOT NULL,                        -- JSON list
    PRIMARY KEY (project_id, idx)
);

CREATE TABLE publish_meta (
    project_id  INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,                        -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_script_versions_project ON script_versions(project_id, id);
CREATE INDEX idx_beats_project ON beats(project_id, idx);
CREATE INDEX idx_images_project ON images(project_id, batch_no, position);
