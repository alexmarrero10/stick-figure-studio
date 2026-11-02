from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import elevenlabs_key, project_or_404
from app.routes.projects import rel
from app.storage import audio_dir
from pipeline import voice

router = APIRouter(prefix="/api/projects/{project_id}/voice", tags=["voice"])


@router.post("")
def generate(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    script = db.current_script(project_id)
    if not script:
        raise HTTPException(400, "Write the script first")
    key = elevenlabs_key()
    cfg = load_config()["voice"]

    def work(progress):
        res = voice.generate(script["text"], audio_dir(p["slug"]), key, cfg, progress)
        db.save_voiceover(project_id, script["id"], res["audio_path"], res["duration"], res["words"], res["warnings"])
        return {"duration": res["duration"], "warnings": res["warnings"]}

    return jobs.start("voice", project_id, work)


class PreviewBody(BaseModel):
    seconds: float = 30
    stability: float | None = None
    style: float | None = None
    model_id: str | None = None
    voice_id: str | None = None


def _preview_info(p: dict[str, Any], project_id: int) -> dict[str, Any] | None:
    mp3 = audio_dir(p["slug"]) / "preview.mp3"
    if not mp3.exists():
        return None
    return {"audio_url": f"/api/projects/{project_id}/file?path={rel(p, mp3)}&t={int(mp3.stat().st_mtime)}"}


@router.post("/preview")
def make_preview(project_id: int, body: PreviewBody) -> dict[str, Any]:
    """Voice just the opening (~30 s) to check tone before spending credits on the full script."""
    p = project_or_404(project_id)
    script = db.current_script(project_id)
    if not script:
        raise HTTPException(400, "Write the script first")
    cfg = dict(load_config()["voice"])
    for k in ("stability", "style"):
        v = getattr(body, k)
        if v is not None:
            cfg[k] = min(1.0, max(0.0, v))
    if body.model_id:
        cfg["model_id"] = body.model_id
    if body.voice_id:
        cfg["voice_id"] = body.voice_id
    wpm = load_config()["script"]["wpm_estimate"]
    text = voice.preview_text(script["text"], min(max(body.seconds, 5), 90), wpm)
    dur = voice.preview(text, audio_dir(p["slug"]) / "preview.mp3", elevenlabs_key(), cfg)
    return {**_preview_info(p, project_id), "text": text, "chars": len(text), "duration": round(dur, 2),
            "stability": cfg["stability"], "style": cfg["style"], "model_id": cfg["model_id"], "voice_id": cfg["voice_id"]}


@router.get("/preview")
def get_preview(project_id: int) -> dict[str, Any] | None:
    return _preview_info(project_or_404(project_id), project_id)


@router.get("")
def get_voice(project_id: int) -> dict[str, Any] | None:
    p = project_or_404(project_id)
    v = db.get_voiceover(project_id)
    if not v:
        return None
    script = db.current_script(project_id)
    mp3 = audio_dir(p["slug"]) / "voice.mp3"
    return {
        **v,
        "audio_url": f"/api/projects/{project_id}/file?path={rel(p, mp3)}" if mp3.exists() else None,
        "stale": script is not None and script["id"] != v["script_version_id"],
        "word_count": len(db.list_words(project_id)),
        "chars": len(script["text"]) if script else 0,
    }


@router.get("/words")
def words(project_id: int) -> list[dict[str, Any]]:
    project_or_404(project_id)
    return db.list_words(project_id)
