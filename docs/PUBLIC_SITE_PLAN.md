# RAG research + public video site with chatbot

The plan for (1) researching each video from 10-15 downloaded sources stored in a shared vector database,
and using them while writing the script, and (2) a public website of the finished videos with semantic search
and a chatbot that answers questions about a video with timestamps. Video creation stays private on the
owner's PC.

**If a session gets disconnected:** read this file, check the Status table and the Log at the bottom, then
carry on with the first unchecked task. Tick tasks off (`[x]`) and add a Log entry as you go.

Replaces the earlier plan (2026-11-03) that started with a local gallery and Voyage embeddings.

---

## Status

| Phase | What | Status |
|---|---|---|
| A | Corpus: download sources, chunk, embed (Gemini), store (Supabase pgvector) | ✅ Built, waiting for keys to try for real |
| B | RAG in research (brief from sources), script and chat | ✅ Built, waiting for keys to try for real |
| C | "Publish to site": narration chunks with timestamps, thumbnails | Not started |
| D | Public site: gallery, semantic search, watch page + chatbot (Gemini Flash-Lite) | Not started |
| E | Deploy (Supabase, Render/Fly API, Cloudflare Pages site) | Not started |

## Decisions (made with the owner, 2026-11-06)

- **Vector DB:** Supabase Postgres + pgvector (free tier, 500 MB). The same database will hold the site's
  videos. Schema: `backend/supabase/schema.sql` (run once in Supabase's SQL Editor).
- **Embeddings:** Gemini `gemini-embedding-001`, 768 dimensions, one free Google key (`GEMINI_API_KEY`) for
  embeddings and, later, the chatbot. Keep billing off on that Google project: the free tier can then only
  answer "too many requests", never send a bill.
- **Order:** studio RAG first, then the site.
- **Playback:** YouTube embeds (timestamps seek the player).
- **Search:** hybrid, vector + Postgres full-text, merged with reciprocal rank fusion.
- **Shared corpus:** `documents` are keyed by URL and shared by every project (and, later, every user via
  the `owner` column). A page already stored with the same text is reused without new embeddings.
  Retrieval uses the project's own sources first, plus a few close matches (similarity >= 0.8) from others.

Honest expectation: the big speed and Claude-usage saving is in research (Python downloads pages instead of
Claude opening them, and the brief is written from excerpts with no web tools). Writing the script costs about
the same; the excerpts mainly improve accuracy.

## Phase A + B: what was built

- `pipeline/sources.py`: Claude picks 3-6 Wikipedia titles and 6-10 other pages (max 3 searches, no page
  opens); Python downloads them in parallel (Wikipedia API, trafilatura for other pages), skips PDFs, blocked
  sites and pages under 300 words, tops up with Wikipedia search if under the minimum.
- `pipeline/chunking.py`: ~300-word chunks, ~50-word overlap, sentence/paragraph breaks, section headings kept.
- `pipeline/embeddings.py`: Gemini batch embeddings over httpx, retries on 429, vectors normalized.
- `pipeline/vector_store.py`: `PgStore` (psycopg, plain SQL) and `MemoryStore` (tests).
- `pipeline/rag.py`: index, retrieve (round robin over questions), brief from excerpts, script and chat excerpts.
- Routes: Research uses RAG when `rag.enabled` and both keys are set (old web-search research otherwise).
  `GET /sources`, `POST /sources/more`, `DELETE /sources/{id}`. Script and chat get excerpts; if the database
  or Gemini fails they write without them.
- Settings: `GEMINI_API_KEY`, `SUPABASE_DB_URL`, a "Test Gemini and Supabase" button, `rag.*` fields.
- Local table `project_sources` (migration 010) lists each project's downloaded sources.

To try it: create a Supabase project, run `backend/supabase/schema.sql` in its SQL Editor, copy the Session
pooler URI (with the database password) into Settings, add a Gemini key from aistudio.google.com, click
"Test Gemini and Supabase", then Research on a new project.

## Phase C: Publish videos to the site

- [ ] Migration `011_site.sql`: per project `youtube_url`, `site_summary`, `published_at`.
- [ ] `pipeline/site_publish.py`: narration chunks from the `words` table (30-45 s windows on sentence ends,
      with start/end seconds), embedded and upserted into `videos` / `video_chunks`.
- [ ] Thumbnail: ffmpeg frame from `output/video.mp4` to Supabase Storage, or the owner's own image.
- [ ] Publish step: YouTube URL + summary fields; "Publish to site" / "Update" / "Remove" (confirm first).
- [ ] Check that word times match the final video (the video's audio is the voiceover).

## Phase D: Public site (separate, read-only)

- [ ] `site/api/` FastAPI: `GET /videos`, `GET /videos/{id}`, `GET /search?q=` (hybrid, best moment per
      video), `POST /chat` (top ~8 chunks from the video's narration + its sources, Gemini Flash-Lite, cites
      `[3:42]`, says when the video doesn't cover it, streamed).
- [ ] Abuse limits: billing-off Google key, per-IP limit (~10 questions/hour) and a daily global cap,
      question length cap, ~400 output tokens, last 4 turns of history, answer cache. Read-only DB role.
- [ ] `site/web/` React + Vite: search bar, video grid, watch page with YouTube embed + chat sidebar;
      timestamp links seek the player.

## Phase E: Deploy

- [ ] API on Render or Fly.io free tier, site on Cloudflare Pages, secrets in the host dashboards.
      Nothing is deployed without the owner's go-ahead.

---

## Log

Newest first.

### 2026-11-06: Phases A and B built
- Built the corpus and RAG research/script flow (see above). 148 tests pass; the UI builds.
- Real-network check: Wikipedia API and page extraction work (Franklin article: 9,781 words, 41 chunks).
  Wikipedia needs a User-Agent with a contact URL (the GitHub project page is used, never an email).
- Not yet run end to end against Supabase and Gemini: the owner needs to create both and add the keys.
- Next: owner sets up keys and tries Research on a new video; then Phase C.

### 2026-11-03: First plan written (superseded)
