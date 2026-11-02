"""File-system layout for a project's media and human-facing exports."""
from __future__ import annotations

from pathlib import Path

from app.config import PROJECTS_DIR


def project_dir(slug: str) -> Path:
    d = PROJECTS_DIR / slug
    for sub in ("audio", "prompts", "images", "output"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def audio_dir(slug: str) -> Path:
    return project_dir(slug) / "audio"


def prompts_dir(slug: str) -> Path:
    return project_dir(slug) / "prompts"


def images_dir(slug: str) -> Path:
    return project_dir(slug) / "images"


def batch_images_dir(slug: str, batch_no: int) -> Path:
    d = images_dir(slug) / f"batch_{batch_no:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(slug: str) -> Path:
    return project_dir(slug) / "output"


def write_script_mirror(slug: str, text: str) -> None:
    """Read-only copy of the current script so it can be opened outside the app."""
    (project_dir(slug) / "script.md").write_text(text, encoding="utf-8")
