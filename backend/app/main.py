"""FastAPI app. Serves the API and, in production mode, the built React UI."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import ROOT
from app.routes import assemble, beats, ideas, images, projects, prompts, script, settings, site, voice
from pipeline.claude_client import ClaudeError
from pipeline.ffmpeg import FFmpegError
from pipeline.voice import VoiceError

app = FastAPI(title="Stick Figure Video Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _quiet_resets(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Windows logs a ConnectionResetError whenever the browser drops a media request early
    (normal when an <audio>/<video> player seeks or stops). Ignore just that; log everything else."""
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


@app.on_event("startup")
async def startup() -> None:
    db.migrate()
    asyncio.get_running_loop().set_exception_handler(_quiet_resets)


@app.exception_handler(ClaudeError)
@app.exception_handler(VoiceError)
@app.exception_handler(FFmpegError)
async def pipeline_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


for r in (settings, projects, ideas, script, beats, voice, prompts, images, assemble, site):
    app.include_router(r.router)
app.include_router(projects.jobs_router)

DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        f = DIST / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        # Never cache the page itself, so a browser always picks up a newly built UI after a restart.
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
