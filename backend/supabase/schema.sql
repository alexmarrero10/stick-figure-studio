-- Stick Figure Studio: the shared vector database (Supabase Postgres + pgvector).
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- It is safe to run again; it only creates what is missing.
-- Later changes go in new numbered files next to this one (002_..., 003_...).

create extension if not exists vector;

-- One row per source page (Wikipedia article, archive page, ...). Shared by every project and, later,
-- every user: a page fetched for one video helps the next video on a similar topic.
create table if not exists documents (
    id           bigserial primary key,
    url          text not null unique,
    title        text not null default '',
    source_type  text not null default 'web',      -- 'wikipedia' or 'web'
    text_hash    text not null default '',
    words        integer not null default 0,
    owner        text not null default 'owner',
    fetched_at   timestamptz not null default now()
);

create table if not exists chunks (
    id           bigserial primary key,
    document_id  bigint not null references documents(id) on delete cascade,
    ord          integer not null,
    heading      text not null default '',
    text         text not null,
    embedding    vector(768) not null,
    tsv          tsvector generated always as (to_tsvector('english', coalesce(heading, '') || ' ' || text)) stored,
    unique (document_id, ord)
);
create index if not exists chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_tsv_idx on chunks using gin (tsv);

-- Which documents a video's research used. project_key = '<owner>:<local project id>'.
create table if not exists project_documents (
    project_key  text not null,
    document_id  bigint not null references documents(id) on delete cascade,
    added_at     timestamptz not null default now(),
    primary key (project_key, document_id)
);

-- Published videos for the public site (filled by "Publish to site" in the studio).
create table if not exists videos (
    id           bigserial primary key,
    project_key  text not null unique,
    owner        text not null default 'owner',
    title        text not null,
    summary      text not null default '',
    description  text not null default '',
    youtube_id   text not null,
    thumbnail_url text not null default '',
    duration_s   real not null default 0,
    published_at timestamptz not null default now()
);

-- The narration of each published video, in 30-45 s windows with their times, for search and the chatbot.
create table if not exists video_chunks (
    id           bigserial primary key,
    video_id     bigint not null references videos(id) on delete cascade,
    ord          integer not null,
    start_s      real not null,
    end_s        real not null,
    text         text not null,
    embedding    vector(768) not null,
    tsv          tsvector generated always as (to_tsvector('english', text)) stored,
    unique (video_id, ord)
);
create index if not exists video_chunks_embedding_idx on video_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists video_chunks_tsv_idx on video_chunks using gin (tsv);

-- Keep the tables away from Supabase's public REST API: only the studio (and later the site's server)
-- reach them, with the database password. Row level security with no policies blocks anon access.
alter table documents enable row level security;
alter table chunks enable row level security;
alter table project_documents enable row level security;
alter table videos enable row level security;
alter table video_chunks enable row level security;
