from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import db
from app.config import load_config
from app.deps import project_or_404
from app.routes.projects import rel
from app.storage import batch_images_dir, images_dir
from pipeline import images as images_mod

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


def _slots(project_id: int, batch_no: int) -> int:
    batch = load_config()["prompts"]["batch_size"]
    n_beats = len(db.list_beats(project_id))
    return max(0, min(batch, n_beats - (batch_no - 1) * batch)) or batch


def _scan(project_id: int, batch_no: int) -> list[str]:
    p = db.get_project(project_id)
    ordered = images_mod.order_images(batch_images_dir(p["slug"], batch_no))
    placed, warnings = images_mod.assign_positions(ordered, _slots(project_id, batch_no))
    db.replace_batch_images(project_id, batch_no, placed)
    return warnings + images_mod.tie_warnings([x for x in ordered if not x["number"]])


@router.post("/{batch_no}/upload")
async def upload(project_id: int, batch_no: int, files: list[UploadFile] = File(...),
                 last_modified: str = Form("[]")) -> dict[str, Any]:
    """Save uploaded images (or the images inside uploaded .zip files) into images/batch_XX. Images
    whose slot already has a picture, or whose file name is already there, are skipped, so
    re-uploading a whole Flow download only adds the missing ones. The browser's lastModified times
    are restored on disk so the mtime fallback still reflects when Flow produced the image."""
    p = project_or_404(project_id)
    folder = batch_images_dir(p["slug"], batch_no)
    slots = _slots(project_id, batch_no)
    filled = {im["position"] + 1 for im in db.list_images(project_id)
              if im["batch_no"] == batch_no and im["position"] < slots}
    guard = images_mod.SlotGuard(folder, filled, slots)
    times = json.loads(last_modified or "[]")
    for i, f in enumerate(files):
        name = Path(f.filename or f"image_{i}.png").name
        if Path(name).suffix.lower() == ".zip":
            try:
                images_mod.extract_zip(await f.read(), folder, guard.accept)
            except zipfile.BadZipFile:
                raise HTTPException(400, f"{name} is not a valid zip file")
            continue
        if Path(name).suffix.lower() not in images_mod.IMAGE_EXTS or not guard.accept(name):
            continue
        dst = folder / name
        dst.write_bytes(await f.read())
        if i < len(times) and times[i]:
            t = float(times[i]) / 1000
            os.utime(dst, (t, t))
    warnings = _scan(project_id, batch_no)
    return {"images": list_images(project_id), "warnings": warnings,
            "added": len(guard.added), "skipped": len(guard.skipped)}


@router.post("/{batch_no}/clear")
def clear_batch(project_id: int, batch_no: int) -> dict[str, Any]:
    """Delete every image in one batch (the files too)."""
    p = project_or_404(project_id)
    folder = batch_images_dir(p["slug"], batch_no)
    removed = 0
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in images_mod.IMAGE_EXTS:
            f.unlink()
            removed += 1
    _scan(project_id, batch_no)
    return {**list_images(project_id), "removed": removed}


@router.post("/{batch_no}/rescan")
def rescan(project_id: int, batch_no: int) -> dict[str, Any]:
    """Re-read a batch folder after copying files into it by hand."""
    project_or_404(project_id)
    warnings = _scan(project_id, batch_no)
    return {"images": list_images(project_id), "warnings": warnings}


@router.post("/rescan-all")
def rescan_all(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    warnings: list[str] = []
    for d in sorted(images_dir(p["slug"]).glob("batch_*")):
        if d.is_dir():
            warnings += _scan(project_id, int(d.name.split("_")[1]))
    return {"images": list_images(project_id), "warnings": warnings}


@router.get("")
def list_images(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    batch = load_config()["prompts"]["batch_size"]
    beats = db.list_beats(project_id)
    imgs = db.list_images(project_id)
    by_batch: dict[int, list[dict[str, Any]]] = {}
    for im in imgs:
        im["url"] = f"/api/projects/{project_id}/file?path={rel(p, im['path'])}"
        im["name"] = Path(im["path"]).name
        by_batch.setdefault(im["batch_no"], []).append(im)
    n_batches = (len(beats) + batch - 1) // batch
    out = []
    for n in range(1, max(n_batches, max(by_batch, default=0)) + 1):
        bbeats = beats[(n - 1) * batch:n * batch]
        bimgs = by_batch.get(n, [])
        out.append({
            "batch_no": n,
            "expected": len(bbeats),
            "count": len(bimgs),
            "folder": str(batch_images_dir(p["slug"], n)),
            "slots": [
                {"beat_idx": b["idx"], "beat_text": b["text"],
                 "image": next((im for im in bimgs if im["position"] == k), None)}
                for k, b in enumerate(bbeats)
            ],
            "extra": [im for im in bimgs if im["position"] >= len(bbeats)],
        })
    return {"batches": out}


class OrderBody(BaseModel):
    paths: list[str | None]  # index = slot; None leaves that slot empty


@router.put("/{batch_no}/order")
def reorder(project_id: int, batch_no: int, body: OrderBody) -> dict[str, Any]:
    project_or_404(project_id)
    existing = {im["path"] for im in db.list_images(project_id) if im["batch_no"] == batch_no}
    given = [x for x in body.paths if x is not None]
    if len(given) != len(set(given)) or set(given) != existing:
        raise HTTPException(400, "Order must list every image in the batch exactly once")
    db.reorder_batch(project_id, batch_no, body.paths)
    return list_images(project_id)


class DeleteBody(BaseModel):
    path: str


@router.post("/{batch_no}/delete")
def delete_image(project_id: int, batch_no: int, body: DeleteBody) -> dict[str, Any]:
    p = project_or_404(project_id)
    folder = batch_images_dir(p["slug"], batch_no).resolve()
    target = Path(body.path).resolve()
    if target.parent != folder:
        raise HTTPException(400, "Not in this batch")
    target.unlink(missing_ok=True)
    _scan(project_id, batch_no)
    return list_images(project_id)


@router.post("/{batch_no}/slot/{position}")
async def upload_to_slot(project_id: int, batch_no: int, position: int, file: UploadFile = File(...)) -> dict[str, Any]:
    """Put one picked image into an empty slot (0-based). It is saved as "<number> - <title>" so it
    stays in that slot whenever the batch is read again."""
    p = project_or_404(project_id)
    slots = _slots(project_id, batch_no)
    if not 0 <= position < slots:
        raise HTTPException(400, "No such slot")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in images_mod.IMAGE_EXTS:
        raise HTTPException(400, "Pick a PNG, JPG or WebP image")
    if any(im["batch_no"] == batch_no and im["position"] == position for im in db.list_images(project_id)):
        raise HTTPException(400, "That slot already has an image. Remove it first.")
    batch = load_config()["prompts"]["batch_size"]
    idx = (batch_no - 1) * batch + position
    label = next((pr["label"] for pr in db.list_prompts(project_id) if pr["idx"] == idx), "")
    label = re.sub(r'[\\/:*?"<>|]+', "", label).strip(" .")[:80] or "image"  # safe as a Windows file name
    folder = batch_images_dir(p["slug"], batch_no)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".upload{suffix}"
    tmp.write_bytes(await file.read())
    images_mod.rename_free(tmp, f"{position + 1} - {label}{suffix}")
    warnings = _scan(project_id, batch_no)
    return {"images": list_images(project_id), "warnings": warnings}


class MoveBody(BaseModel):
    path: str
    to: int  # 0-based slot


@router.post("/{batch_no}/move")
def move_image(project_id: int, batch_no: int, body: MoveBody) -> dict[str, Any]:
    """Drag an image onto a slot. A picture already there swaps places with it (or, when an extra was
    dragged in, loses its number: it fills the first empty slot, or becomes an extra when there is
    none). Files are renamed to their new slot numbers, so the order sticks."""
    p = project_or_404(project_id)
    slots = _slots(project_id, batch_no)
    folder = batch_images_dir(p["slug"], batch_no).resolve()
    imgs = {Path(im["path"]).resolve(): im for im in db.list_images(project_id) if im["batch_no"] == batch_no}
    src = Path(body.path).resolve()
    if src.parent != folder or src not in imgs:
        raise HTTPException(400, "Not in this batch")
    if not 0 <= body.to < slots:
        raise HTTPException(400, "No such slot")
    from_pos = imgs[src]["position"]
    other = next((path for path, im in imgs.items() if im["position"] == body.to and path != src), None)
    # Park the moving file under a temporary name first so the two renames can't collide.
    src = images_mod.rename_free(src, f".moving{src.suffix}")
    if other is not None:
        back = from_pos + 1 if from_pos < slots else None
        images_mod.rename_free(other, images_mod.numbered(other.name, back))
    images_mod.rename_free(src, images_mod.numbered(Path(body.path).name, body.to + 1))
    _scan(project_id, batch_no)
    return list_images(project_id)


def beat_image_map(project_id: int) -> dict[int, str]:
    """beat idx → image path, using batch + position (batch n holds beats (n-1)*24 ...)."""
    batch = load_config()["prompts"]["batch_size"]
    out: dict[int, str] = {}
    for im in db.list_images(project_id):
        if im["position"] < batch:  # extras don't belong to any beat
            out[(im["batch_no"] - 1) * batch + im["position"]] = im["path"]
    return out
