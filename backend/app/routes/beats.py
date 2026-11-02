from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.config import load_config
from app.deps import claude, project_or_404
from app.storage import write_script_mirror
from pipeline import beat_review, scenes
from pipeline.script import to_ascii

router = APIRouter(prefix="/api/projects/{project_id}/beats", tags=["beats"])


def _with_estimates(beats: list[dict[str, Any]], project_id: int) -> list[dict[str, Any]]:
    wpm = load_config()["script"]["wpm_estimate"]
    words = db.list_words(project_id)
    voice = db.get_voiceover(project_id)
    timed = bool(words) and voice and beats and voice["script_version_id"] == beats[0]["script_version_id"]
    out = []
    for b in beats:
        b = dict(b)
        b["est_seconds"] = round((b["word_end"] - b["word_start"] + 1) * 60 / wpm, 2)
        if timed:
            b["start"] = words[b["word_start"]]["start"]
            b["end"] = words[b["word_end"]]["end"]
        out.append(b)
    return out


@router.get("")
def get_beats(project_id: int) -> list[dict[str, Any]]:
    project_or_404(project_id)
    return _with_estimates(db.list_beats(project_id), project_id)


class BuildBody(BaseModel):
    review: bool = True


@router.post("/build")
def build(project_id: int, body: BuildBody) -> dict[str, Any]:
    project_or_404(project_id)
    script = db.current_script(project_id)
    if not script:
        raise HTTPException(400, "Write the script first")
    cfg = load_config()
    bc = cfg["beats"]
    beats = scenes.build_beats(script["text"], bc["min_words"], bc["max_words"], cfg["script"]["wpm_estimate"])
    skipped: list[str] = []
    applied = 0
    if body.review:
        ops = beat_review.review(claude(), beats)
        ranges = [(b["word_start"], b["word_end"]) for b in beats]
        new_ranges, skipped = scenes.apply_ops(ranges, ops, len(script["text"].split()), bc["max_words"])
        applied = len(ops) - len(skipped)
        beats = scenes.beats_from_ranges(script["text"], new_ranges, cfg["script"]["wpm_estimate"])
    db.replace_beats(project_id, script["id"], beats)
    return {"beats": get_beats(project_id), "review_applied": applied, "review_skipped": skipped}


class TextBody(BaseModel):
    text: str


@router.put("/{idx}/text")
def edit_text(project_id: int, idx: int, body: TextBody) -> list[dict[str, Any]]:
    """Rewrite one beat's words. Saves a new script version; other beats keep their ranges and prompts."""
    p = project_or_404(project_id)
    beats = db.list_beats(project_id)
    script = db.current_script(project_id)
    if not beats or not script:
        raise HTTPException(400, "No beats yet")
    if beats[0]["script_version_id"] != script["id"]:
        raise HTTPException(400, "The script changed since these beats were built. Rebuild the beats first.")
    ranges = [(b["word_start"], b["word_end"]) for b in beats]
    try:
        new_script, new_ranges = scenes.replace_beat_text(script["text"], ranges, idx, to_ascii(body.text))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if new_script == script["text"]:
        return get_beats(project_id)
    prompts = {pr["idx"]: pr for pr in db.list_prompts(project_id)}
    v = db.save_script(project_id, new_script, "manual", f"Edited beat #{idx}")
    write_script_mirror(p["slug"], new_script)
    cfg = load_config()
    db.replace_beats(project_id, v["id"], scenes.beats_from_ranges(new_script, new_ranges, cfg["script"]["wpm_estimate"]))
    # The edited beat's picture may no longer fit, so only the other beats keep their prompts.
    batch = cfg["prompts"]["batch_size"]
    for edited in (False, True):
        kept = [
            {"beat_id": b["id"], "batch_no": b["idx"] // batch + 1, "scene": prompts[b["idx"]]["scene"]}
            for b in db.list_beats(project_id)
            if b["idx"] != idx and b["idx"] in prompts and bool(prompts[b["idx"]]["edited"]) == edited
        ]
        if kept:
            db.upsert_prompts(project_id, kept, edited=edited)
    return get_beats(project_id)


class OpsBody(BaseModel):
    ops: list[dict[str, Any]]


@router.post("/ops")
def ops(project_id: int, body: OpsBody) -> list[dict[str, Any]]:
    """Manual merge/split from the UI. Note: this resets image prompts for all beats."""
    project_or_404(project_id)
    beats = db.list_beats(project_id)
    if not beats:
        raise HTTPException(400, "No beats yet")
    script = db.get_script_version(beats[0]["script_version_id"])
    cfg = load_config()
    ranges = [(b["word_start"], b["word_end"]) for b in beats]
    new_ranges, skipped = scenes.apply_ops(ranges, body.ops, len(script["text"].split()), cfg["beats"]["max_words"] + 8)
    if skipped:
        raise HTTPException(400, "; ".join(skipped))
    prompts = {(p["word_start"], p["word_end"]): p for p in db.list_prompts(project_id)}
    db.replace_beats(project_id, script["id"], scenes.beats_from_ranges(script["text"], new_ranges))
    # Keep prompts for beats whose word range didn't change.
    kept = []
    batch = load_config()["prompts"]["batch_size"]
    for b in db.list_beats(project_id):
        old = prompts.get((b["word_start"], b["word_end"]))
        if old:
            kept.append({"beat_id": b["id"], "batch_no": b["idx"] // batch + 1, "scene": old["scene"]})
    if kept:
        db.upsert_prompts(project_id, kept)
    return get_beats(project_id)
