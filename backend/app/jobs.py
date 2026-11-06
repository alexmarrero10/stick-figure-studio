"""In-memory background jobs for long steps (voice, prompts, assembly). The UI polls /api/jobs/{id}.

A job can be stopped: it ends at its next progress update, and any ffmpeg or Claude process it
started is killed at once (see pipeline.procs), so a step waiting on one stops too.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any, Callable

from pipeline import procs

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def start(kind: str, project_id: int, fn: Callable[[Callable[[str, float], None]], Any]) -> dict[str, Any]:
    with _lock:
        for j in _jobs.values():
            if j["project_id"] == project_id and j["kind"] == kind and j["status"] in ("running", "stopping"):
                return j
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "project_id": project_id, "status": "running",
               "message": "Starting", "progress": 0.0, "result": None, "error": None}
        _jobs[job["id"]] = job
        procs.begin(job["id"])

    def progress(message: str, fraction: float) -> None:
        procs.check()
        job["message"] = message
        job["progress"] = max(0.0, min(1.0, fraction))

    def run() -> None:
        procs.current.set(job["id"])
        try:
            job["result"] = fn(progress)
            procs.check()
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # surfaced to the UI
            if procs.stopped(job["id"]):
                job["status"] = "stopped"
                job["message"] = "Stopped"
            else:
                traceback.print_exc()
                job["status"] = "error"
                job["error"] = str(e)
        finally:
            procs.end(job["id"])

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id: str) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def active(project_id: int | None = None) -> list[dict[str, Any]]:
    """Running jobs for one project, or for all projects when project_id is None."""
    return [j for j in _jobs.values() if (project_id is None or j["project_id"] == project_id)
            and j["status"] in ("running", "stopping")]


def stop(job_id: str) -> dict[str, Any] | None:
    """Ask a job to stop and kill whatever it is running right now."""
    job = _jobs.get(job_id)
    if job and job["status"] == "running":
        job["status"] = "stopping"
        job["message"] = "Stopping…"
        procs.stop(job_id)
    return job
