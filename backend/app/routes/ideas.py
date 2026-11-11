from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude
from app.storage import project_dir
from pipeline import ideas

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


class SuggestBody(BaseModel):
    theme: str = ""
    count: int = 3
    trending: bool = True


@router.post("/suggest")
def suggest(body: SuggestBody) -> dict[str, Any]:
    """Background job (idea jobs use project id 0). Its result is the list of new ideas."""
    c = claude()
    trending = body.trending and load_config()["claude"].get("web_search", True)

    def work(progress):
        notes = ""
        if trending:
            progress("Searching YouTube and social media for trending history topics", 0.1)
            notes = ideas.trends(c, body.theme)
        progress("Writing topic ideas", 0.6)
        avoid = db.used_idea_titles() + [i["title"] for i in db.list_ideas()[:100]]
        result = ideas.suggest(c, max(1, min(body.count, 20)), body.theme, avoid, notes)
        return db.add_ideas(result, "trending" if notes else "suggested")

    return jobs.start("ideas", 0, work)


class OwnIdea(BaseModel):
    text: str
    refine: bool = True


@router.post("/own")
def own(body: OwnIdea) -> dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(400, "Describe your idea first")
    if body.refine:
        idea = ideas.refine(claude(), body.text)
    else:
        idea = {"title": body.text.strip()[:120], "hook": "", "why_it_works": "", "category": "",
                "era": "", "documentation": body.text.strip(), "format": ideas.guess_format(body.text)}
    return db.add_ideas([idea], "user")[0]


@router.get("")
def list_ideas(saved: bool = False) -> list[dict[str, Any]]:
    return db.list_ideas(saved)


class SaveBody(BaseModel):
    saved: bool


@router.put("/{idea_id}/saved")
def save(idea_id: int, body: SaveBody) -> dict[str, Any]:
    db.set_idea_saved(idea_id, body.saved)
    return {"ok": True}


@router.post("/{idea_id}/use")
def use(idea_id: int) -> dict[str, Any]:
    """Create a project from an idea and move on to the script step."""
    idea = db.get_idea(idea_id)
    if not idea:
        raise HTTPException(404, "Idea not found")
    if idea["project_id"]:
        p = db.get_project(idea["project_id"])
        if p:
            return p
    p = db.create_project(idea["title"], idea_id, idea.get("format") or "story")
    project_dir(p["slug"])
    return p
