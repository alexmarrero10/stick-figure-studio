"""Read-only access to the site database (Supabase Postgres + pgvector).

The site never writes. It connects as the `site_reader` user (see backend/supabase/002_site_reader.sql).
"""
from __future__ import annotations

from typing import Any

RRF_K = 60
VIDEO_COLS = "id, title, summary, description, youtube_id, thumbnail_url, duration_s, published_at"


def rrf(*rankings: list[int], k: int = RRF_K) -> list[int]:
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=lambda c: -score[c])


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class PgReader:
    def __init__(self, url: str):
        if not url:
            raise ValueError("SITE_DATABASE_URL is not set.")
        self.url = url
        self._pool = None

    def _conn(self):
        """A connection from a small pool. Opening a new one to Supabase takes about a second; reusing is instant."""
        if self._pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(
                self.url, min_size=1, max_size=5, open=True, check=ConnectionPool.check_connection,
                max_idle=300, kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 15,
                                      "autocommit": True})
        return self._pool.connection()

    def list_videos(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            return c.execute(f"select {VIDEO_COLS} from videos order by published_at desc").fetchall()

    def get_video(self, video_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            v = c.execute(f"select {VIDEO_COLS}, project_key from videos where id = %s", (video_id,)).fetchone()
        return v

    def search_moments(self, query_vec: list[float], query_text: str, k: int = 30,
                       video_id: int | None = None) -> list[dict[str, Any]]:
        """Hybrid search over narration windows (vector + keywords, fused). Optionally one video only."""
        where, params = ("where c.video_id = %s", [video_id]) if video_id else ("", [])
        q = _vec(query_vec)
        with self._conn() as c:
            vec = c.execute(
                f"select c.id from video_chunks c {where} order by c.embedding <=> %s::vector limit %s",
                [*params, q, k]).fetchall()
            kw = c.execute(
                f"select c.id from video_chunks c {where + (' and' if where else 'where')} "
                f"c.tsv @@ websearch_to_tsquery('english', %s) "
                f"order by ts_rank(c.tsv, websearch_to_tsquery('english', %s)) desc limit %s",
                [*params, query_text, query_text, k]).fetchall()
            ids = rrf([r["id"] for r in vec], [r["id"] for r in kw])[:k]
            if not ids:
                return []
            rows = c.execute(
                "select c.id, c.video_id, c.ord, c.start_s, c.end_s, c.text, 1 - (c.embedding <=> %s::vector) as similarity "
                "from video_chunks c where c.id = any(%s)", (q, ids)).fetchall()
        kw_ids = {r["id"] for r in kw}
        by_id = {r["id"]: {**r, "keyword": r["id"] in kw_ids} for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def moments_near(self, video_id: int, at_s: float, n: int = 1) -> list[dict[str, Any]]:
        """The narration window playing at `at_s`, plus `n` before it."""
        with self._conn() as c:
            return c.execute(
                "select id, video_id, ord, start_s, end_s, text from video_chunks where video_id = %s and start_s <= %s "
                "order by start_s desc limit %s", (video_id, at_s, n + 1)).fetchall()[::-1]

    def search_sources(self, project_key: str, query_vec: list[float], k: int = 3) -> list[dict[str, Any]]:
        """Research passages from the sources this video was made from (background facts)."""
        with self._conn() as c:
            return c.execute(
                "select ch.id, ch.text, ch.heading, d.title, d.url from chunks ch join documents d on d.id = ch.document_id "
                "join project_documents pd on pd.document_id = d.id where pd.project_key = %s "
                "order by ch.embedding <=> %s::vector limit %s", (project_key, _vec(query_vec), k)).fetchall()
