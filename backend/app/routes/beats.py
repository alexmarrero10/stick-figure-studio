from __future__ import annotations

from typing import Any, Callable

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
        ops = beat_review.review(claude(), beats, bc["min_words"], bc["max_words"], cfg["script"]["wpm_estimate"])
        ranges = [(b["word_start"], b["word_end"]) for b in beats]
        new_ranges, skipped = scenes.apply_ops(ranges, ops, len(script["text"].split()), bc["max_words"])
        applied = len(ops) - len(skipped)
        beats = scenes.beats_from_ranges(script["text"], new_ranges, cfg["script"]["wpm_estimate"])
    db.replace_beats(project_id, script["id"], beats)
    db.clear_beat_undo(project_id)
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
    # The edited beat's picture may no longer fit, so only the other beats keep their prompts.
    prompts = {pr["idx"]: pr for pr in db.list_prompts(project_id) if pr["idx"] != idx}
    v = db.save_script(project_id, new_script, "manual", f"Edited beat #{idx}")
    write_script_mirror(p["slug"], new_script)
    cfg = load_config()
    db.replace_beats(project_id, v["id"], scenes.beats_from_ranges(new_script, new_ranges, cfg["script"]["wpm_estimate"]))
    db.clear_beat_undo(project_id)  # the script changed, so earlier splits can't be undone
    _restore_prompts(project_id, prompts, lambda b: b["idx"])
    return get_beats(project_id)


def _restore_prompts(project_id: int, saved: dict[Any, dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> None:
    """Put saved prompts back on the beats they belong to (matched by `key(beat)`), keeping each
    one's title, cast, objects and edited flag."""
    batch = load_config()["prompts"]["batch_size"]
    rows = [(b, saved[key(b)]) for b in db.list_beats(project_id) if key(b) in saved]
    for edited in (False, True):
        kept = [{"beat_id": b["id"], "batch_no": b["idx"] // batch + 1, "scene": pr["scene"],
                 "label": pr.get("label", ""), "characters": pr.get("characters"), "things": pr.get("things")}
                for b, pr in rows if bool(pr.get("edited")) == edited]
        if kept:
            db.upsert_prompts(project_id, kept, edited=edited)


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
    db.push_beat_undo(project_id, {"script_version_id": script["id"], "ranges": ranges,
                                   "prompts": [{**_saved_prompt(p), "range": list(k)} for k, p in prompts.items()]})
    db.replace_beats(project_id, script["id"], scenes.beats_from_ranges(script["text"], new_ranges))
    # Keep prompts for beats whose word range didn't change.
    _restore_prompts(project_id, prompts, lambda b: (b["word_start"], b["word_end"]))
    return get_beats(project_id)


def _saved_prompt(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("scene", "label", "edited", "characters", "things")}


@router.get("/undo")
def undo_steps(project_id: int) -> dict[str, int]:
    project_or_404(project_id)
    return {"steps": db.beat_undo_steps(project_id)}


@router.post("/undo")
def undo(project_id: int) -> list[dict[str, Any]]:
    """Undo the latest split or merge: the beats and their image prompts go back to how they were."""
    project_or_404(project_id)
    snap = db.pop_beat_undo(project_id)
    beats = db.list_beats(project_id)
    if not snap:
        raise HTTPException(400, "Nothing to undo")
    if not beats or beats[0]["script_version_id"] != snap["script_version_id"]:
        db.clear_beat_undo(project_id)
        raise HTTPException(400, "The beats were rebuilt since then, so that change can't be undone")
    script = db.get_script_version(snap["script_version_id"])
    db.replace_beats(project_id, script["id"],
                     scenes.beats_from_ranges(script["text"], [tuple(r) for r in snap["ranges"]]))
    _restore_prompts(project_id, {tuple(p["range"]): p for p in snap["prompts"]},
                     lambda b: (b["word_start"], b["word_end"]))
    return get_beats(project_id)
