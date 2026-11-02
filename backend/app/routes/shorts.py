"""The vertical Short made from the start of the video, its text, and posting it to every app."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, project_or_404
from app.routes import social
from app.routes.assemble import _plan
from app.routes.projects import rel
from app.storage import output_dir
from pipeline import shorts
from pipeline.social import SocialError

router = APIRouter(prefix="/api/projects/{project_id}/short", tags=["shorts"])


def _cfg() -> dict[str, Any]:
    cfg = load_config()
    return {**{"max_seconds": 59, "channel_name": ""}, **cfg.get("shorts", {})}


def _file(p: dict[str, Any]) -> Path:
    return output_dir(p["slug"]) / "short.mp4"


def _opening_text(project_id: int, seconds: float) -> str:
    return " ".join(w["text"] for w in db.list_words(project_id) if w["start"] < seconds)


@router.get("")
def get_short(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    cfg = _cfg()
    f = _file(p)
    short = db.get_short(project_id)
    meta = db.get_publish_meta(project_id)
    return {
        "short": short,
        "video": ({"url": f"/api/projects/{project_id}/file?path={rel(p, f)}", "modified": f.stat().st_mtime,
                   "size": f.stat().st_size} if f.exists() and short["rendered_at"] else None),
        "posts": db.list_social_posts(project_id),
        "connected": {pl: social.connected(pl) for pl in shorts.PLATFORMS},
        "channel_name": cfg["channel_name"],
        "max_seconds": cfg["max_seconds"],
        "opening_text": _opening_text(project_id, float(cfg["max_seconds"])),
        "previews": {pl: shorts.platform_text(short, pl) for pl in shorts.PLATFORMS},
        "full_titles": meta["titles"] if meta else [],
    }


class ShortEdit(BaseModel):
    title: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    youtube_url: str | None = None


@router.put("")
def edit_short(project_id: int, body: ShortEdit) -> dict[str, Any]:
    project_or_404(project_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "hashtags" in fields:
        fields["hashtags"] = shorts.clean_hashtags(fields["hashtags"])
    if "youtube_url" in fields:
        url = fields["youtube_url"].strip()
        if url and not url.startswith(("https://youtu.be/", "https://www.youtube.com/", "https://youtube.com/")):
            raise HTTPException(400, "Paste the full video's YouTube link, e.g. https://youtu.be/abc123")
        fields["youtube_url"] = url
    db.save_short(project_id, **fields)
    return get_short(project_id)


@router.post("/text")
def write_text(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    opening = _opening_text(project_id, float(_cfg()["max_seconds"]))
    if not opening:
        raise HTTPException(400, "Record the voice-over first")
    meta = db.get_publish_meta(project_id)
    res = shorts.write_text(claude(), meta["titles"][0] if meta else p["title"], opening)
    db.save_short(project_id, title=res["title"], caption=res["caption"], hashtags=res["hashtags"])
    return get_short(project_id)


@router.post("/render")
def render(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    cfg = load_config()
    scfg = _cfg()
    if not scfg["channel_name"].strip():
        raise HTTPException(400, "Set your channel name on the Settings page first; it is shown under the pictures.")
    plan = _plan(project_id)
    voice = db.get_voiceover(project_id)
    out = _file(p)

    def work(progress):
        res = shorts.render(plan["shots"], Path(voice["audio_path"]), out, cfg["video"], scfg,
                            output_dir(p["slug"]) / "_short_work", progress)
        db.save_short(project_id, rendered_at=time.strftime("%Y-%m-%d %H:%M:%S"), duration_s=res["duration"])
        return res

    return jobs.start("short", project_id, work)


class PublishBody(BaseModel):
    platforms: list[str]
    again: bool = False  # post to apps that already have this render


@router.post("/publish")
def publish(project_id: int, body: PublishBody) -> dict[str, Any]:
    p = project_or_404(project_id)
    short = db.get_short(project_id)
    f = _file(p)
    if not short["rendered_at"] or not f.exists():
        raise HTTPException(400, "Make the Short first")
    if not short["youtube_url"]:
        raise HTTPException(400, "Paste the full video's YouTube link first; it goes in every description.")
    if not short["title"].strip() or not short["caption"].strip():
        raise HTTPException(400, "Write the title and caption first")
    platforms = [pl for pl in shorts.PLATFORMS if pl in body.platforms]
    if not platforms:
        raise HTTPException(400, "Choose at least one app")
    missing = [pl for pl in platforms if not social.connected(pl)]
    if missing:
        raise HTTPException(400, f"Connect {', '.join(m.title() for m in missing)} on the Settings page first")
    done_before = {x["platform"] for x in db.list_social_posts(project_id)
                   if x["status"] == "posted" and x["rendered_at"] == short["rendered_at"]}
    meta = db.get_publish_meta(project_id)
    tags = (meta or {}).get("tags", [])

    def work(progress):
        results = []
        for n, pl in enumerate(platforms):
            if pl in done_before and not body.again:
                results.append({"platform": pl, "status": "skipped", "error": "Already posted"})
                continue
            progress(f"Posting to {pl.title()} ({n + 1} of {len(platforms)})", n / len(platforms))
            text = shorts.platform_text(short, pl)
            try:
                with social.http() as c:
                    res = social.post_video(c, pl, f, text["title"], text["text"], tags)
                results.append(db.add_social_post(project_id, pl, "posted", res["post_id"], res["url"],
                                                  rendered_at=short["rendered_at"]))
            except (SocialError, Exception) as e:  # one app failing must not stop the others
                results.append(db.add_social_post(project_id, pl, "error", error=str(e),
                                                  rendered_at=short["rendered_at"]))
        return results

    return jobs.start("short_publish", project_id, work)
