"""Child processes (ffmpeg, the Claude CLI) tracked per background job, so stopping a job can kill
what it is running. app.jobs sets the current job; thread pools carry it over with
contextvars.copy_context()."""
from __future__ import annotations

import contextvars
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

_procs: dict[str, set[subprocess.Popen]] = {}
_stop: dict[str, threading.Event] = {}
current: contextvars.ContextVar[str | None] = contextvars.ContextVar("job", default=None)


class Stopped(Exception):
    """Raised inside a job that was stopped."""


def begin(job_id: str) -> None:
    _procs[job_id] = set()
    _stop[job_id] = threading.Event()


def end(job_id: str) -> None:
    _procs.pop(job_id, None)


def stopped(job_id: str | None) -> bool:
    return bool(job_id) and job_id in _stop and _stop[job_id].is_set()


def stop(job_id: str) -> None:
    _stop[job_id].set()
    for proc in list(_procs.get(job_id, ())):
        kill(proc)


def check() -> None:
    """Raise Stopped if the job this code runs for was stopped."""
    if stopped(current.get()):
        raise Stopped("Stopped")


@contextmanager
def track(proc: subprocess.Popen) -> Iterator[subprocess.Popen]:
    """Register a running process with the current job (if any), so stopping the job kills it."""
    job_id = current.get()
    procs = _procs.get(job_id) if job_id else None
    if procs is not None:
        procs.add(proc)
        if stopped(job_id):
            kill(proc)
    try:
        yield proc
    finally:
        if procs is not None:
            procs.discard(proc)


def kill(proc: subprocess.Popen) -> None:
    """Kill a process and its children (the Claude CLI can start helpers)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()
