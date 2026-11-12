# Public video site

A read-only website for the finished videos: a search bar that searches by meaning, a page per video with
the YouTube player, and a chatbot that answers questions about that video with clickable timestamps.

It reads what the studio's **Post to Video Site** step (step 7) puts in Supabase. It never writes anything.

- `server/`: FastAPI app (`app.py`) that serves the API and the built pages. `store.py` reads Supabase,
  `gemini.py` calls Gemini, `limits.py` holds the abuse limits and the answer cache.
- `web/`: React + Vite pages (search, video grid, watch page, chat sidebar).
- `index.py`, `vercel.json`, `requirements.txt`: hosting on Vercel. `Dockerfile`: hosting anywhere else.
  (The app folder is `server/`, not `api/`, because Vercel turns every file in an `api/` folder into its
  own function.)

## Run it on your PC

From the repo root (it reuses the studio's `.env` keys):

```powershell
cd site\web; npm install; npm run build; cd ..\..
.venv\Scripts\python.exe -m uvicorn app:app --app-dir site/server --port 8790
```

Open http://127.0.0.1:8790. For live editing of the pages, also run `npm run dev` in `site/web`
(http://localhost:5174).

Tests: `cd site/server && ../../.venv/Scripts/python -m pytest -q`

## Keeping it free and safe

- **Gemini key:** use a key from a Google project with **billing turned off**. The free tier then can only
  answer "too many requests", never send a bill.
- **Limits per visitor:** 10 questions an hour and 30 a day; 60 searches an hour and 300 a day. **Site-wide:**
  500 questions and 5,000 searches a day. Change them with the environment variables below.
- **Off-topic questions are turned away for free.** Each question is compared with the video's narration
  and sources (using the free embedding). Below `CHAT_MIN_SIMILARITY` (0.55; real questions score
  0.58-0.77, recipes, code and "ignore your rules" 0.46-0.56) it replies "I can only answer questions about
  this video" without asking Gemini to write anything.
- **Rules and filters:** the instructions treat visitors' text as questions only (no role-play, no
  revealing instructions), and Google's safety filter blocks hateful, sexual, harassing and dangerous
  answers (medium level, so history's wars and crimes stay discussable).
- **Keys can't leak:** the model only ever sees the instructions, narration and source passages. Keys stay
  in the server's environment, the Gemini key goes in a request header (never a URL), errors shown to
  visitors are generic, and the database user can only read.
- Repeated first questions are answered from a cache (no Gemini call). Questions are capped at 500
  characters, answers at about 500 tokens, and only the last 4 turns of a chat are sent.
- **Read-only database user:** run `backend/supabase/002_site_reader.sql` once in Supabase's SQL Editor
  (pick your own password first). The site connects as `site_reader`, which can only read.

## Put it online (Vercel, free)

Not done yet. Nothing is deployed until you do these steps.

1. Push the repo to GitHub (the studio's `.env`, database and media are gitignored).
2. On vercel.com: **Add New → Project**, import the repo, and set **Root Directory** to `site`.
   `vercel.json` sets up two Vercel services: `server` (the FastAPI app, `index.py`) gets `/api/...`, and
   `web` (the pages, built with Vite and served from Vercel's CDN) gets everything else. No bindings: the
   pages call `/api/...` from the visitor's browser.
3. **Environment variables** (Project → Settings → Environment Variables):
   - `GEMINI_API_KEY`: your free-tier key (billing off)
   - `SITE_DATABASE_URL`: the Supabase pooler address with `site_reader.<project-ref>` and its password.
     The **Transaction pooler** (port 6543) suits Vercel best; the Session pooler (5432) also works.
   - optional: `CHAT_PER_HOUR`, `CHAT_PER_DAY`, `CHAT_GLOBAL_PER_DAY`, `SEARCH_PER_HOUR`, `SEARCH_PER_DAY`,
     `SEARCH_GLOBAL_PER_DAY`, `CHAT_MIN_SIMILARITY`, `GEMINI_CHAT_MODEL` (default `gemini-flash-lite-latest`)
4. Deploy. You get a `https://<name>.vercel.app` address; a custom domain can be added later.

Or from your PC: `npm i -g vercel`, then in `site/`: `vercel` (it asks you to log in and link a project),
`vercel env add GEMINI_API_KEY`, `vercel env add SITE_DATABASE_URL`, then `vercel --prod`.

Good to know on Vercel:
- The visitor limits are kept in memory, and Vercel runs the app on several short-lived instances, so the
  counts reset more often than on one server. The real cost guard is still the Gemini key with billing
  off: it can only say "too many requests", never bill.
- No sleeping: the first visit after a quiet spell takes a second or two, not a minute.

## Other hosts (Render, Fly.io)

The `Dockerfile` builds the same site as one container. On render.com: **New → Web Service**, pick the repo,
**Language: Docker**, **Root directory:** `site`, **Instance type:** Free, and the same environment
variables as above (use the Session pooler address). Free Render services sleep after 15 minutes without
visitors, so the first visit after a quiet spell takes about a minute.
