"""Stopping background jobs: a job ends at its next step, and a process it is waiting on is killed."""
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app import jobs
from pipeline import ffmpeg, procs


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    from app.main import app
    with TestClient(app) as c:
        yield c


def _wait(job, statuses=("done", "error", "stopped"), timeout=20):
    end = time.time() + timeout
    while job["status"] not in statuses and time.time() < end:
        time.sleep(0.05)
    return job


def test_a_job_stops_at_its_next_progress_update():
    def work(progress):
        for i in range(1000):
            progress(f"step {i}", i / 1000)
            time.sleep(0.01)
        return "finished"

    job = jobs.start("test_loop", 1, work)
    time.sleep(0.1)
    assert jobs.stop(job["id"])["status"] == "stopping"
    assert _wait(job)["status"] == "stopped"
    assert job["result"] is None and job["error"] is None
    assert job not in jobs.active(1)


def test_stopping_kills_the_process_a_job_is_waiting_on():
    started = {}

    def work(progress):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL)
        started["proc"] = proc
        with procs.track(proc):
            proc.wait()
        procs.check()
        return "finished"

    job = jobs.start("test_proc", 1, work)
    while "proc" not in started:
        time.sleep(0.05)
    t = time.time()
    jobs.stop(job["id"])
    assert _wait(job)["status"] == "stopped"
    assert time.time() - t < 10 and started["proc"].poll() is not None


def test_a_job_that_is_not_stopped_still_reports_errors():
    def work(progress):
        raise ValueError("boom")

    job = _wait(jobs.start("test_err", 1, work))
    assert job["status"] == "error" and job["error"] == "boom"


def test_ffmpeg_never_waits_on_the_console(monkeypatch):
    seen = {}

    class P:
        returncode = 0

        def __init__(self, args, **kw):
            seen["args"], seen["kw"] = args, kw

        def communicate(self):
            return "", ""

        def poll(self):
            return 0

    monkeypatch.setattr(ffmpeg.subprocess, "Popen", P)
    ffmpeg.run(["-i", "a.wav", "b.mp3"])
    assert seen["args"][:2] == ["ffmpeg", "-nostdin"] and seen["kw"]["stdin"] is subprocess.DEVNULL


def test_stop_route(client):
    job = jobs.start("test_route", 1, lambda progress: [progress("x", 0.1) or time.sleep(0.01) for _ in range(2000)])
    assert client.post(f"/api/jobs/{job['id']}/stop").json()["status"] == "stopping"
    assert _wait(job)["status"] == "stopped"
    assert client.post("/api/jobs/nope/stop").status_code == 404


def test_jobs_list_without_a_project_shows_every_running_job(client):
    """start.ps1 asks this before restarting the server, so a running job is never killed."""
    a = jobs.start("list_a", 101, lambda progress: [progress("x", 0.1) or time.sleep(0.01) for _ in range(2000)])
    b = jobs.start("list_b", 102, lambda progress: [progress("x", 0.1) or time.sleep(0.01) for _ in range(2000)])
    try:
        ids = {j["id"] for j in client.get("/api/jobs").json()}
        assert {a["id"], b["id"]} <= ids
        assert [j["id"] for j in client.get("/api/jobs?project_id=101").json()] == [a["id"]]
    finally:
        jobs.stop(a["id"])
        jobs.stop(b["id"])
        _wait(a)
        _wait(b)
    assert not {a["id"], b["id"]} & {j["id"] for j in client.get("/api/jobs").json()}
