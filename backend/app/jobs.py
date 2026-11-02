"""In-memory background jobs for long steps (voice, prompts, assembly). The UI polls /api/jobs/{id}."""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any, Callable

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def start(kind: str, project_id: int, fn: Callable[[Callable[[str, float], None]], Any]) -> dict[str, Any]:
    with _lock:
        for j in _jobs.values():
            if j["project_id"] == project_id and j["kind"] == kind and j["status"] == "running":
                return j
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "project_id": project_id, "status": "running",
               "message": "Starting", "progress": 0.0, "result": None, "error": None}
        _jobs[job["id"]] = job

    def progress(message: str, fraction: float) -> None:
        job["message"] = message
        job["progress"] = max(0.0, min(1.0, fraction))

    def run() -> None:
        try:
            job["result"] = fn(progress)
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # surfaced to the UI
            traceback.print_exc()
            job["status"] = "error"
            job["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id: str) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def active(project_id: int) -> list[dict[str, Any]]:
    return [j for j in _jobs.values() if j["project_id"] == project_id and j["status"] == "running"]
