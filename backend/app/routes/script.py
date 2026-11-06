from __future__ import annotations

import json
import traceback
from typing import Any, Callable, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db, jobs
from app.config import load_config
from app.deps import claude, embedder, project_or_404, rag_config, rag_ready, vector_store
from app.storage import write_script_mirror
from pipeline import rag
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

    if rag_ready():
        return _rag_research(p, c, web)

    def work(progress):
        progress("Researching" + (" (searching the web)" if web else ""), 0.1)
        content, sources = script_mod.research(c, _idea(p), web, p["format"], depth)
        progress("Checking that every source link works", 0.9)
        return db.save_research(project_id, content, script_mod.check_sources(sources))["id"]

    return jobs.start("research", project_id, work)


def _key(project_id: int) -> str:
    return rag.project_key(rag_config()["owner"], project_id)


def _rag_research(p: dict[str, Any], c: Any, web: bool) -> dict[str, Any]:
    """Download 10-15 sources into the vector database (unless the project already has enough), then
    write the brief from the best passages."""
    cfg, store, embed = rag_config(), vector_store(), embedder()
    pid = p["id"]

    def work(progress):
        have = [s for s in db.list_sources(pid) if s["status"] == "ok"]
        if len(have) < cfg["docs_min"]:
            docs = rag.find_sources(c, store, embed, _idea(p), p["format"], _key(pid), cfg,
                                    [s["url"] for s in db.list_sources(pid)], web, progress)
            db.save_sources(pid, docs)
        content, sources = rag.brief_from_store(c, store, embed, _idea(p), p["format"], _key(pid), cfg, progress)
        progress("Checking that every source link works", 0.95)
        return db.save_research(pid, content, script_mod.check_sources(sources))["id"]

    return jobs.start("research", pid, work)


@router.get("/sources")
def list_sources(project_id: int) -> dict[str, Any]:
    project_or_404(project_id)
    return {"rag": rag_ready(), "sources": db.list_sources(project_id)}


@router.post("/sources/more")
def more_sources(project_id: int) -> dict[str, Any]:
    """Download more sources (different from the ones the project has) into the vector database."""
    p = project_or_404(project_id)
    if not rag_ready():
        raise HTTPException(400, "Add the Gemini key and the Supabase database address on the Settings page first.")
    c, cfg, store, embed = claude(), rag_config(), vector_store(), embedder()
    web = load_config()["claude"].get("web_search", True)

    def work(progress):
        docs = rag.find_sources(c, store, embed, _idea(p), p["format"], _key(project_id), cfg,
                                [s["url"] for s in db.list_sources(project_id)], web, progress)
        db.save_sources(project_id, docs)
        return sum(d["status"] == "ok" for d in docs)

    return jobs.start("sources", project_id, work)


@router.delete("/sources/{source_id}")
def remove_source(project_id: int, source_id: int) -> dict[str, Any]:
    """Stop using a source for this project. It stays in the shared database for other videos."""
    project_or_404(project_id)
    s = db.get_source(project_id, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    if s["remote_id"] and rag_ready():
        vector_store().unlink_project(_key(project_id), s["remote_id"])
    db.delete_source(project_id, source_id)
    return {"ok": True}


def _excerpts(fn: Callable[[], str]) -> str:
    """RAG excerpts are a bonus: if the database or Gemini is unreachable, write without them."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 - logged, never blocks writing
        traceback.print_exc()
        return ""


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

    use_rag = rag_ready() and any(s["status"] == "ok" for s in db.list_sources(project_id))

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            excerpts = ""
            if use_rag:
                yield _sse({"type": "status", "text": "Looking up source passages"})
                rc = rag_config()
                excerpts = _excerpts(lambda: rag.script_excerpts(vector_store(), embedder(), _key(project_id),
                                                                 research["content"], _idea(p), rc["script_chunks"]))
            for text in script_mod.generate(c, _idea(p), research["content"], target, body.notes, cfg["wpm_estimate"],
                                            p["format"], excerpts):
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
    excerpts = ""
    if rag_ready() and any(s["status"] == "ok" for s in db.list_sources(project_id)):
        excerpts = _excerpts(lambda: rag.revise_excerpts(vector_store(), embedder(), _key(project_id), body.message))
    result = script_mod.revise(claude(), cur["text"], history, body.message, excerpts)
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
