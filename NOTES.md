# Notes: current state (updated 2026-11-06)

Read CLAUDE.md first for how the project works and the rules. This file is what's happening now.

## Where things stand

- The full pipeline works end to end and has made two real videos (both format "story"):
  1. **Project 1:** "The Inuit Knew Where Franklin's Lost Ships Were. No One Listened" (151 shots)
  2. **Project 2:** "How a Hand-Drawn Family Tree Found Saddam in a Hole" (238 shots)
- Channel problem being worked on: **low retention.** Average view duration is about 25% on long videos and
  about 65% on Shorts, and views are low. Recent work targets this.
- 152 backend tests pass; the frontend builds.
- Active plan: `docs/PUBLIC_SITE_PLAN.md` (RAG research built; public site with chatbot next).

## Recently done

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

1. User: publish projects 1 and 2 on the site (Publish step, paste their YouTube links), run
   `backend/supabase/002_site_reader.sql`, then deploy per `site/README.md` (needs a push to GitHub first).
2. Finish project 3 ("The Piece of Tape...", researched with RAG) with the new script style and zoom, then
   compare its retention with the first two.
3. Possibly re-assemble projects 1 and 2 to see the zoom (only if the user wants new versions).
4. Push to GitHub when the user asks (`alexmarrero10/stick-figure-studio`, private). Many local commits are
   unpushed (`git log origin/main..main`).

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
