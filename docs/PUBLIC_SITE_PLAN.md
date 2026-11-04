# Public Video Library with Search and RAG Q&A

The plan for turning Stick Figure Studio into a portfolio project: a public website where anyone can
browse the finished videos, search them by meaning, and ask questions that are answered from the
videos' own narration with timestamped citations. Video creation stays private.

**If a session gets disconnected:** read this file, check the Status table and the Log at the bottom,
then carry on with the first unchecked task. Tick tasks off (`[x]`) and add a Log entry as you go.

---

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Gallery home screen + Projects screen (local, no API keys) | ⏳ Next |
| 2 | Chunking, embeddings, hybrid search (local) | Not started |
| 3 | Evaluation set and retrieval metrics | Not started |
| 4 | "Ask the archive": RAG answers with timestamp citations | Not started |
| 5 | Split into public site + API, deploy, "Publish to site" | Not started |
| 6 | README, architecture diagram, metrics, demo GIF | Not started |

## Goals

- **Public site:** a gallery of finished videos (thumbnail, title, short description), semantic search,
  and Q&A over the narration. Read-only for visitors.
- **Private studio:** the current app, still only on the owner's PC. Only the owner can create videos.
- **Resume value:** real RAG (retrieve, then generate a grounded, cited answer), hybrid retrieval, and
  measured results (recall@k, MRR, answer faithfulness), not just a demo.

## Decisions

Made:
- Studio stays local (it relies on the Claude Code CLI subscription, ffmpeg and local files). The public
  site is a separate read-only app; the studio pushes content to it with a secret key.
- Public videos play as **YouTube embeds** (no self-hosted MP4s; the player can start at any second, which
  makes timestamp citations work). Locally, the gallery plays `output/video.mp4` directly.
- Search is **hybrid**: vector similarity + full-text keyword search, merged with reciprocal rank fusion.
- The LLM and embedding model sit behind one small provider interface, so switching models is a config change.
- Free-tier first:
  - **Answers:** Google Gemini Flash-Lite (free tier, roughly 500 requests/day reported). Fallback: Groq
    Llama 3.1 8B (roughly 14,400 requests/day, 500K tokens/day reported). Later option: Claude Haiku via API key.
  - **Embeddings:** Voyage AI (about 200M free tokens reported). Fallback: Gemini embeddings.
  - These limits come from third-party reports. Check the official pages (Google AI Studio rate limits,
    console.groq.com/docs/rate-limits, Voyage pricing) before relying on them.
- Budget per question: about 3,000 input tokens (about 8 chunks + instructions) and about 300 output tokens.
- Public Q&A needs per-visitor rate limiting (e.g. 10 questions/hour) and a cache for repeated questions.

Still open:
- Hosting: Postgres + pgvector on Supabase or Neon; API on Render, Fly.io or Railway; site on Cloudflare
  Pages or Vercel. Custom domain optional.
- Whether to index research briefs (as background facts, not citable moments).

## Data the app already has

| What | Where |
|---|---|
| Projects (title, format, archived) | `projects` table |
| Finished video | `projects/<slug>/output/video.mp4` (Franklin has one; Saddam not yet) |
| Short | `projects/<slug>/output/short.mp4`, `shorts` table (has `youtube_url`) |
| Titles, description, tags, chapters, thumbnail prompts | `publish_meta.content` (JSON) |
| Script text | `script_versions` |
| Every narrated word with start/end time | `words` table (from the voiceover) |
| Research brief with sources | `research_briefs` |

Notes:
- There is no stored YouTube URL for the full video yet, and no thumbnail image (only thumbnail prompts).
- Word times are voiceover times. Check they match the final video's timeline (shot lead-in, any intro)
  before using them for citations.

## Architecture (target)

```
Owner's PC (private)                       Hosted (public)
┌──────────────────────┐   publish        ┌──────────────────────────────┐
│ Stick Figure Studio   │ ──────────────▶  │ API: /videos /search /ask      │
│ FastAPI + React        │  (secret key)    │ Postgres + pgvector            │
│ script → … → video     │                  │ Site: gallery, search, ask,    │
└──────────────────────┘                  │ watch page with YouTube embed   │
                                            └──────────────────────────────┘
```

---

## Phase 1: Gallery home screen + Projects screen

No new services or API keys. Everything is local and uses data the app already has.

Routing (hash routes in `frontend/src/App.tsx`):
- `#/` becomes the new **gallery** home (`frontend/src/steps/Gallery.tsx`, new).
- The current home screen (`frontend/src/steps/Home.tsx`, project list + new project) moves to
  `#/projects`. Project pages stay at `#/p/<id>/<step>`.
- The header gets a **Projects** button/link (to `#/projects`) next to Ideas and Settings.

Backend:
- [ ] `GET /api/gallery`: one entry per non-archived project that has a finished video
      (`output/video.mp4` exists). Fields:
  - project id and title (publish title if chosen, else project title);
  - a short description (first 1-2 sentences of the publish description, or a new `summary` field);
  - duration, date finished, video URL (via the existing `/api/projects/{id}/file` route);
  - thumbnail URL and YouTube URL (if set).
- [ ] Thumbnails: grab one frame from `video.mp4` with ffmpeg (e.g. at 10% in), cached as
      `output/thumbnail.jpg`, regenerated when the video is newer than the thumbnail. Allow uploading a
      custom thumbnail image instead.
- [ ] Per-project site fields: `youtube_url` for the full video and an optional `summary` override.
      New migration (`010_...sql`; 007-009 are taken). Editable on the Publish step.
- [ ] Simple local search for now: case-insensitive match over title, description and tags, so the
      search box works before Phase 2. Phase 2 replaces it behind the same endpoint (`GET /api/gallery?q=`).

Frontend:
- [ ] Gallery: responsive grid of video cards (thumbnail, title, 1-2 line description, duration).
      Large search box on top. Empty state when no videos are finished yet, with a link to Projects.
- [ ] Watch page (`#/watch/<id>`): video player (local MP4 now, YouTube embed when `youtube_url` is set),
      title, full description, link to the project in the studio.
- [ ] Projects page: today's home screen, unchanged apart from its route and heading.
- [ ] Publish step: fields for YouTube URL and site summary.

Tests:
- [ ] `/api/gallery` lists only projects with a video, skips archived ones, and filters with `q`.
- [ ] Thumbnail is created once and reused.
- [ ] Browser check: gallery → watch page → Projects → a project step and back.

Done when: opening the app shows the gallery with the Franklin video, search filters it, clicking plays
it, and Projects leads to the existing workflow.

## Phase 2: Chunking, embeddings, hybrid search

- [ ] Chunker: split each video's narration (from `words`) into windows of about 30-45 s, breaking on
      sentence ends, keeping start/end seconds. Also index title + description as their own entries.
- [ ] Provider interface for embeddings (`embed(texts) -> vectors`): Voyage first, Gemini fallback.
      Keys go in `.env` via the Settings page (never in chat or git).
- [ ] Local vector store (SQLite + `sqlite-vec`, or a local Postgres with pgvector to match the hosted setup).
- [ ] Keyword search (SQLite FTS5 or Postgres full-text).
- [ ] Hybrid ranking: reciprocal rank fusion of vector and keyword results, grouped by video. Each hit
      returns its best matching moment ("...quote... ▶ 0:12").
- [ ] Index when a video is assembled (and a "Reindex all" button). `GET /api/gallery?q=` uses it.
- [ ] Gallery shows matching moments under each result; clicking jumps the player to that second.

## Phase 3: Evaluation

- [ ] Test set (`backend/eval/questions.yaml`): 20-40 questions or search phrases, each with the expected
      video and approximate timestamp.
- [ ] Script reporting recall@5 and MRR for vector-only, keyword-only and hybrid.
- [ ] Record results in this file and the README.

## Phase 4: Ask the archive (RAG)

- [ ] Provider interface for answers (`answer(question, chunks) -> streamed text`): Gemini Flash-Lite
      first, Groq fallback, Claude Haiku option.
- [ ] Retrieve the top ~8 chunks with hybrid search. Answer **only** from them, cite each claim as
      [video, timestamp], and say "my videos don't cover that" when the chunks don't answer it.
- [ ] Stream the answer; citations render as links that open the watch page at that second.
- [ ] Suggested questions on the home page (generated once from the archive, cached).
- [ ] Answer checks in the eval: every cited chunk exists and supports its claim.
- [ ] Rate limit per visitor and cache repeated questions.

## Phase 5: Public site and deployment

- [ ] Split out a small public API (read-only: videos, search, ask) and the public React site (gallery,
      search, ask, watch page with YouTube embed). No studio routes are deployed.
- [ ] Hosted Postgres + pgvector. "Publish to site" / "Update" / "Remove" buttons in the studio push a
      video's metadata, chunks and embeddings with a secret publish key.
- [ ] Deploy, set environment secrets on the host, add rate limits and a spending cap on any paid key.

## Phase 6: Portfolio polish

- [ ] README: what it is, architecture diagram, retrieval design and why hybrid, eval numbers, demo GIF,
      live link, what I'd do next.

## Ideas for later (not planned yet)

- Use RAG in the studio: pull related facts from past briefs during research, suggest links to earlier
  videos for descriptions and end screens.
- Search Shorts as well as full videos.

---

## Log

Newest first. One entry per working session: what was done, decisions, what's next.

### 2026-11-03: Plan written
- Wrote this plan. Phase 1 is next; it needs no API keys.
- Meanwhile the owner will sign up for Gemini and Voyage API keys for Phases 2 and 4.
