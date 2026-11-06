# Stick Figure Studio

A local app that takes a true-story video from idea to a DaVinci Resolve timeline. It writes the
script with Claude, records the voice-over with ElevenLabs, writes Google Flow image prompts, and
cuts the pictures to the narration.

## Requirements

- Windows with **Python 3.11+**, **Node.js 20+**, and **FFmpeg** on PATH (`winget install Gyan.FFmpeg`)
- **Claude**: either **Claude Code** logged in with your Claude Pro/Max subscription (the default; no API key
  needed, but it uses your plan's usage limits), or an **Anthropic API key**. Choose on the Settings page.
- An **ElevenLabs API key** (a paid plan is needed for commercial use)

## Start

Double-click `start.bat`, or run:

```powershell
.\start.ps1          # http://127.0.0.1:8765, opens your browser
.\start.ps1 -Dev     # hot reload for development (UI at http://localhost:5173)
```

Running it again restarts the app: it stops the copy that's already running first. If that copy is in the
middle of a job (research, voice, assembly...), it doesn't stop it and tells you to wait.

The first run creates `.venv`, installs packages, builds the UI, and copies `.env.example` to `.env`.
Add your ElevenLabs key on the **Settings** page; it is saved to `.env`. With the default Claude Code
provider, Claude uses your existing `claude` login. If you're logged out, run `claude auth login` once.

## Workflow

1. **New video.** Ask Claude for ideas (optionally on a theme) or type your own. Save the ones you
   like for later. Choosing one creates a project.
2. **Script.**
   1. Click **Research the story** first. Claude searches the web and writes a fact sheet (timeline,
      people, turning points, what is disputed, sources). Fix anything wrong in it.
   2. Then click **Write script**. It streams in as narration only, with a cold-open hook and no intro,
      targeting 1,550-1,650 words (~8.5-9 min at Josh's ~180 wpm), in simple, upbeat language.
   3. Edit the text directly, or ask Claude for changes in the chat box. Each proposed edit is shown
      as a diff you accept or reject.
   4. Every save is kept in version history.
3. **Beats.** The narration is split into 0.5-3 second chunks at commas and sentence ends, and each one
   records its word range (e.g. words 112-121). Claude can review the boundaries for better pictures.
   Click a word to split a beat there, merge a beat into the next one, or edit a beat's text
   (this also updates the script).
4. **Voice.** Josh (ElevenLabs) reads the script with character timestamps, which become start and end
   times for every word. Long pauses are trimmed.
5. **Image prompts.**
   - Claude defines a series style and gives each recurring character a fixed visual marker.
   - It writes one prompt per beat, in batches of 24 (`projects/<slug>/prompts/batch_01.txt`, …).
   - Copy a batch into Google Flow and generate **one image per prompt, in order**.
6. **Images.**
   - Drop each batch's downloads onto the matching batch tab, or copy them into
     `projects/<slug>/images/batch_XX/` and click **Rescan**.
   - Images are ordered by the creation timestamp in their metadata (then file time, then name).
   - Check each picture against its narration and drag any that are out of order.
7. **Assemble.**
   - Each picture appears 0.08 s before its first word and holds until the next beat.
   - Shots under 0.5 s merge with a neighbour. Shots of 3 s or longer slowly zoom in.
   - Outputs go to `projects/<slug>/output/`:
     - `video.mp4`: preview render (1080p30, H.264 + AAC)
     - `timeline.fcpxml`: in Resolve, **File → Import → Timeline…**; every shot is its own clip on V1 and the voice is on A1
     - `captions.srt`: upload to YouTube
     - `short.mp4`: the vertical Short (1080×1920), the opening up to the best cliffhanger between 50 and 70 s,
       with your channel name under the pictures. Download it and upload it yourself.
8. **Publish.** Title options, a description with chapters and sources, tags and thumbnail prompts. The general tags from Settings (animation, history, education, …)
   are added to every video's tags.

Video types: a project is **one story**, a **topic explained** (e.g. how Blitzkrieg worked), or a
**countdown list** (e.g. top 5 Navy pilot UFO encounters). Pick it at the top of the Script step before
researching. Every project can be archived from the home page; only archived projects can be deleted.

## Tuning

Everything is in `config.yaml`, and most of it is on the Settings page:
- Claude model and effort;
- script length;
- beat sizes;
- voice settings and pause trimming;
- batch size;
- cut lead, minimum and maximum shot length, and punch-in zoom;
- frame rate and quality.

## Project layout

```
backend/app/        FastAPI app, SQLite access (db.py), routes, migrations
backend/pipeline/   one module per step: ideas, script, scenes, beat_review, voice, prompts,
                    images, shots, assemble, fcpxml, captions, publish
backend/tests/      pytest suite (run: .venv\Scripts\python -m pytest backend\tests)
frontend/src/       React UI (one component per step in steps/)
data/app.db         SQLite database (scripts, versions, beats, timings, prompts, …)
projects/<slug>/    audio, prompts, images and outputs for each video
PROGRESS.md         stage checklist and development notes
```

Back up by copying `data/app.db` and the `projects/` folder.
