"""The vector database: source documents, their chunks and embeddings, and hybrid search.

`PgStore` talks to Postgres + pgvector (Supabase, see backend/supabase/schema.sql) with plain SQL.
`MemoryStore` does the same in memory and is used by the tests.

Search is hybrid: vector similarity (meaning) and full-text keywords (exact names, dates), merged with
reciprocal rank fusion. Names and numbers matter a lot in history scripts, and pure vector search
is weak at them.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Iterable

RRF_K = 60


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def rrf(*rankings: list[int], k: int = RRF_K) -> list[int]:
    """Reciprocal rank fusion: merge several ranked id lists into one."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=lambda c: -score[c])


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class PgStore:
    def __init__(self, url: str):
        if not url:
            raise ValueError("SUPABASE_DB_URL is not set. Add it on the Settings page.")
        self.url = url

    def _conn(self):
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: Supabase's connection pooler doesn't support prepared statements.
        return psycopg.connect(self.url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)

    def ping(self) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("select count(*) as docs from documents").fetchone()
            chunks = c.execute("select count(*) as n from chunks").fetchone()
        return {"documents": row["docs"], "chunks": chunks["n"]}

    def find_document(self, url: str) -> dict[str, Any] | None:
        with self._conn() as c:
            return c.execute("select d.*, (select count(*) from chunks where document_id = d.id) as chunks "
                             "from documents d where url = %s", (url,)).fetchone()

    def save_document(self, url: str, title: str, source_type: str, text: str, owner: str,
                      chunks: list[dict[str, Any]]) -> int:
        """Insert or replace a document and all its chunks (each chunk has an `embedding`)."""
        with self._conn() as c, c.transaction():
            row = c.execute(
                "insert into documents (url, title, source_type, text_hash, words, owner) "
                "values (%s, %s, %s, %s, %s, %s) on conflict (url) do update set title = excluded.title, "
                "source_type = excluded.source_type, text_hash = excluded.text_hash, words = excluded.words, "
                "fetched_at = now() returning id",
                (url, title, source_type, text_hash(text), len(text.split()), owner)).fetchone()
            doc_id = row["id"]
            c.execute("delete from chunks where document_id = %s", (doc_id,))
            with c.cursor() as cur:
                cur.executemany(
                    "insert into chunks (document_id, ord, heading, text, embedding) values (%s, %s, %s, %s, %s::vector)",
                    [(doc_id, ch["ord"], ch.get("heading", ""), ch["text"], _vec(ch["embedding"])) for ch in chunks])
        return doc_id

    def link_project(self, project_key: str, doc_ids: Iterable[int]) -> None:
        with self._conn() as c, c.transaction():
            for d in doc_ids:
                c.execute("insert into project_documents (project_key, document_id) values (%s, %s) "
                          "on conflict do nothing", (project_key, d))

    def unlink_project(self, project_key: str, doc_id: int) -> None:
        with self._conn() as c:
            c.execute("delete from project_documents where project_key = %s and document_id = %s",
                      (project_key, doc_id))

    def project_documents(self, project_key: str) -> list[int]:
        with self._conn() as c:
            return [r["document_id"] for r in c.execute(
                "select document_id from project_documents where project_key = %s", (project_key,))]

    def search(self, query_vec: list[float], query_text: str, k: int = 12,
               doc_ids: list[int] | None = None, min_similarity: float = 0.0) -> list[dict[str, Any]]:
        n = max(k * 4, 20)
        where, params = "", []
        if doc_ids is not None:
            if not doc_ids:
                return []
            where = "where c.document_id = any(%s)"
            params = [doc_ids]
        q = _vec(query_vec)
        with self._conn() as c:
            vec = c.execute(
                f"select c.id, 1 - (c.embedding <=> %s::vector) as sim from chunks c {where} "
                f"order by c.embedding <=> %s::vector limit %s", [q, *params, q, n]).fetchall()
            kw = c.execute(
                f"select c.id from chunks c {where + (' and' if where else 'where')} "
                f"c.tsv @@ websearch_to_tsquery('english', %s) "
                f"order by ts_rank(c.tsv, websearch_to_tsquery('english', %s)) desc limit %s",
                [*params, query_text, query_text, n]).fetchall()
            sims = {r["id"]: r["sim"] for r in vec}
            ids = [i for i in rrf([r["id"] for r in vec if r["sim"] >= min_similarity],
                                  [r["id"] for r in kw]) if sims.get(i, 1.0) >= min_similarity][:k]
            if not ids:
                return []
            rows = c.execute(
                "select c.id, c.document_id, c.ord, c.heading, c.text, d.url, d.title "
                "from chunks c join documents d on d.id = c.document_id where c.id = any(%s)", (ids,)).fetchall()
        by_id = {r["id"]: r for r in rows}
        return [{**by_id[i], "similarity": sims.get(i)} for i in ids if i in by_id]

    # -- published videos (the public site) ---------------------------------

    def publish_video(self, project_key: str, owner: str, video: dict[str, Any], chunks: list[dict[str, Any]]) -> int:
        """Insert or update a video and replace its narration windows. Returns videos.id."""
        with self._conn() as c, c.transaction():
            row = c.execute(
                "insert into videos (project_key, owner, title, summary, description, youtube_id, thumbnail_url, "
                "duration_s) values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (project_key) do update set "
                "title = excluded.title, summary = excluded.summary, description = excluded.description, "
                "youtube_id = excluded.youtube_id, thumbnail_url = excluded.thumbnail_url, "
                "duration_s = excluded.duration_s returning id",
                (project_key, owner, video["title"], video["summary"], video["description"], video["youtube_id"],
                 video["thumbnail_url"], video["duration_s"])).fetchone()
            vid = row["id"]
            c.execute("delete from video_chunks where video_id = %s", (vid,))
            with c.cursor() as cur:
                cur.executemany(
                    "insert into video_chunks (video_id, ord, start_s, end_s, text, embedding) "
                    "values (%s, %s, %s, %s, %s, %s::vector)",
                    [(vid, ch["ord"], ch["start_s"], ch["end_s"], ch["text"], _vec(ch["embedding"])) for ch in chunks])
        return vid

    def unpublish_video(self, project_key: str) -> None:
        with self._conn() as c:
            c.execute("delete from videos where project_key = %s", (project_key,))


class MemoryStore:
    """Same interface as PgStore, in memory (for tests and trying things without Supabase)."""

    def __init__(self) -> None:
        self.documents: dict[int, dict[str, Any]] = {}
        self.chunks: dict[int, dict[str, Any]] = {}
        self.links: set[tuple[str, int]] = set()
        self.videos: dict[int, dict[str, Any]] = {}
        self.video_chunks: dict[int, list[dict[str, Any]]] = {}
        self._next_doc = 1
        self._next_chunk = 1
        self._next_video = 1

    def publish_video(self, project_key: str, owner: str, video: dict[str, Any], chunks: list[dict[str, Any]]) -> int:
        vid = next((v["id"] for v in self.videos.values() if v["project_key"] == project_key), None)
        if vid is None:
            vid = self._next_video
            self._next_video += 1
        self.videos[vid] = {**video, "id": vid, "project_key": project_key, "owner": owner}
        self.video_chunks[vid] = [dict(c) for c in chunks]
        return vid

    def unpublish_video(self, project_key: str) -> None:
        for vid in [v["id"] for v in self.videos.values() if v["project_key"] == project_key]:
            del self.videos[vid]
            self.video_chunks.pop(vid, None)

    def ping(self) -> dict[str, Any]:
        return {"documents": len(self.documents), "chunks": len(self.chunks)}

    def find_document(self, url: str) -> dict[str, Any] | None:
        for d in self.documents.values():
            if d["url"] == url:
                return {**d, "chunks": sum(1 for c in self.chunks.values() if c["document_id"] == d["id"])}
        return None

    def save_document(self, url: str, title: str, source_type: str, text: str, owner: str,
                      chunks: list[dict[str, Any]]) -> int:
        existing = self.find_document(url)
        doc_id = existing["id"] if existing else self._next_doc
        if not existing:
            self._next_doc += 1
        self.documents[doc_id] = {"id": doc_id, "url": url, "title": title, "source_type": source_type,
                                  "text_hash": text_hash(text), "words": len(text.split()), "owner": owner}
        self.chunks = {i: c for i, c in self.chunks.items() if c["document_id"] != doc_id}
        for ch in chunks:
            self.chunks[self._next_chunk] = {"id": self._next_chunk, "document_id": doc_id, "ord": ch["ord"],
                                             "heading": ch.get("heading", ""), "text": ch["text"],
                                             "embedding": ch["embedding"]}
            self._next_chunk += 1
        return doc_id

    def link_project(self, project_key: str, doc_ids: Iterable[int]) -> None:
        self.links.update((project_key, d) for d in doc_ids)

    def unlink_project(self, project_key: str, doc_id: int) -> None:
        self.links.discard((project_key, doc_id))

    def project_documents(self, project_key: str) -> list[int]:
        return sorted(d for p, d in self.links if p == project_key)

    def search(self, query_vec: list[float], query_text: str, k: int = 12,
               doc_ids: list[int] | None = None, min_similarity: float = 0.0) -> list[dict[str, Any]]:
        pool = [c for c in self.chunks.values() if doc_ids is None or c["document_id"] in doc_ids]
        sims = {c["id"]: _cos(query_vec, c["embedding"]) for c in pool}
        vec = sorted((c["id"] for c in pool if sims[c["id"]] >= min_similarity), key=lambda i: -sims[i])
        terms = {t for t in re.findall(r"\w+", query_text.lower()) if len(t) > 2}
        hits = {c["id"]: sum(t in c["text"].lower() for t in terms) for c in pool}
        kw = sorted((i for i, h in hits.items() if h and sims[i] >= min_similarity), key=lambda i: -hits[i])
        out = []
        for i in rrf(vec, kw)[:k]:
            c = self.chunks[i]
            d = self.documents[c["document_id"]]
            out.append({"id": i, "document_id": d["id"], "ord": c["ord"], "heading": c["heading"],
                        "text": c["text"], "url": d["url"], "title": d["title"], "similarity": sims[i]})
        return out


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
