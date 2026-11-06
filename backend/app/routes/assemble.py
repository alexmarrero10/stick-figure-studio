from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, project_or_404
from app.routes.images import beat_image_map
from app.routes.projects import rel
from app.storage import output_dir
from pipeline import assemble, captions, fcpxml, procs, publish, shorts, shots as shots_mod

router = APIRouter(prefix="/api/projects/{project_id}", tags=["assemble"])


def _plan(project_id: int) -> dict[str, Any]:
    beats = db.list_beats(project_id)
    words = db.list_words(project_id)
    voice = db.get_voiceover(project_id)
    if not beats or not voice or not words:
        raise HTTPException(400, "Beats and voice-over are required")
    if voice["script_version_id"] != beats[0]["script_version_id"]:
        raise HTTPException(400, "The voice-over and beats come from different script versions. "
                                 "Rebuild the beats or regenerate the voice.")
    cfg = load_config()
    images = beat_image_map(project_id)
    plan = shots_mod.build_shots(beats, words, images, voice["duration_s"], cfg["shots"], cfg["video"]["fps"])
    plan["missing_images"] = [b["idx"] for b in beats if b["idx"] not in images]
    return plan


def short_cfg() -> dict[str, Any]:
    return {**{"min_seconds": 50, "max_seconds": 70, "channel_name": ""}, **load_config().get("shorts", {})}


def stored_cut(project_id: int) -> float | None:
    """Where the Short ends, if it was chosen for the current voice-over."""
    short, cfg = db.get_short(project_id), short_cfg()
    words = db.list_words(project_id)
    if words and short["cut_s"] is not None and short["cut_key"] == shorts.cut_key(words, float(cfg["max_seconds"])):
        return short["cut_s"]
    return None


def _cut(project_id: int) -> float:
    """Where the Short ends: chosen once per voice-over (at the best cliffhanger in the window), then kept."""
    cut = stored_cut(project_id)
    if cut is None:
        cfg = short_cfg()
        words = db.list_words(project_id)
        cut = shorts.choose_cut(claude(), words, float(cfg["min_seconds"]), float(cfg["max_seconds"]))
        db.save_short(project_id, cut_s=cut, cut_key=shorts.cut_key(words, float(cfg["max_seconds"])))
    return cut


@router.get("/shots/preview")
def preview(project_id: int) -> dict[str, Any]:
    project_or_404(project_id)
    plan = _plan(project_id)
    fps = load_config()["video"]["fps"]
    durs = [(s["end_frame"] - s["start_frame"]) / fps for s in plan["shots"]]
    return {
        **plan,
        "fps": fps,
        "stats": {
            "shots": len(durs),
            "min_s": round(min(durs), 2) if durs else 0,
            "max_s": round(max(durs), 2) if durs else 0,
            "avg_s": round(sum(durs) / len(durs), 2) if durs else 0,
            "total_s": round(plan["total_frames"] / fps, 2),
        },
    }


@router.post("/assemble")
def run_assembly(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    plan = _plan(project_id)
    cfg = load_config()
    vcfg = cfg["video"]
    voice = db.get_voiceover(project_id)
    words = db.list_words(project_id)
    beat_text = {b["idx"]: b["text"] for b in db.list_beats(project_id)}
    out = output_dir(p["slug"])
    scfg = short_cfg()

    def work(progress):
        db.replace_shots(project_id, plan["shots"])
        audio = Path(voice["audio_path"])
        (out / "captions.srt").write_text(captions.build_srt(words), encoding="utf-8")
        timeline = fcpxml.build(plan["shots"], audio, voice["duration_s"], p["title"],
                                vcfg["fps"], vcfg["width"], vcfg["height"])
        (out / "timeline.fcpxml").write_text(timeline, encoding="utf-8")
        res = assemble.render(plan["shots"], audio, out / "video.mp4", vcfg, out / "_work", beat_text,
                              lambda msg, f: progress(msg, 0.75 * f))
        drift = abs(res["duration"] - res["expected"])
        result = {**res, "drift_s": round(drift, 3), "missing_images": plan["missing_images"],
                  "unused_images": plan["unused_images"], "short": None, "short_error": None}
        # The vertical Short is made from the same shots. If it fails, the full video is still kept.
        if not scfg["channel_name"].strip():
            result["short_error"] = "Set your channel name on the Settings page to make the Short too."
            return result
        try:
            progress("Short: finding the cliffhanger to end on", 0.76)
            cut = _cut(project_id)
            sres = shorts.render(plan["shots"], audio, out / "short.mp4", vcfg, scfg, out / "_short_work",
                                 lambda msg, f: progress(f"Short: {msg}", 0.76 + 0.24 * f), seconds=cut)
            db.save_short(project_id, rendered_at=time.strftime("%Y-%m-%d %H:%M:%S"), duration_s=sres["duration"])
            result["short"] = sres
        except procs.Stopped:
            raise
        except Exception as e:
            result["short_error"] = f"The full video is done, but the Short failed: {e}"
        return result

    return jobs.start("assemble", project_id, work)


@router.get("/outputs")
def outputs(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    out = output_dir(p["slug"])
    files = {}
    for name in ("video.mp4", "short.mp4", "timeline.fcpxml", "captions.srt"):
        f = out / name
        if f.exists():
            files[name] = {"url": f"/api/projects/{project_id}/file?path={rel(p, f)}", "path": str(f),
                           "size": f.stat().st_size, "modified": f.stat().st_mtime}
    return {"folder": str(out), "files": files}


@router.post("/publish")
def make_publish(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    script = db.current_script(project_id)
    beats = db.list_beats(project_id)
    if not script or not beats:
        raise HTTPException(400, "Script and beats are required")
    research = db.latest_research(project_id)
    meta = publish.generate(claude(), p["title"], script["text"], beats, db.list_words(project_id),
                            research["sources"] if research else [],
                            load_config().get("publish", {}).get("general_tags", []),
                            db.get_style_guide(project_id))
    meta["custom_thumbnails"] = (db.get_publish_meta(project_id) or {}).get("custom_thumbnails", [])
    db.save_publish_meta(project_id, meta)
    return meta


@router.get("/publish")
def get_publish(project_id: int) -> dict[str, Any] | None:
    project_or_404(project_id)
    meta = db.get_publish_meta(project_id)
    return {"custom_thumbnails": [], **meta} if meta else None


class ThumbAsk(BaseModel):
    request: str


@router.post("/publish/thumbnails")
def ask_thumbnail(project_id: int, body: ThumbAsk) -> dict[str, Any]:
    """Claude writes a thumbnail prompt from the owner's own idea; it is kept next to the suggested ones."""
    p = project_or_404(project_id)
    meta = db.get_publish_meta(project_id)
    script = db.current_script(project_id)
    if not meta or not script:
        raise HTTPException(400, "Generate the publishing pack first")
    if not body.request.strip():
        raise HTTPException(400, "Describe the thumbnail you want")
    title = meta["titles"][0] if meta.get("titles") else p["title"]
    prompt = publish.ask_thumbnail(claude(), body.request, title, script["text"], db.get_style_guide(project_id))
    meta["custom_thumbnails"] = [*meta.get("custom_thumbnails", []), {"request": body.request.strip(), "prompt": prompt}]
    db.save_publish_meta(project_id, meta)
    return meta


@router.delete("/publish/thumbnails/{n}")
def remove_thumbnail(project_id: int, n: int) -> dict[str, Any]:
    project_or_404(project_id)
    meta = db.get_publish_meta(project_id)
    if not meta or not 0 <= n < len(meta.get("custom_thumbnails", [])):
        raise HTTPException(404, "Thumbnail not found")
    meta["custom_thumbnails"].pop(n)
    db.save_publish_meta(project_id, meta)
    return meta
