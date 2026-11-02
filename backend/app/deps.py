"""Shared helpers for route handlers."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app import db
from app.config import DATA_DIR, get_key, load_config
from pipeline.claude_client import Claude
from pipeline.claude_code import ClaudeCode


def project_or_404(project_id: int) -> dict[str, Any]:
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def claude() -> Claude | ClaudeCode:
    """The configured Claude provider: 'claude_code' (subscription via the CLI) or 'api' (API key)."""
    cfg = load_config()["claude"]
    if cfg.get("provider", "claude_code") == "claude_code":
        return ClaudeCode(cfg, DATA_DIR / "claude_code_workdir")
    key = get_key("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set. Add it on the Settings page, "
                                 "or switch the Claude provider to Claude Code.")
    return Claude(key, cfg)


def elevenlabs_key() -> str:
    key = get_key("ELEVENLABS_API_KEY")
    if not key:
        raise HTTPException(400, "ELEVENLABS_API_KEY is not set. Add it on the Settings page.")
    return key
