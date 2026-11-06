from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import db, jobs
from app.config import PROJECTS_DIR
from app.deps import project_or_404
from app.storage import project_dir

router = APIRouter(prefix="/api/projects", tags=["projects"])


class NewProject(BaseModel):
    title: str
    idea_id: int | None = None
    format: str = "story"


@router.get("")
def list_projects() -> list[dict[str, Any]]:
    return [{**p, "status": db.project_status(p["id"])} for p in db.list_projects()]


@router.post("")
def create_project(body: NewProject) -> dict[str, Any]:
    p = db.create_project(body.title.strip() or "Untitled video", body.idea_id, body.format)
    project_dir(p["slug"])
    return p


@router.get("/{project_id}")
def get_project(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    idea = db.get_idea(p["idea_id"]) if p["idea_id"] else None
    return {**p, "idea": idea, "status": db.project_status(project_id), "jobs": jobs.active(project_id)}


class ProjectEdit(BaseModel):
    title: str | None = None
    format: str | None = None
    archived: bool | None = None


@router.patch("/{project_id}")
def edit_project(project_id: int, body: ProjectEdit) -> dict[str, Any]:
    project_or_404(project_id)
    fields: dict[str, Any] = {}
    if body.title is not None and body.title.strip():
        fields["title"] = body.title.strip()
    if body.format is not None:
        if body.format not in db.FORMATS:
            raise HTTPException(400, f"Video type must be one of {', '.join(db.FORMATS)}")
        fields["format"] = body.format
    if body.archived is not None:
        fields["archived"] = int(body.archived)
    db.update_project(project_id, touch=set(fields) != {"archived"}, **fields)
    return db.get_project(project_id)


@router.delete("/{project_id}")
def delete_project(project_id: int, delete_files: bool = False) -> dict[str, Any]:
    p = project_or_404(project_id)
    if not p["archived"]:
        raise HTTPException(400, "Archive the project before deleting it")
    db.delete_project(project_id)
    if delete_files:
        shutil.rmtree(PROJECTS_DIR / p["slug"], ignore_errors=True)
    return {"ok": True}


@router.get("/{project_id}/file")
def get_file(project_id: int, path: str) -> FileResponse:
    """Serve a file from inside the project folder (audio, images, video)."""
    p = project_or_404(project_id)
    base = project_dir(p["slug"]).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target)


@router.post("/{project_id}/open-folder")
def open_folder(project_id: int, sub: str = "") -> dict[str, Any]:
    p = project_or_404(project_id)
    base = project_dir(p["slug"]).resolve()
    target = (base / sub).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(400, "Bad folder")
    target.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(target)  # type: ignore[attr-defined]
    return {"path": str(target)}


jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("")
def running_jobs(project_id: int | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    """Jobs still running for a project, so a page opened mid-job can pick it back up. Without a project,
    every running job (start.ps1 checks this before restarting the server)."""
    return [j for j in jobs.active(project_id) if kind is None or j["kind"] == kind]


@jobs_router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@jobs_router.post("/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, Any]:
    """Stop a running job: it ends at its next step, and its ffmpeg or Claude process is killed now."""
    j = jobs.stop(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


def rel(project: dict[str, Any], path: str | Path) -> str:
    """Path relative to the project folder, for the /file endpoint."""
    return Path(path).resolve().relative_to(project_dir(project["slug"]).resolve()).as_posix()
