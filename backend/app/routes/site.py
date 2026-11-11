"""Publish a finished video to the public site's database (Supabase), update it, or take it down."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, jobs
from app.deps import embedder, project_or_404, rag_config, rag_ready, vector_store
from pipeline import rag, site_publish

router = APIRouter(prefix="/api/projects/{project_id}/site", tags=["site"])


def _key(project_id: int) -> str:
    return rag.project_key(rag_config()["owner"], project_id)


def _view(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    saved = db.get_site_video(project_id) or {}
    meta = db.get_publish_meta(project_id) or {}
    voice = db.get_voiceover(project_id)
    youtube_url = saved.get("youtube_url") or db.get_short(project_id).get("youtube_url", "")
    published_at = saved.get("published_at") if saved.get("remote_id") else None
    return {
        "youtube_url": youtube_url,
        "youtube_id": site_publish.youtube_id(youtube_url),
        "title": saved.get("title") or (meta.get("titles") or [p["title"]])[0],  # the pack's suggested title
        "summary": saved.get("summary") or site_publish.default_summary(meta.get("description", "")),
        "title_options": meta.get("titles", []),
        "published": published_at is not None,
        "published_at": published_at,
        "chunks": saved.get("chunks", 0) if published_at else 0,
        # The voice was re-recorded after publishing: the site's timestamps are out of date.
        "stale": bool(published_at and voice and voice["created_at"] > published_at),
        "has_voice": voice is not None,
        "rag_ready": rag_ready(),
    }


class SiteBody(BaseModel):
    youtube_url: str = ""
    title: str = ""
    summary: str = ""


@router.get("")
def get_site(project_id: int) -> dict[str, Any]:
    return _view(project_id)


@router.put("")
def save_site(project_id: int, body: SiteBody) -> dict[str, Any]:
    project_or_404(project_id)
    db.save_site_video(project_id, youtube_url=body.youtube_url.strip(), title=body.title.strip(),
                       summary=body.summary.strip())
    return _view(project_id)


@router.post("/publish")
def publish(project_id: int, body: SiteBody) -> dict[str, Any]:
    """Save the fields, then upload the video's details and timed narration to the site database."""
    save_site(project_id, body)
    if not rag_ready():
        raise HTTPException(400, "Add the Gemini key and the Supabase database address on the Settings page first.")
    voice = db.get_voiceover(project_id)
    words = db.list_words(project_id)
    try:
        video = site_publish.build_video(db.get_site_video(project_id), db.get_publish_meta(project_id),
                                         voice["duration_s"] if voice else 0.0)
        if not words:
            raise ValueError("This video has no voiceover timings yet. Record the voice first.")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    store, embed, owner = vector_store(), embedder(), rag_config()["owner"]

    def work(progress):
        progress("Cutting the narration into timed passages and saving them", 0.2)
        vid, n = site_publish.publish(store, embed, _key(project_id), owner, video, words)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        db.save_site_video(project_id, remote_id=vid, chunks=n, published_at=now)
        return {"video_id": vid, "chunks": n}

    return jobs.start("site_publish", project_id, work)


@router.delete("/publish")
def unpublish(project_id: int) -> dict[str, Any]:
    """Take the video off the site (its research sources stay in the shared database)."""
    project_or_404(project_id)
    if not rag_ready():
        raise HTTPException(400, "Can't reach the site database: add the Supabase address on the Settings page.")
    vector_store().unpublish_video(_key(project_id))
    db.save_site_video(project_id, remote_id=None, chunks=0, published_at=None)
    return _view(project_id)
