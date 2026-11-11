# Notes: current state (updated 2026-11-11)

Read CLAUDE.md first for how the project works and the rules. This file is what's happening now.

## Where things stand

- The full pipeline works end to end and has made two real videos (both format "story"):
  1. **Project 1:** "The Inuit Knew Where Franklin's Lost Ships Were. No One Listened" (151 shots)
  2. **Project 2:** "How a Hand-Drawn Family Tree Found Saddam in a Hole" (238 shots)
- Channel problem being worked on: **low retention.** Average view duration is about 25% on long videos and
  about 65% on Shorts, and views are low. Recent work targets this.
- 182 backend tests and 21 studio browser tests pass; the frontend builds. Version 1.0.0 (local tag `v1.0.0`,
  not pushed). The studio redesign commit (2026-11-11) and the notes commit before it are local, not pushed.
- **Public site is live: https://stick-figure-studio.vercel.app** (Vercel project `alex-2f75/stick-figure-studio`).
  Vercel redeploys automatically on every push to `main`; check a build with
  `gh api repos/alexmarrero10/stick-figure-studio/commits/<sha>/status`. No Vercel CLI installed.
  Projects 1, 2 and 3 (Watergate) are published on it.
- Project 3 is Watergate ("The Piece of Tape That Brought Down a President"): all 221 images in, assembled,
  published to the site.

## Recently done

- **Ideas are never lost (2026-11-11):** "Use my own idea" (button now "Save my idea") saves the idea at once
  (`saved=1`, `POST /api/ideas/own`) and shows it as one full-width feature card. Saved ideas not yet started
  are listed on the Projects page ("Saved ideas": Start project / Remove) via `GET /api/ideas?saved=true&unused=true`.
  The Find a story page reloads the latest 6 unsaved suggestions (`?unused=true`) and keeps the half-typed idea,
  theme and choices in localStorage (`ideas-draft`). Suggestions are still only saved when asked.
- **Studio follow-ups (2026-11-11):** Settings grouped into sections (API keys, Claude, Research sources,
  Script and beats, Voice, Pictures and video, Publishing and Shorts) with a side menu and a save bar that stays
  on screen; bigger project titles and labels on the home page; "New video" renamed "New project"; Claude
  suggests 3 ideas at a time (was 10; `count` default 3 in the route and `ideas.suggest`).
- **Studio redesign (2026-11-11)** in the public site's look (navy ink, cool paper, red marker for the current
  step, yellow highlighter for the playing beat, Bricolage Grotesque + Atkinson Hyperlegible, dark mode). New
  top bar with the stick-figure mark, a connected step track (done = navy check, needs attention = yellow,
  current = red ring, `aria-current="step"`), line icons (`Icon` in `components.tsx`) instead of text arrows,
  quieter project chips. Only CSS class styling changed in the steps; behavior is the same.
- **Studio browser tests** (`frontend/e2e/`, Playwright with the Edge that ships with Windows):
  `cd frontend && npm run test:e2e` builds, serves the build with `vite preview` on port 4179 and runs 18 tests
  against a **fake backend** (`e2e/mock.ts` answers every `/api` call from `e2e/fixtures.json`), so they never
  touch the real server, app.db, config.yaml or .env. A test fails on any page error or any API call with no
  answer. Refresh the data with `node e2e/record-fixtures.mjs 1` while the studio runs (GET only; trims long
  lists, replaces keys with fakes, strips local folder names). New step = add its GET paths to the recorder.

- **Site chatbot answers beyond the video directly** (no "the video doesn't cover that, but..."); the
  evals judge (`evals/answers.py`) grades that way too. New tests: 3 offline in `site/server/tests` (each
  question searches this video's narration and research sources and both reach the model) and live ones in
  `evals/tests/test_chatbot_live.py` (skipped unless `LIVE_EVALS=1`; real retrieval hit rates, not turned
  away, answers cite given passages, the Nixon/McGovern question gets a straight answer). Not pushed yet.

- **Public site redesign (live since 2026-11-11, e13c486; the user likes it):** "Next Door Historian" branding; navy ink on cool paper, the red
  marker ring from the thumbnails (drawn once around the hero search, beside a stick figure that draws
  itself; skipped with reduced motion), yellow highlighter timestamp chips. Fonts: Bricolage Grotesque
  (headings, numbers) + Atkinson Hyperlegible (body). Home = hero search, "Newest story" feature, grid;
  search = result rows with the matching moment; dark mode kept. Thumbnails use 16:9 `maxresdefault`
  (fallback `mqdefault`) instead of letterboxed `hqdefault`. Literal "\n" in stored summaries is shown as
  paragraphs. Chat accepts loose stamps like "[0:0]". Checked with Playwright at 1366 px and 390 px.

- **Gemini free-tier pacing:** embeddings are batched by size (max 100 texts and ~20K tokens per request,
  `embeddings.batches`) and paced to stay under ~24K tokens / 90 texts a minute (free tier: 30K / 100).
  Big research runs now wait instead of hitting 429s. Site search's global daily cap is 100
  (`SEARCH_GLOBAL_PER_DAY`), since search and chat share the 1K-a-day embedding limit with the studio.

- **Thumbnail panel is "idea to prompt"** (Publish step): the pack no longer writes 3 thumbnail prompts; **Give
  suggestion** writes one (`publish.suggest_thumbnail`, told to differ from those listed). Newest listed first. Works before the pack exists.

- **Script rule:** clumsy real quotes are retold in plain words; never "1 person, 2 persons". Watergate's script
  still has Frank Wills' "one person, then two persons..." quote (voice + beats already made on v30; not changed).

- **Zoom no longer shakes:** `assemble.zoom_filter` uses FFmpeg `perspective` (sub-pixel, cubic) instead of
  `zoompan`, whose whole-pixel crops made pictures jump back and forth. Same speed. Applies on the next Assemble.

- **Short background is black** with a white channel name (`shorts.background`, `shorts.text_color`, both on
  Settings). Applies on the next Assemble.

- **Bulk image upload (2026-11-10):** one zip holding every batch's Flow download (inner zips or folders), or several
  zips, on the Images step. Each image goes to the batch it matches by title; unmatched images in a download go
  to that download's batch. In one flat zip, a title two batches share is settled by zip order (Flow lists
  newest batch first, batch by batch). Dry run on Watergate's real 221-image zip: all 221 placed. Unplaced ones are listed.

- **Image file naming (55fb5ab, 2026-11-10):** prompts start with a short title and **no number** (the
  numbered "7 - Title" made Flow draw numbers in image corners). `prompts.batch_titles` keeps titles unique per
  batch; the import (`images.slot_for_title`) matches Flow's file name to the slot. Titles stay 3 words since
  Flow keeps only ~3 words of the name. Old numbered files still work.
- **Big text in prompts was tried and reverted** (765b396 -> 8221380): numbers appeared in corners. Don't redo.
- **Character look rules:** faces never described (no nose etc.; caricature risk), hair pinned exactly
  (1c58f2f); every character looks different, group members may share clothes but differ in hair/facial
  hair/glasses/build (148da63, 1c91316); character sheet for characters in 8+ pictures, made before batch 1
  (6d5a8b0).
- **Public site:** channel name and footer removed, Vercel setup (07c8649); later split into two Vercel services
  (b4fd7de) and the chatbot now answers wider-topic questions (bbb32fd). Not deployed.
- **docs/RAG_EXPLAINED.md:** study guide on how the RAG works (for the user's resume).
- **Voice:** Brian at 1.2x; Settings shows the real voice name (cc99488).

- **Check facts** button on the Script step (`fact_check.py`, `POST /script/factcheck`): checks names, dates,
  numbers and quotes; wrong ones come back as fixes in the chat, unconfirmed ones are listed. With RAG it
  checks against the stored passages for each paragraph (no tools); without, against the brief + web search.
  The speed test (`evals/speed.py`) now runs the same four steps both ways: research, script, fact check,
  one revision. First run (research + script only): research 39% faster and 91% fewer input tokens with
  RAG, script ~1 min slower (it gets passages too), total about even. Voice is now Brian at 1.2x; v1.0.0 tagged.

- **Faster narration** (`voice.speed`, set to 1.1 on 2026-11-06): the voice-over is sped up after ElevenLabs
  (FFmpeg atempo, pitch kept) and word timings are scaled to the measured length. Previews use it too.
  Previews now trim pauses and apply the speed too (before, they had untrimmed 0.6-0.8 s sentence gaps).
  Tried 0.3 s longest pause: the user said it sounded cut off, so it's back to 0.45 s, and trimming now
  measures where the sound really stops (word end times can be early) so it never clips a word. Old voice-overs ran ~177-187 wpm; 1.1x gives ~195-205. Applies to new voice-overs only. At 1.1x the
  1,550-1,650 word target gives ~8.1 min, close to the 8:00 mid-roll line (consider ~1,750 words).
- **Speed/token benchmark** (`evals/speed.py`): old research vs RAG on the same topic; the CLI provider can
  record each call's time and token use (`ClaudeCode.usage_log`).

- **"Your video site" is its own step** (UI step 7, `frontend/src/steps/Site.tsx`), split out of Publish; the
  "Before you upload" checklist was removed from Publish.

- **RAG evals** (`evals/`, see its README). First run, 2026-11-06, 2 videos + project 3's sources:
  - Retrieval: narration hit@6 100% (hit@1 88%); sources hit@3 80%, hit@6 95%; hybrid slightly beats
    vector-only on sources; search bar right video first 100%; off-topic searches empty 8/8.
  - Answers (30): grounded 93%, correct 100%, timestamps valid 43/43, cites the right moment 100%, says
    "not covered" 83% (the misses answer a nearby fact without saying the video doesn't cover the question).
  - Guard rails: 0/54 real questions refused; 61/80 attacks stopped free; of the 19 that got through, the
    model declined 18 (one "Ahoy, matey!" before steering back). Sweep says 0.57 would still refuse no real
    questions and let fewer attacks through (0.55 now); 0.59 is the "fewest mistakes" point.

- **Chatbot guard rails** (site): questions scoring under 0.55 similarity to the video's narration/sources
  are turned away before Gemini writes anything (measured on the real videos: real questions 0.58-0.77,
  off-topic 0.46-0.56); stricter rules (visitor text is questions only, no role-play, no revealing
  instructions); Google safety filter at medium; empty/blocked answers get a polite reply. Tests check that
  keys and the DB password never reach the model or the visitor. Checked live with real Gemini.

- **Short tab and all posting removed** (user's request): Assemble now renders the Short next to the full
  video (shown side by side on the Assemble step; download and upload it yourself). Deleted the Short step,
  `routes/shorts.py`, `routes/social.py`, `pipeline/social/`, `SocialAccounts.tsx`, the Short title/caption
  writer and the social settings. Kept the `shorts` table (cut point, rendered time) and left the
  `social_posts` table and any social tokens in `.env` alone. The `social:` section in config.yaml is unused.

- **`SITE_DATABASE_URL` on Settings** (4e8eeac): the read-only `site_reader` address is saved to `.env` from
  the Settings page; the local site reads it (falls back to `SUPABASE_DB_URL` when empty). The user's local
  `002_site_reader.sql` has their real password as an uncommitted edit: **never commit it**; restore the
  placeholder with `git checkout` once they confirm they've run it.

- **Public site built** (`site/`, Phase D): search by meaning, watch page with YouTube player and a Gemini
  chatbot with clickable timestamps, abuse limits, read-only DB user. Tested locally against real Supabase
  and Gemini; not deployed. Run it: see CLAUDE.md "Public site". Deploy steps: `site/README.md`.
- **RAG research used for real** on project 3 (14 sources, 128 passages in Supabase). **Publish to site**
  (Phase C) is built: the Publish step's "Your video site" panel stores the video and its timed narration in
  Supabase `videos` / `video_chunks`. Nothing published yet. Next: Phase D, the public site.
- **`start.bat` restarts the app**: it stops a Stick Figure Studio server already on the port (including a
  `-Dev` reloader), unless `GET /api/jobs` (no project = all projects) shows a running job; then it warns and
  leaves it alone. Restart this way (or the same check by hand) after backend changes.
- **RAG research (Phases A + B)**: research can download 10-15 sources (Wikipedia + pages Claude picks),
  chunk and embed them (Gemini) into Supabase pgvector, and write the brief from retrieved passages with no
  web tools. Script and chat requests get source excerpts. Sources are listed on the Script step (remove,
  find more). Off until the user adds `GEMINI_API_KEY` and `SUPABASE_DB_URL` on Settings; the old web-search
  research is used otherwise. **Not yet run against real Supabase/Gemini.** Setup steps are in the plan file.
- **Script style modeled on top channels** (commit 0b31f28): a new CHANNEL STYLE section in `SCRIPT_SYSTEM`
  (see CLAUDE.md), new ending rule (no subscribe asks; end on a bookend line or one comment question), more
  energetic tone, scene-drop openings allowed. Not yet tried on a new video.
- **Slow zoom on long shots** (0b31f28, f76c398): shots of 3 s or longer zoom in at 1.5%/s, capped at 12%.
  About 81 of 151 shots (project 1) and 76 of 238 (project 2) qualify. Applies on the next Assemble. Settings
  has both knobs under Video. The Final Cut export and Shorts are not zoomed.
- Restored `docs/PUBLIC_SITE_PLAN.md`, which f76c398 had deleted by mistake (de096c5).
- Earlier: Stop button for long steps, Settings save feedback and dropdowns, beat undo, script drawer, grammar
  check, image slot picking and swapping, thumbnail prompts from the user's own idea, Shorts ending on the best
  cliffhanger at 50-70 s.

## Next

1. Site is deployed. Confirm with the user that they ran `backend/supabase/002_site_reader.sql`, then restore
   its placeholder with `git checkout` (it holds their real password: never commit it). `v1.0.0` tag is local only.
2. Finish project 3 (Watergate): user recopies batches (old copies had numbers), makes images in Flow.
   Open question to the user: should Frank Wills (Black security guard) get a brown head?
3. Full speed test (`evals/speed.py --ways rag,full,old`) paused on 2026-11-09 for the user's usage limits;
   rerun when they say so.
4. Possibly re-assemble projects 1 and 2 to see the zoom (only if the user wants new versions).
5. Push to GitHub only when the user asks (`alexmarrero10/stick-figure-studio`, private). A push redeploys
   the public site.
6. Open questions to the user (no answer yet): fix the Watergate script's clumsy Frank Wills quote (means
   redoing beats and voice)? Quick Playwright browser checks after UI changes, or real Playwright tests?

## Claude tools installed (2026-11-10, user scope)

- Plugins: `frontend-design@claude-plugins-official`, `impeccable@impeccable` (runs a design-check hook at
  session start, after each Edit/Write and at stop; `/impeccable hooks off` turns it off per project),
  `ui-ux-pro-max@ui-ux-pro-max-skill`. Skills copied from vercel-labs/agent-skills into `~/.claude/skills`:
  `web-design-guidelines`, `react-best-practices`, `composition-patterns` (deploy/account skills skipped).
- Playwright MCP works for screenshots (save under `.playwright-mcp/`, gitignored). The first screenshot
  after a navigation is often a stale frame: take a second one.

## Ideas discussed, not started

- **A few Veo clips via Google Flow** for small figure animations. Free tier ~50 credits/day; Veo 3.1 Lite ~10
  credits per clip, Fast ~20, Quality ~100. Plan was the FFmpeg zoom for most shots plus a handful of Veo clips.
  Would be done manually by the user (no Flow automation).
- **Settings toggle for an AI-voice line** at the bottom of the description (offered, not accepted).
- **Era corpora** (medieval, samurai, Chronicling America) in the vector DB to improve Ideas. Parked.

## Open issues

- `README.md` and `PROGRESS.md` are partly out of date. They say the "current project" is the public site. CLAUDE.md and this file are correct. The
  `shots.py` docstring also says "pictures are never zoomed" (zoom now happens in `assemble.py`).
- `projects/a-han-governor-removed-the-tiger-traps-and-the-tigers-left/` exists on disk but has no project row
  in the database (leftover folder).
- `config.yaml` has an uncommitted change by the user: `claude.research_depth: thorough`. The new `rag:`
  section isn't in config.yaml yet (code defaults in `app/deps.py` RAG_DEFAULTS); saving Settings adds it.
- Still never checked by hand: importing `timeline.fcpxml` into DaVinci Resolve.
