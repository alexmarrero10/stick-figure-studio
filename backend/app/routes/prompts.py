from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, project_or_404
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
    """Beats in the first minute, which is also cut into the Short."""
    cfg = load_config()
    return shorts.opening_beats(beats, db.list_words(project_id), cfg.get("shorts", {}).get("max_seconds", 59),
                                cfg["script"].get("wpm_estimate", 180))


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
        if body.only_missing:
            existing = db.list_prompts(project_id)
            have = {p["beat_id"] for p in existing}
            todo = [b for b in beats if b["id"] not in have]
            written = {p["idx"]: {"scene": p["scene"], "label": p["label"]} for p in existing}
            known_cast = {p["idx"]: p["characters"] for p in existing if p["characters"] is not None}
        if not body.only_missing:
            db.clear_batches_done(project_id)  # new prompts mean the Flow batches have to be made again
        if todo:
            progress("Deciding who is in each image", 0.04)
            cast = prompts_mod.cast_beats(c, script, guide, todo, known=known_cast,
                                          progress=lambda m, f: progress(m, 0.04 + 0.16 * f))
            scenes = prompts_mod.write_scenes(c, script, guide, todo, progress=lambda m, f: progress(m, 0.2 + 0.75 * f),
                                              written=written, opening=_opening(project_id, beats), cast=cast)
            by_idx = {b["idx"]: b for b in todo}
            db.upsert_prompts(project_id, [
                {"beat_id": by_idx[i]["id"], "batch_no": prompts_mod.batch_of(i, batch), **s, "characters": cast[i]}
                for i, s in scenes.items() if i in by_idx
            ])
        files = _export(project_id)
        return {"files": files, "missing": len(beats) - len(db.list_prompts(project_id))}

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


@router.get("")
def list_prompts(project_id: int) -> dict[str, Any]:
    project_or_404(project_id)
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
    db.save_style_guide(project_id, body.style_prefix, body.characters, None, body.props, body.locations)
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
    cast = next((p["characters"] for p in existing if p["beat_id"] == beat_id), None)
    if cast is None:  # written before casting existed: cast this image now, with its neighbours for context
        near = [b for b in beats if abs(b["idx"] - beat["idx"]) <= 3]
        cast = prompts_mod.cast_beats(c, script, guide, near)[beat["idx"]]
    res = prompts_mod.regenerate_one(c, script, guide, beats, beat["idx"], body.note, written,
                                     beat["idx"] in _opening(project_id, beats), cast)
    batch = load_config()["prompts"]["batch_size"]
    db.upsert_prompts(project_id, [{"beat_id": beat_id, "batch_no": prompts_mod.batch_of(beat["idx"], batch), **res,
                                    "characters": cast}])
    _export(project_id)
    return {**res, "prompt": prompts_mod.prompt_text(guide["style_prefix"], {**res, "idx": beat["idx"]}, batch)}


@router.get("/batch/{batch_no}", response_class=PlainTextResponse)
def batch_text(project_id: int, batch_no: int) -> str:
    p = project_or_404(project_id)
    f = prompts_dir(p["slug"]) / f"batch_{batch_no:02d}.txt"
    if not f.exists():
        raise HTTPException(404, "Batch not found")
    return f.read_text(encoding="utf-8")
