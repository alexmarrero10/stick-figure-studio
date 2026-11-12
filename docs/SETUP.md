# Setting up Stick Figure Studio

How to install and run the studio on your own PC. For what the app does and how each step works, see the
[README](../README.md).

The studio is a local app: it runs on your computer and opens in your browser. Everything you make (scripts,
voice-overs, images, videos) stays on your PC.

## What you need

| | Needed? | Used for |
|---|---|---|
| Windows 10 or 11 | Yes | The start script is PowerShell |
| [Python 3.11+](https://www.python.org/downloads/) | Yes | The app's backend |
| [Node.js 20+](https://nodejs.org/) | Yes | Building the app's pages |
| FFmpeg on PATH | Yes | Rendering the video, the zoom and the voice speed-up. Install with `winget install Gyan.FFmpeg`, then reopen the terminal |
| Claude | Yes, one of the two | Research, script, beats, prompts and the publishing pack: **Claude Code** logged in with your Claude Pro or Max plan (the default; uses your plan's limits), or an **Anthropic API key** (billed per use) |
| [ElevenLabs](https://elevenlabs.io) API key | Yes | The voice-over. A paid plan is needed for commercial use |
| [Google Flow](https://labs.google/flow) | Yes | Making the pictures. You do this by hand; the app writes the prompts |
| [Gemini](https://aistudio.google.com) API key | Optional | Embeddings for research from downloaded sources (free tier) |
| [Supabase](https://supabase.com) project | Optional | The vector database for research from downloaded sources (free tier) |

Without Gemini and Supabase, research still works: Claude researches with web search instead.

Use your own accounts and keys for everything. Don't share a Supabase database address with anyone: it
contains the database password.

## 1. Get the code

```powershell
git clone https://github.com/alexmarrero10/stick-figure-studio.git
cd stick-figure-studio
```

## 2. Start the app

Double-click `start.bat`, or run:

```powershell
.\start.ps1              # http://127.0.0.1:8765, opens your browser
.\start.ps1 -Port 9000   # if something else already uses port 8765
.\start.ps1 -Dev         # for development: auto-reload, pages at http://localhost:5173
```

The first run takes a few minutes. It creates a Python environment (`.venv`), installs the packages, builds
the pages, and copies `.env.example` to `.env`, where your keys are kept.

Running it again restarts the app. If the app is in the middle of a job (research, voice, rendering...), it
doesn't restart, so the work isn't lost; it tells you to wait instead.

## 3. Add your keys

Open **Settings** in the app.

1. **Claude:** the provider is **Claude Code** by default, which uses your existing `claude` login. If
   you're logged out, run `claude` in a terminal once and log in. To use the API instead, pick
   **Anthropic API** and paste your Anthropic key.
2. **ElevenLabs:** paste your API key (elevenlabs.io, your profile, then API keys). You pick the voice
   later, on the Voice step.
3. **Channel name:** set the name shown under the pictures on your Shorts.

Keys are saved to `.env`, which is never committed to git.

## 4. Optional: research from downloaded sources (RAG)

This makes research download 10-15 real sources per story and write the brief from the best passages,
which uses far fewer Claude tokens (see [Research with RAG](../README.md#research-with-rag)).

1. **Gemini key:** create a free key at [aistudio.google.com](https://aistudio.google.com). Leave billing
   off on that Google project, so it can never cost money.
2. **Supabase:** create a free project at [supabase.com](https://supabase.com). In its dashboard, open
   **SQL Editor**, paste in [`backend/supabase/schema.sql`](../backend/supabase/schema.sql) and run it. It's
   safe to run again.
3. **Database address:** in Supabase, click **Connect**, choose **Session pooler**, and copy the URI. Put
   your database password into it.
4. In the app's **Settings**, paste the Gemini key and the Supabase address, turn on **Research from
   downloaded sources**, and click **Test Gemini and Supabase**.

## 5. Optional: your own public site

The studio's **Post to Video Site** step fills the database that the public site reads. To run or host your
own copy of the site, see [site/README.md](../site/README.md).

## Changing how it works

Every setting lives in `config.yaml`, and most of them are on the Settings page with a short explanation:
the Claude model and effort, script length, beat sizes, the voice and its speed, image batch size, shot
timing and zoom, video quality, the Short, and research. Changes apply right away, without a restart.

## Where your files are

```
data/app.db         the database: projects, script versions, beats, word timings, prompts...
projects/<name>/    each video's files: audio/, prompts/, images/batch_01/..., output/
.env                your keys
config.yaml         your settings
```

Each video's finished files are in `projects/<name>/output/`: `video.mp4`, `short.mp4`, `captions.srt` and
`timeline.fcpxml` (in DaVinci Resolve: **File > Import > Timeline**). None of these are committed to git.
To back everything up, copy `data/app.db`, the `projects/` folder, `.env` and `config.yaml`.

## Running the tests

From the repo root:

```powershell
cd backend; ..\.venv\Scripts\python -m pytest -q; cd ..   # backend tests (~12 s)
cd frontend; npm run test:e2e; cd ..                      # browser tests (~10 s)
```

The tests never touch your real database, keys or settings. More on what they cover:
[Testing and evals](../README.md#testing-and-evals).

## Troubleshooting

- **"FFmpeg not found":** install it with `winget install Gyan.FFmpeg`, then close and reopen the terminal.
- **Port 8765 is in use:** close the other program, or run `.\start.ps1 -Port 9000`.
- **Claude steps fail with a login error:** run `claude` in a terminal and log in again, or switch the
  provider to Anthropic API on the Settings page.
- **Research isn't using downloaded sources:** click **Test Gemini and Supabase** on the Settings page; it
  says which part is missing. Until both pass, research quietly falls back to web search.
