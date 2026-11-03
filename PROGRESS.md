# Stick Figure Studio: Progress and Dev Notes

A local app (Python FastAPI + React) that automates most of the workflow for narrated stick-figure
YouTube videos about real stories:
idea → research → script → beats → ElevenLabs voice with word timings → Google Flow prompts (batches of 24)
→ image import and ordering → timed shots → preview MP4 + FCPXML for DaVinci Resolve → publishing pack.

**Conventions for this file:** update it at the end of every stage. For each stage, record what was
done, the decisions made, known issues, and what comes next. Newest notes go at the top of the log.

---

## Claude provider

The app talks to Claude in one of two ways. Choose it on the Settings page, or set `claude.provider` in `config.yaml`:
- **`claude_code` (default)** runs the local Claude Code CLI in headless mode (`claude -p`), using your
  Claude Pro/Max login. No API key is needed. It counts against your subscription's usage limits.
- **`api`** uses the Anthropic API with `ANTHROPIC_API_KEY` (pay as you go).

Both providers have the same interface (`stream_text` / `complete` / `json`), so every pipeline step works with either.

## Stage checklist

| # | Stage | Status |
|---|-------|--------|
| 0 | Setup and app shell: FastAPI, Vite/React, `start.ps1`, `.env`, settings page, SQLite + migrations, health checks | ✅ Done |
| 1 | Idea generation: Claude suggestions or your own idea, saved idea backlog | ✅ Done, live-tested via Claude Code |
| 2 | Research brief (web search), script generation (streaming), editor, version history, chat revisions with accept/reject edits | ✅ Done (not yet run against the live API) |
| 3 | Beats: deterministic splitter, Claude boundary review, manual merge/split | ✅ Done, unit tested |
| 4 | Voice: ElevenLabs with-timestamps, chunking, character → word timings, pause trimming | ✅ Done, unit tested with fake alignments (not yet run against the live API) |
| 5 | Image prompts: style guide, character markers, per-beat scenes, `batch_XX.txt` files | ✅ Done (not yet run against the live API) |
| 6 | Image import and ordering: metadata → mtime → filename, per-batch folders, drag to reorder | ✅ Done, unit + browser tested |
| 7 | Shots: cut lead, merges under 1 s, punch-ins over 5 s, frame snapping | ✅ Done, unit tested |
| 8 | Assembly: MP4 (FFmpeg), FCPXML 1.9, SRT captions | ✅ Done. MP4 verified frame-exact. **FCPXML import into Resolve still needs a manual check** |
| 9 | Publish pack: titles, description with sources and chapters, tags, thumbnail prompts, monetization checklist | ✅ Done (not yet run live) |
| 10 | Claude Code provider: run all Claude steps through `claude -p` with the user's subscription | ✅ Done, live-tested (ideas, streaming, revisions, beat review, style guide, scene prompts) |

## Next steps (in order)

**Current project: the public video library with search and RAG Q&A.** The full plan, task checklist
and log are in [docs/PUBLIC_SITE_PLAN.md](docs/PUBLIC_SITE_PLAN.md). Start there after a disconnect.

1. Add the ElevenLabs key (Settings page) and run a **full real video** end to end. Note any rough spots below.
   The research step (web search) and a full-length script haven't run through Claude Code yet.
2. **Resolve check:** File → Import → Timeline → `timeline.fcpxml`. Confirm that:
   - every shot is its own clip;
   - punch-ins show 115% zoom;
   - the voice is on A1 and stays in sync.

   If Resolve rejects `<video>` elements for stills, switch `fcpxml.py` to `<asset-clip>` (a small change).
3. Check that real Google Flow downloads carry a creation timestamp. Look at the sort-source label on each
   image card ("metadata" vs "mtime"). If Flow only provides file times, download images one by one in
   prompt order.
4. Tune the prompts after the first real run:
   - script length (Josh measured at ~182 wpm; re-check after the style change);
   - beat sizes;
   - the Flow style prefix.
5. Optional improvements:
   - background music bed + ducking in the MP4;
   - subtle Ken Burns drift on long shots;
   - per-step cost estimates;
   - git repository + CI.

## Architecture notes

- **Storage split.** SQLite (`data/app.db`) holds all structured, versioned data:
  - projects, ideas, research briefs, script versions, revision chat;
  - beats, word timings, style guides, prompts, image order, shots, publish metadata.

  Media and human-facing exports live in `projects/<slug>/`:
  - `script.md` mirror;
  - `audio/voice.wav` (master) and `voice.mp3`;
  - `prompts/batch_XX.txt`;
  - `images/batch_XX/`;
  - `output/`.
- **Word indices are the contract.** Word *i* is `script_text.split()[i]`. Beats store
  `word_start`/`word_end` (inclusive); voice timings are mapped onto the same indices.
- **Staleness.** Beats and the voice-over each store the `script_version_id` they were built from. The UI
  flags them as stale when the script changes. Assembly refuses to run when beats and voice come from
  different versions.
- **Claude.**
  - Model `claude-opus-5-5`, adaptive thinking.
  - Effort is `high` for scripts and `medium` for structured helpers.
  - Server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) is
    on by default (`config.yaml → claude.use_fallbacks`).
  - JSON outputs use `output_config.format` (json_schema).
  - Research uses `web_search_20260209`, with `pause_turn` continuation handled.
- **ElevenLabs.**
  - `POST /v1/text-to-speech/{voice}/with-timestamps`, model `eleven_v4` (10k-char limit; `eleven_multilingual_v2` still selectable).
  - The script is sent in paragraph-aligned chunks of ≤4,000 chars with `previous_text`/`next_text`.
  - Chunks are decoded to WAV and joined; timings are offset by measured chunk length.
  - Josh = `ZoiZ8fuDWInAcwPXaVeq` ("Josh - Warm, Smooth and Steady"). The health check verifies it and finds the voice by name if the ID changes.
- **Pause trimming.**
  - Gaps between words longer than `max_pause_s` (0.45 s) are cut from the middle of the silence, with
    8 ms fades at each splice.
  - Leading silence is trimmed to 0.12 s and the tail to 0.35 s.
  - Word timings are shifted to match.
- **Shots.**
  - A beat starts at `first_word.start − cut_lead_s` (beat 0 starts at frame 0) and ends where the next beat starts.
  - All times are snapped to frames.
  - A shot under 1 s merges into the shorter neighbour, preferring one in the same sentence. The image
    of the beat that contributed more frames is kept.
  - A shot over 5 s is split into ⌈d/5⌉ equal pieces alternating 1.0 / 1.15 zoom.
- **MP4.**
  - Pillow pre-renders each unique (image, zoom) frame at 1920×1080. Near-16:9 images fill the frame;
    others are padded.
  - Each shot is encoded with an exact `-frames:v` count, then concat-copied and muxed with AAC audio.
  - Picture length equals audio length plus the tail.
- **Image ordering.**
  - Sort key, first available:
    1. EXIF DateTimeOriginal/DateTime;
    2. PNG text "Creation Time";
    3. XMP CreateDate;
    4. C2PA `"when"`;
    5. file mtime;
    6. natural filename order.
  - Browser uploads restore the file's `lastModified` time, so the mtime fallback stays meaningful.
  - Near-identical timestamps (< 0.5 s apart) produce a warning.
- **Port.** The app runs on **8765**, because Docker Desktop holds 8000 on this machine.

## Log

### 2026-10-14: Pronounceable names, ASCII-only scripts

- ElevenLabs stumbles on rare or foreign names, so the script prompt now:
  - names only the 2-4 people the story follows; everyone else is a role ("the ship's doctor");
  - uses the easiest true form of a hard name (first name, surname, nickname or title), with the full name once at most;
  - describes hard place, ship and organization names instead of naming them, unless they matter;
  - never invents or alters real names.
- ASCII only. The prompt asks for it, and `script.to_ascii` enforces it:
  - curly quotes become straight; dashes become a comma pause; the ellipsis character becomes `...`;
  - accents are stripped (NFKD); £, €, ° and ½ are spelled out.

  It runs on generated scripts (`clean_script`), the `replace` text of AI chat edits, and beat text edits.
  Manual typing in the script editor is left as typed.
- Tests: 35 pass.

### 2026-10-14: Voice picker in preview

- `GET /api/settings/voices` lists the voices in the account (25 right now).
- The preview panel has a **Voice** dropdown, so you can A/B voices on the opening for a few hundred credits.
  **Use these settings** saves the voice ID and name along with the model and sliders.
- Candidate narrator: **"Davis - Casual Deeper American Male"** (`Z2fsAwk7IblvPhYzfslC`).
  - Use case: narrative/story. High quality on v4. Added by about 23k users. Already in the account.
  - Josh (`ZoiZ8fuDWInAcwPXaVeq`) is labelled "conversational".

### 2026-10-14: Voice quality, switch to Eleven v4

- The voice sounded odd. The configured "Josh" (`ZoiZ8fuDWInAcwPXaVeq`) is a professional voice clone,
  "Josh - Warm, Smooth and Steady", tuned by its creator for stability 0.73, similarity 1.0, style 0 and speed 0.86.
  We were sending stability 0.45, similarity 0.8 and style 0.35, far from what it was built for.
  - The old premade Josh ID `TxGEqnHWrfWFTfGW9XjX` now belongs to a different voice ("Craig"). Default ID and Settings help updated.
- Default model is now **Eleven v4** (`eleven_v4`), ElevenLabs' newest and highest-quality model. It is listed
  as high quality for this voice. Live-tested with one sentence:
  - with-timestamps works and the word count matches;
  - request ids come back, so stitching works;
  - it billed **34 credits for 84 characters**, about half the cost of v2.
- Eleven v3/v4 accept only stability and similarity, so style and speaker boost are sent only for older models
  (`voice.voice_settings`). Defaults: stability 0.5, similarity 0.9, style 0.
- The preview panel has a model picker (v4 vs Multilingual v2) and a similarity slider. The style slider shows only for v2.
- Not done yet: v4 audio tags (`[excited]`, `[whispers]`) for extra energy. `clean_script` strips square brackets,
  and tags would need excluding from word alignment.

### 2026-10-14: Voice preview

- New **Preview the voice** panel on the Voice step. It voices only the opening of the script (15/30/45/60 s;
  30 s is about 95 words and 520 characters) to `audio/preview.mp3`.
  - Style and stability sliders let you try settings for that preview only. **Use these settings** saves them to `config.yaml`.
  - No timings, trimming or DB rows: the full voice-over is unaffected.
- `voice.preview_text` runs on to the end of the sentence, or backs up to the last full sentence, and keeps
  paragraph breaks. `POST/GET /api/projects/{id}/voice/preview`.
- Tests: 33 pass. Route checked with a mocked ElevenLabs call (no credits used).

### 2026-10-14: Feedback from the first real run

- **First real voice-over** (Franklin video, 1,463 words): Josh reads at about **182 wpm**, not 160. The 8:01
  voice-over dropped to about 7:57 after pause trimming, which is under the 8:00 mid-roll minimum.
  - `wpm_estimate` is now 180.
  - Target length is now 1,550-1,650 words (~8.6-9.2 min).
  - The Script page reads the target and wpm from config instead of hard-coded values.
- **Script style.** The prompt now asks for:
  - language a 13-year-old can follow, with simple grammar;
  - an upbeat, enthusiastic storyteller tone;
  - smooth narration: sentences of 10-20 words, few commas, joining words instead of comma chains,
    no strings of fragments, no em dashes, semicolons or ellipses.

  Reason: the first script averaged 11.7 words per sentence and used many fragments, so the pauses
  at sentence ends (median 0.38 s) made it sound choppy.
- **Voice.**
  - Style raised from 0.15 to 0.35 for more energy. Stability stays at 0.45.
  - Chunks now use ElevenLabs request stitching (`previous_request_ids` from the `request-id` header),
    which continues the delivery across chunk seams. It falls back to `previous_text`.
- **Beats.** You can now edit a beat's text inline:
  - `PUT /beats/{idx}/text` rewrites those words in the script and saves a new version ("Edited beat #N").
  - Later beats shift; their ranges and image prompts are kept. The edited beat's prompt is dropped
    so it gets regenerated.
  - The voice is marked stale.
- **UI.** New turquoise colour scheme (light and dark), keeping green for completed steps. Also new hover and
  focus states.
- Tests: 32 pass (new ones cover beat text replacement and request stitching).

### 2026-10-09: Stage 10, Claude Code provider

- The user has Claude Pro, which doesn't include API keys, so all Claude steps can now run through the
  Claude Code CLI on their subscription.
- New `backend/pipeline/claude_code.py` mirrors the `Claude` client interface. Each call:
  - is a fresh headless session (`--no-session-persistence`) in an empty work dir (`data/claude_code_workdir`);
  - loads no settings files (`--setting-sources ""`);
  - has no tools, except `WebSearch`/`WebFetch` for research;
  - uses `--json-schema` for structured output (read from `structured_output`);
  - streams `stream-json` text deltas for the script.
- The prompt is sent on stdin. System prompts over 12k chars go into the prompt body to stay under
  the Windows command-line limit.
- `ANTHROPIC_API_KEY` is stripped from the subprocess environment. Otherwise Claude Code would bill
  the API instead of the subscription.
- `--bare` can't be used: it only accepts API keys, not the subscription login.
- Model is `opus` (Opus 5.5 confirmed available on this account), with `--fallback-model sonnet`.
- Research sources are parsed from the brief's Markdown links, since Claude Code returns text rather
  than search-result blocks.
- Pro usage-limit and login errors get readable messages.
- Live-tested on the user's account: idea suggestion (27 s for 3 ideas), streaming, a chat revision
  with valid find/replace edits, beat review, style guide, and scene prompts.
- 30 tests pass, including 6 new ones for the provider.
- Health check and the home-page setup warning are provider-aware. Settings has a provider dropdown.

### 2026-10-09: Stages 0–9 built

- Built the backend: 10 pipeline modules, 9 route modules, and a SQLite schema (`001_initial.sql`).
- Built the React UI: projects, ideas, settings, and a 7-step project wizard.
- Tests: 24 pytest tests pass. They cover scenes, voice (alignment, chunking, pause trimming), shots,
  image ordering, FCPXML, SRT, DB versions and staleness, plus an offline end-to-end render that
  checks the MP4 frame count against the shot plan.
- Browser check (Playwright) on a demo project with a synthetic voice and 9 images whose filenames
  were reversed relative to their embedded creation times:
  - the images were ordered correctly by metadata;
  - the render produced 10 shots with 1 punch-in;
  - picture/audio length difference was 0.000 s;
  - no console errors on any screen.
- Bugs found and fixed during the check:
  - the assemble route used the wrong DB key (`duration` → `duration_s`);
  - the Chat panel's scroll effect returned the Promise from Chromium's `scrollIntoView` to React as if
    it were a cleanup function, which crashed React's effect cleanup;
  - port 8000 is taken by Docker Desktop, so the app moved to 8765.
- Not yet verified (no API keys in this environment):
  - live Claude calls (ideas, research, script, revisions, beat review, prompts, publish);
  - the live ElevenLabs call;
  - DaVinci Resolve import of the FCPXML.

## Monetization checklist (also on the Publish step)

- YouTube Partner Program: 1,000 subscribers plus 4,000 public watch hours (or 10M Shorts views) for ad revenue.
- Avoid YouTube's **inauthentic / mass-produced content** problems:
  - original research and a varied story structure for each video;
  - your own editing in Resolve (music, sound effects, pacing);
  - never re-upload near-identical videos.
- Accuracy: keep the sources from the research brief in the description, and don't state rumors as fact.
- **ElevenLabs:** a paid plan is required for commercial use of generated voice.
- **Google Flow:** check the current terms for commercial use of generated images.
- No copyrighted music, footage, logos or real photos. Use royalty-free music in Resolve.
- Keep videos at **8:00 or longer** so mid-roll ad breaks are available (the script targets ~8.5 min).
- Upload `captions.srt`.
- YouTube's altered/synthetic content disclosure is needed only for realistic content that could
  be mistaken for real footage. Stick-figure art normally doesn't need it.
