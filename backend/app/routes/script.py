from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, project_or_404
from app.storage import write_script_mirror
from pipeline import script as script_mod
from pipeline.claude_client import ClaudeError

router = APIRouter(prefix="/api/projects/{project_id}", tags=["script"])


def _idea(p: dict[str, Any]) -> dict[str, Any]:
    idea = db.get_idea(p["idea_id"]) if p["idea_id"] else None
    return idea or {"title": p["title"], "hook": "", "why_it_works": "", "documentation": ""}


# --- research ---------------------------------------------------------------

@router.post("/research")
def start_research(project_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    c = claude()
    web = load_config()["claude"].get("web_search", True)
    depth = load_config()["claude"].get("research_depth", "quick")

    def work(progress):
        progress("Researching" + (" (searching the web)" if web else ""), 0.1)
        content, sources = script_mod.research(c, _idea(p), web, p["format"], depth)
        progress("Checking that every source link works", 0.9)
        return db.save_research(project_id, content, script_mod.check_sources(sources))["id"]

    return jobs.start("research", project_id, work)


@router.get("/research")
def get_research(project_id: int) -> dict[str, Any] | None:
    project_or_404(project_id)
    return db.latest_research(project_id)


class ResearchEdit(BaseModel):
    content: str


@router.put("/research")
def edit_research(project_id: int, body: ResearchEdit) -> dict[str, Any]:
    project_or_404(project_id)
    prev = db.latest_research(project_id)
    return db.save_research(project_id, body.content, prev["sources"] if prev else [])


# --- script -----------------------------------------------------------------

class GenerateBody(BaseModel):
    notes: str = ""


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@router.post("/script/generate")
def generate_script(project_id: int, body: GenerateBody) -> StreamingResponse:
    p = project_or_404(project_id)
    research = db.latest_research(project_id)
    if not research:
        raise HTTPException(400, "Run the research step first")
    c = claude()
    cfg = load_config()["script"]
    target = (cfg["target_words_min"], cfg["target_words_max"])

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            for text in script_mod.generate(c, _idea(p), research["content"], target, body.notes, cfg["wpm_estimate"],
                                            p["format"]):
                parts.append(text)
                yield _sse({"type": "text", "text": text})
            final = script_mod.clean_script("".join(parts))
            v = db.save_script(project_id, final, "generated", body.notes or None)
            write_script_mirror(p["slug"], final)
            yield _sse({"type": "done", "version": v})
        except (ClaudeError, Exception) as e:
            yield _sse({"type": "error", "error": str(e)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/script")
def get_script(project_id: int) -> dict[str, Any] | None:
    project_or_404(project_id)
    return db.current_script(project_id)


class SaveBody(BaseModel):
    text: str
    source: str = "manual"
    instruction: str | None = None


@router.put("/script")
def save_script(project_id: int, body: SaveBody) -> dict[str, Any]:
    p = project_or_404(project_id)
    cur = db.current_script(project_id)
    text = body.text.strip()
    if cur and cur["text"] == text:
        return cur
    v = db.save_script(project_id, text, body.source if body.source in ("manual", "ai_revision") else "manual",
                       body.instruction)
    write_script_mirror(p["slug"], text)
    return v


@router.get("/script/versions")
def versions(project_id: int) -> list[dict[str, Any]]:
    project_or_404(project_id)
    return db.list_script_versions(project_id)


@router.get("/script/versions/{version_id}")
def version(project_id: int, version_id: int) -> dict[str, Any]:
    v = db.get_script_version(version_id)
    if not v or v["project_id"] != project_id:
        raise HTTPException(404, "Version not found")
    return v


@router.post("/script/versions/{version_id}/restore")
def restore(project_id: int, version_id: int) -> dict[str, Any]:
    p = project_or_404(project_id)
    v = version(project_id, version_id)
    nv = db.save_script(project_id, v["text"], "manual", f"Restored version {version_id}")
    write_script_mirror(p["slug"], v["text"])
    return nv


# --- chat revisions ---------------------------------------------------------

class ChatBody(BaseModel):
    message: str


@router.get("/script/chat")
def chat_history(project_id: int) -> list[dict[str, Any]]:
    project_or_404(project_id)
    return db.list_revision_messages(project_id)


@router.post("/script/chat")
def chat(project_id: int, body: ChatBody) -> dict[str, Any]:
    project_or_404(project_id)
    cur = db.current_script(project_id)
    if not cur:
        raise HTTPException(400, "Generate or write a script first")
    history = db.list_revision_messages(project_id)
    result = script_mod.revise(claude(), cur["text"], history, body.message)
    db.add_revision_message(project_id, "user", body.message)
    msg = db.add_revision_message(project_id, "assistant", result["reply"], result["edits"])
    msg["edits"] = result["edits"]
    msg["script_version_id"] = cur["id"]
    return msg


@router.post("/script/grammar")
def grammar(project_id: int) -> dict[str, Any]:
    """Proofread the script, focusing on the passages typed by hand since Claude last wrote it.
    The fixes come back as pending edits in the chat, like any other suggestion."""
    project_or_404(project_id)
    cur = db.current_script(project_id)
    if not cur:
        raise HTTPException(400, "Generate or write a script first")
    last_ai = next((v for v in db.list_script_versions(project_id) if v["source"] != "manual"), None)
    before = db.get_script_version(last_ai["id"])["text"] if last_ai else None
    result = script_mod.check_grammar(claude(), cur["text"], before)
    db.add_revision_message(project_id, "user", "Check grammar")
    msg = db.add_revision_message(project_id, "assistant", result["reply"], result["edits"])
    msg["edits"] = result["edits"]
    msg["script_version_id"] = cur["id"]
    msg["passages"] = result["passages"]
    return msg


class ApplyBody(BaseModel):
    edits: list[dict[str, Any]]
    instruction: str | None = None


@router.post("/script/apply-edits")
def apply_edits(project_id: int, body: ApplyBody) -> dict[str, Any]:
    p = project_or_404(project_id)
    cur = db.current_script(project_id)
    if not cur:
        raise HTTPException(400, "No script")
    text, errors = script_mod.apply_edits(cur["text"], body.edits)
    v = db.save_script(project_id, text, "ai_revision", body.instruction)
    write_script_mirror(p["slug"], text)
    return {"version": v, "errors": errors}
