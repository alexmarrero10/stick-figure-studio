"""Shared setup for the evals: keys from the root .env, the public site's own search and chat code,
Claude (through the studio's configured provider), the saved question sets and the reports."""
from __future__ import annotations

import atexit
import importlib.util
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evals" / "data"
REPORTS = ROOT / "evals" / "reports"
sys.path.insert(0, str(ROOT / "site" / "api"))
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

_site = None


def site():
    """The public site's app module (site/api/app.py), loaded under its own name so it doesn't clash with
    the studio's `app` package. The evals call its find_videos / gather / chat_contents directly, so they
    measure exactly what visitors get, without the visitor rate limits."""
    global _site
    if _site is None:
        spec = importlib.util.spec_from_file_location("site_app", ROOT / "site" / "api" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _site = mod
        atexit.register(_close_pool)
    return _site


def _close_pool() -> None:
    """Close the site's database pool before Python shuts down (otherwise it prints a harmless error)."""
    pool = getattr(_site.app.state.reader, "_pool", None) if _site else None
    if pool is not None:
        pool.close()


def studio_store():
    """The studio's vector store (research chunks), on the owner's database address."""
    from pipeline.vector_store import PgStore
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL is not set in .env (add it on the studio's Settings page).")
    return PgStore(url)


def claude():
    """Claude through the studio's configured provider (the Claude Code CLI on the Pro plan by default)."""
    from app.deps import claude as make
    return make()


def retry(fn: Callable[..., Any], *args: Any, tries: int = 6, wait: float = 15, **kwargs: Any) -> Any:
    """Call fn, waiting and retrying while Gemini's free tier says it's busy."""
    from gemini import GeminiError
    for n in range(tries):
        try:
            return fn(*args, **kwargs)
        except GeminiError as e:
            if str(e) != "busy" or n == tries - 1:
                raise
            print(f"    Gemini is busy, waiting {int(wait * (n + 1))} s")
            time.sleep(wait * (n + 1))


def answer(system: str, contents: list[dict[str, Any]]) -> str:
    return retry(lambda: "".join(site().gemini().stream_answer(system, contents)).strip())


def videos() -> list[dict[str, Any]]:
    """Every published video, with its project_key."""
    r = site().reader()
    return [r.get_video(v["id"]) for v in r.list_videos()]


def video_windows(video_id: int) -> list[dict[str, Any]]:
    with site().reader()._conn() as c:
        return c.execute("select id, ord, start_s, end_s, text from video_chunks where video_id = %s order by ord",
                         (video_id,)).fetchall()


def load(name: str) -> Any:
    f = DATA / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(name: str, data: Any) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def need_questions() -> dict[str, Any]:
    q = load("questions.json")
    if not q:
        sys.exit("No question set yet. Run first:  .venv\\Scripts\\python evals\\make_questions.py")
    return q


def report(layer: str, title: str, body: str, headline: dict[str, Any], details: Any) -> Path:
    """Save a Markdown report and the raw results, add the headline numbers to history.jsonl, print it."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    md = REPORTS / f"{stamp}_{layer}.md"
    md.write_text(f"# {title}\n\n_{datetime.now():%Y-%m-%d %H:%M}_\n\n{body}\n", encoding="utf-8")
    (REPORTS / f"{stamp}_{layer}.json").write_text(json.dumps(details, indent=2, ensure_ascii=False, default=str),
                                                   encoding="utf-8")
    with (REPORTS / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"when": stamp, "layer": layer, **headline}) + "\n")
    print(f"\n{body}\n\nSaved: {md}")
    return md
