from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, project_or_404
from app.routes.shorts import stored_cut
from app.storage import prompts_dir
from pipeline import prompts as prompts_mod
from pipeline import shorts

router = APIRouter(prefix="/api/projects/{project_id}/prompts", tags=["prompts"])


def _beats_and_script(project_id: int) -> tuple[list[dict[str, Any]], str]:
    beats = db.list_beats(project_id)
    if not beats:
        raise HTTPException(400, "Build the beats first")
    script = db.get_script_version(beats[0]["script_version_id"])
    return beats, script["text"]


def _opening(project_id: int, beats: list[dict[str, Any]]) -> set[int]:
    """Beats in the opening, which is also cut into the Short: up to where the Short ends once that is
    chosen, otherwise the longest the Short may run."""
    cfg = load_config()
    seconds = stored_cut(project_id) or cfg.get("shorts", {}).get("max_seconds", 70)
    return shorts.opening_beats(beats, db.list_words(project_id), seconds, cfg["script"].get("wpm_estimate", 180))


def _export(project_id: int) -> list[str]:
    p = db.get_project(project_id)
    guide = db.get_style_guide(project_id)
    if not guide:
        return []
    batch = load_config()["prompts"]["batch_size"]
    return prompts_mod.write_batch_files(prompts_dir(p["slug"]), guide["style_prefix"], db.list_prompts(project_id), batch)


class GenBody(BaseModel):
    only_missing: bool = False
    new_style: bool = False


@router.post("/generate")
def generate(project_id: int, body: GenBody) -> dict[str, Any]:
    project_or_404(project_id)
    beats, script = _beats_and_script(project_id)
    c = claude()
    batch = load_config()["prompts"]["batch_size"]

    def work(progress):
        guide = db.get_style_guide(project_id)
        if not guide or body.new_style:
            progress("Designing the style guide and character looks", 0.02)
            g = prompts_mod.make_style_guide(c, script)
            db.save_style_guide(project_id, g["style_prefix"], g["characters"], g.get("setting_notes", ""),
                                g.get("props", []), g.get("locations", []))
            guide = db.get_style_guide(project_id)
        todo = beats
        written: dict[int, dict[str, str]] = {}
        known_cast: dict[int, list[dict[str, str]]] = {}
        known_things: dict[int, dict[str, Any]] = {}
        if body.only_missing:
            existing = db.list_prompts(project_id)
            have = {p["beat_id"] for p in existing}
            todo = [b for b in beats if b["id"] not in have]
            written = {p["idx"]: {"scene": p["scene"], "label": p["label"]} for p in existing}
            known_cast = {p["idx"]: p["characters"] for p in existing if p["characters"] is not None}
            known_things = {p["idx"]: p["things"] for p in existing if p["things"] is not None}
        if not body.only_missing:
            db.clear_batches_done(project_id)  # new prompts mean the Flow batches have to be made again
        if todo:
            progress("Deciding who and what is in each image", 0.04)
            cast, things = prompts_mod.stage_beats(c, script, guide, todo, known=known_cast, known_things=known_things,
                                                   progress=lambda m, f: progress(m, 0.04 + 0.16 * f))
            scenes = prompts_mod.write_scenes(c, script, guide, todo, progress=lambda m, f: progress(m, 0.2 + 0.75 * f),
                                              written=written, opening=_opening(project_id, beats), cast=cast,
                                              things=things)
            by_idx = {b["idx"]: b for b in todo}
            db.upsert_prompts(project_id, [
                {"beat_id": by_idx[i]["id"], "batch_no": prompts_mod.batch_of(i, batch), **s, "characters": cast[i],
                 "things": things[i]}
                for i, s in scenes.items() if i in by_idx
            ])
        files = _export(project_id)
        return {"files": files, "missing": len(beats) - len(db.list_prompts(project_id))}

    return jobs.start("prompts", project_id, work)


@router.post("/check-looks")
def check_looks(project_id: int) -> dict[str, Any]:
    """For prompts already written: decide the recurring objects and place in each image (and the
    cast, where missing), then fix the prompts that leave out a look, changing as little as possible.
    Prompts edited by hand are left alone."""
    project_or_404(project_id)
    beats, script = _beats_and_script(project_id)
    guide = db.get_style_guide(project_id)
    if not guide:
        raise HTTPException(400, "Generate prompts first")
    c = claude()
    batch = load_config()["prompts"]["batch_size"]

    def work(progress):
        existing = db.list_prompts(project_id)
        by_beat = {b["id"]: b for b in beats}
        todo = [by_beat[p["beat_id"]] for p in existing if p["beat_id"] in by_beat]
        progress("Deciding who and what is in each image", 0.02)
        cast, things = prompts_mod.stage_beats(c, script, guide, todo, progress=lambda m, f: progress(m, 0.02 + 0.48 * f))
        db.set_staging(project_id, {p["beat_id"]: (None if p["characters"] is not None else cast[p["idx"]], things[p["idx"]])
                                    for p in existing})
        rows = []
        for p in db.list_prompts(project_id):
            looks = prompts_mod.cast_looks(guide, p["characters"])
            stuff = prompts_mod.thing_looks(guide, p["things"])
            if not p["edited"] and prompts_mod.missing_looks(p["scene"], looks + stuff):
                rows.append({**p, "looks": looks, "things": stuff})
        skipped = sum(1 for p in db.list_prompts(project_id) if p["edited"] and prompts_mod.missing_looks(
            p["scene"], prompts_mod.cast_looks(guide, p["characters"]) + prompts_mod.thing_looks(guide, p["things"])))
        fixed = prompts_mod.patch_scenes(c, script, guide, rows, progress=lambda m, f: progress(m, 0.5 + 0.45 * f)) if rows else {}
        db.set_scenes(project_id, {r["beat_id"]: fixed[r["idx"]] for r in rows if r["idx"] in fixed})
        _export(project_id)
        return {"fixed": len(fixed), "skipped_edited": skipped,
                "batches": sorted({prompts_mod.batch_of(r["idx"], batch) for r in rows if r["idx"] in fixed})}

    return jobs.start("prompts", project_id, work)


@router.post("/labels")
def add_labels(project_id: int) -> dict[str, Any]:
    """Give a title to every prompt that has none, leaving the scenes untouched."""
    project_or_404(project_id)
    c = claude()
    batch = load_config()["prompts"]["batch_size"]

    def work(progress):
        todo = [p for p in db.list_prompts(project_id) if not p["label"]]
        if not todo:
            return {"titled": 0}
        labels = prompts_mod.write_labels(c, todo, progress=lambda m, f: progress(m, 0.05 + 0.9 * f))
        for edited in (False, True):  # keep each prompt's "edited" flag as it was
            db.upsert_prompts(project_id, [
                {"beat_id": p["beat_id"], "batch_no": prompts_mod.batch_of(p["idx"], batch), "scene": p["scene"],
                 "label": labels[p["idx"]]}
                for p in todo if p["idx"] in labels and bool(p["edited"]) == edited
            ], edited=edited)
        _export(project_id)
        return {"titled": len(labels)}

    return jobs.start("prompts", project_id, work)


def _save_characters(project_id: int, old: list[dict[str, Any]], new: list[dict[str, Any]], style_prefix: str,
                     props: list[dict[str, str]] | None = None, locations: list[dict[str, str]] | None = None) -> None:
    """Saves the character looks and swaps any changed look into the prompts that copied it."""
    new = prompts_mod.add_head_colors(new)
    db.save_style_guide(project_id, style_prefix, new, None, props, locations)
    pairs = prompts_mod.changed_looks(old, new)
    if pairs:
        db.set_scenes(project_id, {p["beat_id"]: s for p in db.list_prompts(project_id)
                                   if (s := prompts_mod.replace_looks(p["scene"], pairs)) != p["scene"]})


@router.get("")
def list_prompts(project_id: int) -> dict[str, Any]:
    project_or_404(project_id)
    guide = db.get_style_guide(project_id)
    if guide and prompts_mod.add_head_colors(guide["characters"]) != guide["characters"]:
        # made before every look stated its head color: add it to the guide and the prompts
        _save_characters(project_id, guide["characters"], guide["characters"], guide["style_prefix"])
        guide = db.get_style_guide(project_id)
    if guide:
        guide["style_prefix"] = prompts_mod.with_body_rule(guide["style_prefix"])
    items = db.list_prompts(project_id)
    batch = load_config()["prompts"]["batch_size"]
    for it in items:
        it["title"] = prompts_mod.image_title(prompts_mod.number_in_batch(it["idx"], batch), it["label"], it["scene"])
        if guide:
            it["prompt"] = prompts_mod.prompt_text(guide["style_prefix"], it, batch)
    texts = prompts_mod.batch_texts(guide["style_prefix"], items, batch) if guide else {}
    if texts:
        _export(project_id)  # keep batch_XX.txt the same as what the Copy button gives
    return {"style": guide, "prompts": items, "beats": len(db.list_beats(project_id)),
            "batch_size": batch, "done_batches": db.done_batches(project_id), "batch_texts": texts}


class DoneBody(BaseModel):
    done: bool


@router.put("/batch/{batch_no}/done")
def set_done(project_id: int, batch_no: int, body: DoneBody) -> dict[str, Any]:
    """Tick a batch off once its images have been created in Google Flow."""
    project_or_404(project_id)
    db.set_batch_done(project_id, batch_no, body.done)
    return {"done_batches": db.done_batches(project_id)}


class StyleBody(BaseModel):
    style_prefix: str
    characters: list[dict[str, Any]]
    props: list[dict[str, str]] | None = None
    locations: list[dict[str, str]] | None = None


@router.put("/style")
def put_style(project_id: int, body: StyleBody) -> dict[str, Any]:
    project_or_404(project_id)
    old = db.get_style_guide(project_id)
    _save_characters(project_id, old["characters"] if old else [], body.characters, body.style_prefix,
                     body.props, body.locations)
    _export(project_id)
    return db.get_style_guide(project_id)


class SceneBody(BaseModel):
    scene: str
    label: str | None = None


@router.put("/{beat_id}")
def edit(project_id: int, beat_id: int, body: SceneBody) -> dict[str, Any]:
    project_or_404(project_id)
    beat = next((b for b in db.list_beats(project_id) if b["id"] == beat_id), None)
    if not beat:
        raise HTTPException(404, "Beat not found")
    batch = load_config()["prompts"]["batch_size"]
    label = body.label
    if label is None:
        label = next((x["label"] for x in db.list_prompts(project_id) if x["beat_id"] == beat_id), "")
    db.upsert_prompts(project_id, [{"beat_id": beat_id, "batch_no": prompts_mod.batch_of(beat["idx"], batch),
                                    "scene": body.scene.strip(), "label": prompts_mod.clean_label(label)}], edited=True)
    _export(project_id)
    return {"ok": True}


class RegenBody(BaseModel):
    note: str = ""


@router.post("/{beat_id}/regenerate")
def regenerate(project_id: int, beat_id: int, body: RegenBody) -> dict[str, Any]:
    project_or_404(project_id)
    beats, script = _beats_and_script(project_id)
    beat = next((b for b in beats if b["id"] == beat_id), None)
    guide = db.get_style_guide(project_id)
    if not beat or not guide:
        raise HTTPException(400, "Generate prompts first")
    existing = db.list_prompts(project_id)
    written = {p["idx"]: {"scene": p["scene"], "label": p["label"]} for p in existing}
    c = claude()
    row = next((p for p in existing if p["beat_id"] == beat_id), {})
    cast, things = row.get("characters"), row.get("things")
    if cast is None or things is None:  # written before staging existed: stage it now, with its neighbours
        near = [b for b in beats if abs(b["idx"] - beat["idx"]) <= 3]
        new_cast, new_things = prompts_mod.stage_beats(c, script, guide, near)
        cast = new_cast[beat["idx"]] if cast is None else cast
        things = new_things[beat["idx"]] if things is None else things
    res = prompts_mod.regenerate_one(c, script, guide, beats, beat["idx"], body.note, written,
                                     beat["idx"] in _opening(project_id, beats), cast, things)
    batch = load_config()["prompts"]["batch_size"]
    db.upsert_prompts(project_id, [{"beat_id": beat_id, "batch_no": prompts_mod.batch_of(beat["idx"], batch), **res,
                                    "characters": cast, "things": things}])
    _export(project_id)
    return {**res, "prompt": prompts_mod.prompt_text(guide["style_prefix"], {**res, "idx": beat["idx"]}, batch)}


@router.get("/batch/{batch_no}", response_class=PlainTextResponse)
def batch_text(project_id: int, batch_no: int) -> str:
    p = project_or_404(project_id)
    f = prompts_dir(p["slug"]) / f"batch_{batch_no:02d}.txt"
    if not f.exists():
        raise HTTPException(404, "Batch not found")
    return f.read_text(encoding="utf-8")
