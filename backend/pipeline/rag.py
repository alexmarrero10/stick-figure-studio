"""Retrieval-augmented research and writing.

1. index_documents: chunk each source, embed it and store it in the vector database. A page that is
   already stored with the same text is reused as is (no new embedding), so the shared corpus grows
   and similar topics get cheaper over time.
2. retrieve: find the chunks that best answer a set of questions, from this project's sources first,
   then (optionally) from the whole shared corpus if they are a close match.
3. write_brief: Claude writes the research brief from the retrieved excerpts only, with no web tools.
4. script_excerpts / revise_excerpts: a small set of excerpts sent with the script and chat requests.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Protocol

from pipeline import procs
from pipeline.chunking import chunk_text
from pipeline.claude_client import Claude
from pipeline.vector_store import text_hash

EmbedFn = Callable[[list[str], str], list[list[float]]]
ProgressFn = Callable[[str, float], None]


class Store(Protocol):
    def find_document(self, url: str) -> dict[str, Any] | None: ...
    def save_document(self, url: str, title: str, source_type: str, text: str, owner: str,
                      chunks: list[dict[str, Any]]) -> int: ...
    def link_project(self, project_key: str, doc_ids: Any) -> None: ...
    def project_documents(self, project_key: str) -> list[int]: ...
    def search(self, query_vec: list[float], query_text: str, k: int = 12, doc_ids: list[int] | None = None,
               min_similarity: float = 0.0) -> list[dict[str, Any]]: ...


def project_key(owner: str, project_id: int) -> str:
    return f"{owner}:{project_id}"


def index_documents(store: Store, embed: EmbedFn, key: str, docs: list[dict[str, Any]], owner: str = "owner",
                    chunk_words: int = 300, overlap_words: int = 50,
                    progress: ProgressFn | None = None,
                    on_stored: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Store every usable document and link it to the project. Returns the docs with `doc_id`,
    `chunks` and `reused` set. Each one is linked (and `on_stored` called) as soon as it is stored,
    so the count on the page goes up while it works and a stopped job keeps what it stored."""
    say = progress or (lambda m, f: None)
    usable = [d for d in docs if d.get("status") == "ok"]
    for n, d in enumerate(usable):
        procs.check()
        say(f"Storing source {n + 1} of {len(usable)}: {d['title'][:60]}", 0.45 + 0.35 * n / max(len(usable), 1))
        existing = store.find_document(d["url"])
        if existing and existing["text_hash"] == text_hash(d["text"]) and existing.get("chunks"):
            d.update(doc_id=existing["id"], chunks=existing["chunks"], reused=True)
        else:
            chunks = chunk_text(d["text"], chunk_words, overlap_words)
            # The title goes into what is embedded, so "the ship" in a chunk still links to its story.
            vecs = embed([f"{d['title']}\n{c['heading']}\n{c['text']}" for c in chunks], "RETRIEVAL_DOCUMENT")
            for c, v in zip(chunks, vecs):
                c["embedding"] = v
            d.update(doc_id=store.save_document(d["url"], d["title"], d["source_type"], d["text"], owner, chunks),
                     chunks=len(chunks), reused=False)
        store.link_project(key, [d["doc_id"]])
        if on_stored:
            on_stored(d)
    return docs


def retrieve(store: Store, embed: EmbedFn, key: str, queries: list[str], k: int = 12, per_query: int = 6,
             shared: bool = True, shared_min_similarity: float = 0.8, shared_max: int = 4) -> list[dict[str, Any]]:
    """Best chunks for several questions at once. Takes the top results of each question in turn
    (round robin), so every question gets some excerpts, and drops duplicates."""
    queries = [q for q in queries if q.strip()]
    if not queries:
        return []
    doc_ids = store.project_documents(key)
    vecs = embed(queries, "RETRIEVAL_QUERY")
    per: list[list[dict[str, Any]]] = []
    for q, v in zip(queries, vecs):
        procs.check()
        hits = store.search(v, q, per_query, doc_ids=doc_ids) if doc_ids else []
        if shared:
            # Close matches from other videos' sources (the shared corpus) can fill gaps.
            own = set(doc_ids)
            more = [h for h in store.search(v, q, per_query, min_similarity=shared_min_similarity)
                    if h["document_id"] not in own][:2]
            hits += [{**h, "shared": True} for h in more]
        per.append(hits)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    shared_n = 0
    for rank in range(max((len(h) for h in per), default=0)):
        for hits in per:
            if rank < len(hits) and len(out) < k:
                h = hits[rank]
                if h["id"] in seen or (h.get("shared") and shared_n >= shared_max):
                    continue
                seen.add(h["id"])
                shared_n += bool(h.get("shared"))
                out.append(h)
    return out


def number_sources(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, int]]:
    """Give each source document a number [1], [2]... in order of first appearance."""
    sources: list[dict[str, Any]] = []
    num: dict[int, int] = {}
    for c in chunks:
        if c["document_id"] not in num:
            num[c["document_id"]] = len(sources) + 1
            sources.append({"n": num[c["document_id"]], "title": c["title"], "url": c["url"]})
    return sources, num


def format_excerpts(chunks: list[dict[str, Any]], max_words: int | None = None) -> str:
    """Excerpts grouped by source, each source labelled with its number and URL."""
    sources, num = number_sources(chunks)
    by_doc: dict[int, list[dict[str, Any]]] = {}
    words = 0
    for c in chunks:
        n = len(c["text"].split())
        if max_words and words + n > max_words and words:
            break
        words += n
        by_doc.setdefault(c["document_id"], []).append(c)
    parts = []
    for s in sources:
        doc_id = next(d for d, n in num.items() if n == s["n"])
        if doc_id not in by_doc:
            continue
        body = "\n\n".join((f"({c['heading']}) " if c.get("heading") else "") + c["text"]
                           for c in sorted(by_doc[doc_id], key=lambda c: c.get("ord", 0)))
        parts.append(f"[{s['n']}] {s['title']} <{s['url']}>\n{body}")
    return "\n\n---\n\n".join(parts)


# --- research brief from the sources ----------------------------------------

def section_queries(idea: dict[str, Any], sections_text: str) -> list[str]:
    """One search question per brief section, e.g. 'Franklin's lost ships: Timeline (dated bullet points)'."""
    title = idea.get("title", "")
    out = [f"{title}. {idea.get('hook', '')}".strip()]
    for line in sections_text.splitlines():
        m = re.match(r"\s*#{2,3}\s+(.+)", line)
        if m:
            out.append(f"{title}: {m.group(1).strip()[:160]}")
    return out


BRIEF_RULES = """SOURCES (this replaces the web search rules above)
- You are given numbered excerpts from {n} sources that were already downloaded for this topic. \
Use only these excerpts. Do not add facts from memory, and do not search the web.
- Mark every fact with the number of its source, like [3]. If excerpts disagree, say so under \
"Uncertain or disputed".
- If the excerpts don't cover a section well, write what they support and say plainly what is missing.
- Under ## Sources, list only the sources you cited, keeping their numbers: \
3. [Title](https://the-given-url). Use the exact URLs given."""


def write_brief(claude: Claude, idea: dict[str, Any], format: str, chunks: list[dict[str, Any]],
                research_system: str, sections: str, max_words: int = 9000) -> tuple[str, list[dict[str, str]]]:
    """The research brief, written by Claude from the retrieved excerpts with no tools."""
    sources, _ = number_sources(chunks)
    # Swap the web-research SOURCES rules for the excerpt rules; keep the rest of the system prompt.
    head = research_system.split("SOURCES\n", 1)[0]
    tail = research_system.split("Write the brief in Markdown.", 1)[-1]
    sys_text = head + BRIEF_RULES.replace("{n}", str(len(sources))) + "\n\nWrite the brief in Markdown." + tail
    msg = (f"Write the research brief for a narrated video.\n\nTitle: {idea.get('title', '')}\n"
           f"Hook: {idea.get('hook', '')}\nNotes: {idea.get('documentation', '')}\n\n{sections}\n\n"
           f"SOURCE EXCERPTS\n\n{format_excerpts(chunks, max_words)}")
    final = claude.complete(sys_text, [{"role": "user", "content": msg}], max_tokens=16000, effort="medium")
    text = Claude.text_of(final).strip()
    i = text.find("## Summary")
    if i > 0:
        text = text[i:]
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    used = [s for s in sources if s["n"] in cited] or sources
    return text, [{"title": s["title"], "url": s["url"]} for s in used]


def find_sources(claude: Claude, store: Store, embed: EmbedFn, idea: dict[str, Any], format: str, key: str,
                 cfg: dict[str, Any], exclude: list[str] | None = None, web_search: bool = True,
                 progress: ProgressFn | None = None,
                 on_stored: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Download sources for the project and store them in the vector database."""
    from pipeline import sources
    docs = sources.gather(claude, idea, format, cfg["docs_min"], cfg["docs_max"], exclude, web_search, progress)
    return index_documents(store, embed, key, docs, cfg.get("owner", "owner"), cfg["chunk_words"],
                           cfg["overlap_words"], progress, on_stored)


def brief_from_store(claude: Claude, store: Store, embed: EmbedFn, idea: dict[str, Any], format: str, key: str,
                     cfg: dict[str, Any], progress: ProgressFn | None = None) -> tuple[str, list[dict[str, str]]]:
    """Retrieve excerpts for each brief section and have Claude write the brief from them."""
    from pipeline.script import RESEARCH_SECTIONS, RESEARCH_SYSTEM
    say = progress or (lambda m, f: None)
    sections = RESEARCH_SECTIONS.get(format, RESEARCH_SECTIONS["story"])
    say("Finding the best passages for each part of the brief", 0.82)
    chunks = retrieve(store, embed, key, section_queries(idea, sections), k=cfg["brief_chunks"],
                      shared=cfg.get("use_shared", True))
    if not chunks:
        raise RuntimeError("No usable sources were found for this topic. Try again, or turn off "
                           "'Research from downloaded sources' on the Settings page.")
    say(f"Writing the brief from {len(chunks)} passages (no web search needed)", 0.86)
    return write_brief(claude, idea, format, chunks, RESEARCH_SYSTEM, sections)


# --- excerpts for the script and chat ---------------------------------------

def brief_queries(brief: str, idea: dict[str, Any], limit: int = 10) -> list[str]:
    """Questions to look up for the script: the brief's turning points (or entries) and key facts."""
    title = idea.get("title", "")
    picks: list[str] = []
    section = ""
    for line in brief.splitlines():
        m = re.match(r"\s*#{2,3}\s+(.+)", line)
        if m:
            section = m.group(1).lower()
            if line.lstrip().startswith("### "):  # list entries: one query each
                picks.append(m.group(1))
            continue
        if any(s in section for s in ("turning points", "key facts", "real cases")):
            b = re.match(r"\s*(?:[-*]|\d+\.)\s+(.+)", line)
            if b:
                picks.append(re.sub(r"\[\d+\]", "", b.group(1)).strip()[:200])
    picks = picks[:limit] or [title]
    return [f"{title}: {p}" for p in picks]


SCRIPT_EXCERPT_RULE = ("SOURCE EXCERPTS: below the brief are excerpts from the downloaded sources. Use them "
                       "to check facts and to add vivid, accurate detail. Every fact must come from the brief "
                       "or these excerpts.")


def script_excerpts(store: Store, embed: EmbedFn, key: str, brief: str, idea: dict[str, Any], k: int = 10,
                    max_words: int = 2500) -> str:
    chunks = retrieve(store, embed, key, brief_queries(brief, idea), k=k, per_query=3)
    return format_excerpts(chunks, max_words) if chunks else ""


def fact_check_excerpts(store: Store, embed: EmbedFn, key: str, script: str, k: int = 24,
                        max_words: int = 5000) -> str:
    """Passages for the fact check: the best two for each paragraph of the script, from this project's sources."""
    from pipeline.fact_check import paragraph_queries
    chunks = retrieve(store, embed, key, paragraph_queries(script), k=k, per_query=2, shared=False)
    return format_excerpts(chunks, max_words) if chunks else ""


def revise_excerpts(store: Store, embed: EmbedFn, key: str, instruction: str, k: int = 5,
                    max_words: int = 1200) -> str:
    chunks = retrieve(store, embed, key, [instruction], k=k, per_query=k, shared=False)
    return format_excerpts(chunks, max_words) if chunks else ""
