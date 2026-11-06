# NextDoorHistorian public site

A read-only website for the finished videos: a search bar that searches by meaning, a page per video with
the YouTube player, and a chatbot that answers questions about that video with clickable timestamps.

It reads what the studio's **Publish step → Your video site** puts in Supabase. It never writes anything.

- `api/`: FastAPI app (`app.py`) that serves the API and the built pages. `store.py` reads Supabase,
  `gemini.py` calls Gemini, `limits.py` holds the abuse limits and the answer cache.
- `web/`: React + Vite pages (search, video grid, watch page, chat sidebar).

## Run it on your PC

From the repo root (it reuses the studio's `.env` keys):

```powershell
cd site\web; npm install; npm run build; cd ..\..
.venv\Scripts\python.exe -m uvicorn app:app --app-dir site/api --port 8790
```

Open http://127.0.0.1:8790. For live editing of the pages, also run `npm run dev` in `site/web`
(http://localhost:5174).

Tests: `cd site/api && ../../.venv/Scripts/python -m pytest -q`

## Keeping it free and safe

- **Gemini key:** use a key from a Google project with **billing turned off**. The free tier then can only
  answer "too many requests", never send a bill.
- **Limits per visitor:** 10 questions an hour and 30 a day; 60 searches an hour and 300 a day. **Site-wide:**
  500 questions and 5,000 searches a day. Change them with the environment variables below.
- Repeated first questions are answered from a cache (no Gemini call). Questions are capped at 500
  characters, answers at about 500 tokens, and only the last 4 turns of a chat are sent.
- **Read-only database user:** run `backend/supabase/002_site_reader.sql` once in Supabase's SQL Editor
  (pick your own password first). The site connects as `site_reader`, which can only read.

## Put it online (Render, free)

Not done yet: do it once a video is published.

1. Push the repo to GitHub (the studio's `.env`, database and media are gitignored).
2. On render.com: **New → Web Service**, pick the repo, **Language: Docker**, **Root directory:** `site`,
   **Instance type:** Free.
3. **Environment variables:**
   - `GEMINI_API_KEY`: your free-tier key
   - `SITE_DATABASE_URL`: the Session pooler address with `site_reader.<project-ref>` and its password
   - optional: `CHAT_PER_HOUR`, `CHAT_PER_DAY`, `CHAT_GLOBAL_PER_DAY`, `SEARCH_PER_HOUR`, `SEARCH_PER_DAY`,
     `SEARCH_GLOBAL_PER_DAY`, `GEMINI_CHAT_MODEL` (default `gemini-flash-lite-latest`)
4. Deploy. Render gives a `https://<name>.onrender.com` address; a custom domain can be added later.

Free Render services sleep after 15 minutes without visitors, so the first visit after a quiet spell
takes about a minute to load. Fly.io also works with the same Dockerfile.
