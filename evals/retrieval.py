"""Layer 1: does retrieval find the right passage? Free (only Gemini embeddings), objective, quick.

For each saved question we know which passage holds the answer, and check where it ranks:
- the chatbot's narration search (it reads the top 6 windows), hybrid vs vector-only,
- the research-source search (the chatbot reads the top 3; the studio reads more), hybrid vs vector-only,
- the search bar: is the right video first? And do off-topic searches return nothing?

    .venv\\Scripts\\python evals\\retrieval.py
"""
from __future__ import annotations

import common
import scoring as sc


def vector_only_moments(vec: list[float], video_id: int, k: int = 10) -> list[int]:
    from store import _vec
    with common.site().reader()._conn() as c:
        return [r["ord"] for r in c.execute(
            "select ord from video_chunks where video_id = %s order by embedding <=> %s::vector limit %s",
            (video_id, _vec(vec), k))]


def vector_only_chunks(store, vec: list[float], doc_ids: list[int], k: int = 10) -> list[tuple[int, int]]:
    from pipeline.vector_store import _vec
    with store._conn() as c:
        return [(r["document_id"], r["ord"]) for r in c.execute(
            "select document_id, ord from chunks where document_id = any(%s) order by embedding <=> %s::vector "
            "limit %s", (doc_ids, _vec(vec), k))]


def embed(q: str) -> list[float]:
    return common.retry(common.site().gemini().embed_query, q)


def main() -> None:
    data = common.need_questions()
    site = common.site()
    attacks = common.load("attacks.json") or {}
    rows, misses, details = [], [], {"narration": [], "sources": [], "search": [], "search_off_topic": []}

    # 1. Narration windows (what the chatbot answers from).
    print("Narration search...")
    hyb, vec_r, near = [], [], []
    for v in data["videos"]:
        for item in v["questions"]:
            qv = embed(item["q"])
            ranked = [m["ord"] for m in site.reader().search_moments(qv, item["q"], k=10, video_id=v["video_id"])]
            r_h, r_v = sc.rank_of(item["ord"], ranked), sc.rank_of(item["ord"], vector_only_moments(qv, v["video_id"]))
            hyb.append(r_h), vec_r.append(r_v), near.append(sc.near_rank(item["ord"], ranked))
            details["narration"].append({**item, "video": v["title"], "hybrid_rank": r_h, "vector_rank": r_v,
                                         "top": ranked[:3]})
            if r_h is None or r_h > 6:
                misses.append([v["title"][:30], item["q"], item["ord"], ranked[:3], r_h or "-"])
    if hyb:
        h, vv, nr = sc.retrieval_scores(hyb), sc.retrieval_scores(vec_r), sc.retrieval_scores(near)
        rows.append(["Narration (hybrid, used now)", len(hyb), sc.pct(h["hit@1"]), sc.pct(h["hit@3"]),
                     sc.pct(h["hit@6"]), f"{h['mrr']:.2f}", sc.pct(nr["hit@6"])])
        rows.append(["Narration (vector only)", len(vec_r), sc.pct(vv["hit@1"]), sc.pct(vv["hit@3"]),
                     sc.pct(vv["hit@6"]), f"{vv['mrr']:.2f}", ""])

    # 2. Research sources.
    print("Research-source search...")
    store = common.studio_store()
    s_h, s_v, s_n = [], [], []
    for proj in data["sources"]:
        doc_ids = store.project_documents(proj["project_key"])
        for item in proj["questions"]:
            qv = embed(item["q"])
            found = store.search(qv, item["q"], k=10, doc_ids=doc_ids)
            ranked = [(f["document_id"], f["ord"]) for f in found]
            gold = (item["document_id"], item["ord"])
            r_h = sc.rank_of(gold, ranked)
            r_v = sc.rank_of(gold, vector_only_chunks(store, qv, doc_ids))
            r_n = sc.near_rank(item["ord"], [o for _, o in ranked], [d == item["document_id"] for d, _ in ranked])
            s_h.append(r_h), s_v.append(r_v), s_n.append(r_n)
            details["sources"].append({**item, "project_key": proj["project_key"], "hybrid_rank": r_h,
                                       "vector_rank": r_v, "near_rank": r_n})
            if r_h is None or r_h > 6:
                misses.append([item["source"][:30], item["q"], item["ord"], [o for _, o in ranked[:3]], r_h or "-"])
    if s_h:
        h, vv, nr = sc.retrieval_scores(s_h), sc.retrieval_scores(s_v), sc.retrieval_scores(s_n)
        rows.append(["Sources (hybrid, used now)", len(s_h), sc.pct(h["hit@1"]), sc.pct(h["hit@3"]),
                     sc.pct(h["hit@6"]), f"{h['mrr']:.2f}", sc.pct(nr["hit@6"])])
        rows.append(["Sources (vector only)", len(s_v), sc.pct(vv["hit@1"]), sc.pct(vv["hit@3"]),
                     sc.pct(vv["hit@6"]), f"{vv['mrr']:.2f}", ""])

    # 3. The search bar.
    print("Search bar...")
    first = []
    for v in data["videos"]:
        for item in v["questions"]:
            ids = [x["id"] for x in common.retry(site.find_videos, item["q"])]
            r = sc.rank_of(v["video_id"], ids)
            first.append(r)
            details["search"].append({"q": item["q"], "video": v["title"], "rank": r, "results": len(ids)})
    empty = []
    for q in attacks.get("search_off_topic", []):
        n = len(common.retry(site.find_videos, q))
        empty.append(n == 0)
        details["search_off_topic"].append({"q": q, "results": n})

    body = [
        "How often the passage that holds the answer comes back. **hit@6** matters most for narration (the "
        "chatbot reads 6 windows), **hit@3** for sources (it reads 3). **Near** also counts the passage next "
        "to it, which often holds the same fact.\n",
        sc.md_table(["Search", "Questions", "hit@1", "hit@3", "hit@6", "MRR", "Near hit@6"], rows),
    ]
    sr = sc.retrieval_scores(first, ks=(1,))
    body.append(f"\n**Search bar:** right video first for {sc.pct(sr['hit@1'])} of {len(first)} questions. "
                f"Off-topic searches with no results: {sum(empty)} of {len(empty)}"
                + (f" ({sc.pct(sum(empty) / len(empty))})." if empty else "."))
    if misses:
        body.append(f"\n## Misses (answer not in the top 6): {len(misses)}\n")
        body.append(sc.md_table(["Where", "Question", "Answer is in #", "Top 3 found", "Rank"], misses[:25]))
    headline = {"narration_hit6": sc.retrieval_scores(hyb)["hit@6"] if hyb else None,
                "sources_hit3": sc.retrieval_scores(s_h)["hit@3"] if s_h else None,
                "search_first": sr["hit@1"] if first else None}
    common.report("retrieval", "Layer 1: retrieval", "\n".join(body), headline, details)


if __name__ == "__main__":
    main()
