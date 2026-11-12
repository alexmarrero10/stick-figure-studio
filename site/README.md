# Public video Site

**Stick Figure Viewer** (https://stick-figure-viewer.vercel.app) is the read-only website for the finished
videos: search by meaning, a page per video with the YouTube player, and a chatbot that answers questions
about each video with clickable timestamps. It shows what the studio's **Post to Video Site** step puts in
Supabase, and never writes anything.

How it works (search, the chatbot, guard rails, hosting and tests) is in
[docs/PUBLIC_SITE.md](../docs/PUBLIC_SITE.md). This page is how to run and host it.

## Folders

- `server/`: the FastAPI app. `app.py` serves the API and the pages, `store.py` reads Supabase, `gemini.py`
  calls Gemini, `limits.py` holds the rate limits and the answer cache.
- `web/`: the React + Vite pages.
- `index.py`, `vercel.json`, `requirements.txt`: hosting on Vercel. `Dockerfile`: hosting anywhere else.
  The app folder is `server/`, not `api/`, because Vercel turns every file in an `api/` folder into its own
  function.

The site doesn't import the studio's code, so it can be deployed on its own.

## Before you start

You need the studio set up with research from downloaded sources (Gemini key and Supabase database, see
[docs/SETUP.md](../docs/SETUP.md)), and at least one video posted with **Post to Video Site**.

1. **Read-only database user:** open `backend/supabase/002_site_reader.sql`, replace the password with your
   own, and run it once in Supabase's SQL Editor. The site connects as `site_reader`, which can only read.
2. **Gemini key:** use a key from a Google project with **billing turned off**. The free tier can then only
   answer "too many requests", never send a bill.

## Run it on your PC

From the repo root (it reads the studio's `.env`):

```powershell
cd site\web; npm install; npm run build; cd ..\..
.venv\Scripts\python.exe -m uvicorn app:app --app-dir site/server --port 8790
```

Open http://127.0.0.1:8790. For live editing of the pages, also run `npm run dev` in `site/web`
(http://localhost:5174).

Tests: `cd site/server && ../../.venv/Scripts/python -m pytest -q`

## Settings (environment variables)

| Variable | What it is |
|---|---|
| `GEMINI_API_KEY` | Your Gemini key (billing off) |
| `SITE_DATABASE_URL` | Supabase pooler address with the user `site_reader.<project-ref>` and its password. On your PC it falls back to the studio's `SUPABASE_DB_URL` if unset |
| `CHAT_PER_HOUR`, `CHAT_PER_DAY`, `CHAT_GLOBAL_PER_DAY` | Chat limits per visitor and site-wide (default 10, 30, 500) |
| `SEARCH_PER_HOUR`, `SEARCH_PER_DAY`, `SEARCH_GLOBAL_PER_DAY` | Search limits (default 60, 300, 100) |
| `CHAT_MIN_SIMILARITY`, `SEARCH_MIN_SIMILARITY` | Relevance cutoffs (default 0.55 and 0.6) |
| `GEMINI_CHAT_MODEL` | Chat model (default `gemini-flash-lite-latest`) |

## Host it on Vercel (free)

1. Push the repo to GitHub. The studio's `.env`, database and media are gitignored.
2. On vercel.com: **Add New > Project**, import the repo, and set **Root Directory** to `site`.
   `vercel.json` sets up two services: `server` (the FastAPI app) answers `/api/...`, and `web` (the pages,
   served from Vercel's CDN) answers everything else.
3. Under **Settings > Environment Variables**, add `GEMINI_API_KEY` and `SITE_DATABASE_URL`. The
   **Transaction pooler** address (port 6543) suits Vercel best; the Session pooler (5432) also works.
4. Deploy. Every push to `main` redeploys it. A custom `*.vercel.app` name or your own domain can be set
   under **Settings > Domains**.

Rate-limit counts are kept in memory, and Vercel runs several short-lived copies of the app, so they reset
more often than on one server. The real cost guard is the Gemini key with billing off.

## Other hosts (Render, Fly.io)

The `Dockerfile` builds the same site as one container. On render.com: **New > Web Service**, pick the repo,
**Language:** Docker, **Root directory:** `site`, and the same environment variables (use the Session pooler
address). Free Render services sleep after 15 minutes without visitors, so the first visit after that takes
about a minute.
