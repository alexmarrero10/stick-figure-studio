# Stick Figure Studio

A local web app that takes a true-history story from idea to finished video for the user's YouTube channel
**NextDoorHistorian** (narrated stick-figure explainers, ~8.5-9 min, plus vertical Shorts).
Single user, runs on their Windows PC. Not deployed anywhere.

Current status, recent work and open issues are in **NOTES.md**. Read it at the start of a session.
`PROGRESS.md` holds the older stage-by-stage build log and architecture notes; `docs/PUBLIC_SITE_PLAN.md`
is a parked plan for a public video library with RAG Q&A.

## Pipeline (one step per UI tab, one module per step)

1. **Ideas** (`ideas.py`): Claude suggests topics or the user types one. Choosing one creates a project.
   Formats: one story, topic explained, countdown list.
2. **Script** (`script.py`): research brief with web search, then a streamed script (target 1,550-1,650
   words). Chat revisions are shown as find/replace diffs the user accepts or rejects. Every save is a version.
   The style rules live in `SCRIPT_SYSTEM` (see "Script style" below).
3. **Beats** (`scenes.py`, `beat_review.py`): split into 2-13 word picture chunks; Claude can review the
   boundaries; manual split/merge/edit with undo.
4. **Voice** (`voice.py`): ElevenLabs with-timestamps (voice "Josh", `eleven_v4`), chunked and stitched,
   long pauses trimmed, per-word timings stored.
5. **Image prompts** (`prompts.py`): style guide, cast/characters/props/places, one prompt per beat in batches
   of 24. The user generates the images **manually in Google Flow** and uploads them.
6. **Images** (`images.py`): import, ordered by metadata timestamp, then drag or slot-pick to fix.
7. **Shots + Assemble** (`shots.py`, `assemble.py`, `fcpxml.py`, `captions.py`): shots locked to word timings,
   FFmpeg renders `output/video.mp4`, plus `timeline.fcpxml` and `captions.srt`. Shots of 3 s or longer
   slowly zoom in (`video.zoom_min_seconds`, `video.zoom_per_second`, capped at 12%).
8. **Publish** (`publish.py`): titles, description with chapters and sources, tags, thumbnail prompts.
9. **Short** (`shorts.py`, `social/`): 50-70 s vertical cut ending on the best cliffhanger; captions written
   by Claude; can post to YouTube Shorts, Instagram/Facebook Reels and TikTok.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, SQLite (raw `sqlite3`, numbered SQL migrations), Pillow,
  httpx, PyYAML, python-dotenv. FFmpeg on PATH does all rendering.
- **Frontend:** React 18 + TypeScript + Vite 5. No UI library, no router library, plain CSS (`styles.css`).
- **Claude:** two providers with the same interface (`stream_text` / `complete` / `json`):
  - `claude_code` (default): runs the local `claude -p` CLI on the user's **Claude Pro subscription**.
    The user has no API key. `ANTHROPIC_API_KEY` is stripped from the subprocess env so it never bills the API.
    Models are aliases `fable` / `opus` (default) / `sonnet` (fallback) / `haiku`.
  - `api`: Anthropic SDK with `ANTHROPIC_API_KEY`; IDs `claude-fable-5-1`, `claude-opus-5-5` (default),
    `claude-sonnet-5-5`, `claude-haiku-5-5`.
- **ElevenLabs** for voice. **Google Flow** for images (manual, by the user).

## Run, build, test

All commands from the project root (Windows; PowerShell or Git Bash).

- **Start the app:** `.\start.ps1` (builds the UI if needed, serves http://127.0.0.1:8765). `.\start.ps1 -Dev`
  runs backend reload + Vite at http://localhost:5173. Port 8765, because Docker Desktop holds 8000.
- **Start just the server** (what Claude usually does), minimized, from the project root:
  `.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765`
- **Before restarting the server**, check for running jobs: `GET /api/jobs?project_id=N`. Never kill a running job.
- **Config changes don't need a restart:** `PUT /api/settings/config` with `{"section": {"key": value}}`.
  `GET /api/settings` returns `{config: ...}`.
- **Backend tests:** `cd backend && ../.venv/Scripts/python -m pytest -q` (129 passing as of 2026-11-06,
  ~12 s). They also run the small Node test `frontend/src/textarea.test.ts`.
- **Frontend build / type check:** `cd frontend && npm run build`. The served UI is `frontend/dist`, so
  rebuild after frontend changes.
- Shell notes: `bc` isn't available in Git Bash. Use PowerShell `Measure-Command` for timing. Prefer the
  Edit tool over heredoc/sed for multi-line edits (heredocs have mangled text before).

## Folder structure

```
backend/app/            FastAPI app: main.py, config.py (config.yaml + .env), db.py, jobs.py (background
                        jobs with stop), storage.py, routes/ (one file per step), migrations/ (001-009 .sql)
backend/pipeline/       one module per step (see Pipeline), claude_client.py (API), claude_code.py (CLI),
                        ffmpeg.py, procs.py, social/ (youtube, meta, tiktok)
backend/tests/          pytest suite + fixtures/
frontend/src/           App.tsx, api.ts, types.ts, components.tsx, styles.css, steps/ (one .tsx per step,
                        plus Home, Settings, SocialAccounts), aiTells.ts, textarea.ts
config.yaml             all tunables; most are on the Settings page (frontend/src/steps/Settings.tsx FIELDS)
.env                    API keys and social tokens (gitignored)
data/app.db             SQLite DB (gitignored). Tables: projects, ideas, research_briefs, script_versions,
                        revision_messages, beats, beat_undo, voiceovers, words, style_guides, image_prompts,
                        prompt_batches, images, shots, publish_meta, shorts, social_posts
projects/<slug>/        per-video media: audio/, prompts/, images/batch_XX/, output/ (gitignored)
channel_model_transcripts.txt   other channels' transcripts the script style was distilled from.
                        Untracked on purpose; not read at runtime.
```

## Key invariants

- **Word indices are the contract.** Word *i* = `script_text.split()[i]`. Beats store `word_start`/`word_end`
  (inclusive); voice timings map onto the same indices.
- **Staleness:** beats and voice store the `script_version_id` they came from. Assembly refuses mismatches.
- **Frame-exact video:** every shot is encoded with an exact frame count, so picture stays locked to the words.
  Zoom uses FFmpeg `zoompan` on a 2x-upscaled frame and must keep the exact frame count. Shorts don't zoom.
- Scripts are ASCII only (`script.to_ascii`) and avoid hard-to-pronounce names (ElevenLabs stumbles).

## Script style (in `script.py` SCRIPT_SYSTEM; REVISE_SYSTEM inherits it)

Modeled on top channels in the niche, distilled from `channel_model_transcripts.txt`. **Distill patterns, never
copy text.** Rules: put the viewer inside the scene (second person, present tense, senses); then vs now in the
viewer's terms; name the common belief then break it; a trackable shape (frame announced early, each problem
hands off to the next); evidence as mini-stories, then answer the viewer's doubt; planted callbacks; 2-3 direct
questions; honest about uncertainty; occasional dry aside; land it with a "So here's the full picture." recap,
back to the opening scene, ending on a resonant line or one comment question. No subscribe asks or "thanks for
watching". Tone: confident, curious storyteller talking to one viewer, never sarcastic or flat. Simple language
(a 13-year-old can follow), sentences of 10-20 words, no em dashes/semicolons/ellipses. The script must answer
who/what/when/where/why for a newcomer.

## Coding conventions

- Keep it simple and local: plain functions, small modules, no new frameworks or dependencies unless needed.
- Pipeline modules hold the logic and are testable without the server; routes stay thin.
- Long steps run as background jobs (`app/jobs.py`) with progress messages and a Stop button. FFmpeg and Claude
  subprocesses must stop when the job stops (contextvars are copied into worker threads for this).
- Schema changes go in a new numbered migration in `backend/app/migrations/`. Never edit an applied one.
- New tunables go in `config.yaml` with a code default (`cfg.get("key", default)`) and, if user-facing, a field
  in `Settings.tsx` FIELDS with a short plain-language label and help text.
- UI text and docs: plain, short, friendly language. No jargon.
- Add or update tests with every change. Tests use `temp_db` / `tmp_path` and mock network calls.
- Commit messages: one short plain sentence saying what changed for the user (e.g. "Zoom in on shots of 3 s
  or more"), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Keep `NOTES.md` current at the end of each piece of work.

## Always / never (from the user)

- **Never print or echo API keys or tokens.** Keys live only in `.env`; the user sets them on the Settings page.
- **Tests must never write the real `.env` or `config.yaml`** (or the real `data/app.db`).
- **Never send the user's email anywhere.** Git commits use the GitHub noreply address.
- **Confirm before anything outward-facing.** No real social posting, uploads or account actions without an
  explicit go-ahead.
- **Push only when asked.** Commit locally as work is finished; check `git show --stat` before committing so no
  unrelated file is added or deleted (a commit once deleted `docs/PUBLIC_SITE_PLAN.md` by accident).
- **Never kill running jobs** when restarting the server.
- **No Google Flow browser automation** unless the user confirms it for that task.
- **Don't build:** YouTube draft upload, a character sheet feature, or image filename-based matching.
- Don't commit `channel_model_transcripts.txt` (other channels' content).
- Leave the user's own uncommitted `config.yaml` edits alone unless asked.
- When the user says they're just brainstorming ("don't execute anything"), only discuss.
- Keep answers short and direct; the user asks for shorter replies when they get long.
