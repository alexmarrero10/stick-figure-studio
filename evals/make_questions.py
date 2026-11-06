"""Write the test questions once (Claude), so every later run is scored on the same set.

For every published video: one question per narration window (we then know which window holds the
answer) plus a few questions the video does NOT answer. For every project with research sources: one
question for each of up to 20 sampled passages. Saved to evals/data/questions.json.

    .venv\\Scripts\\python evals\\make_questions.py            # adds videos/projects not in the set yet
    .venv\\Scripts\\python evals\\make_questions.py --refresh  # writes the whole set again
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime

import common
from pipeline.claude_client import INT, STR, arr, obj

QUESTION_SYSTEM = """You write test questions for a search system over a narrated history video.

You get numbered passages. For EACH passage write one question that a curious viewer might type, \
which that passage answers on its own.
- Use your own everyday words. Don't copy distinctive phrases from the passage, so the search has to \
match the meaning, not the exact words. Names of people and places are fine.
- Under 15 words. Ask about the passage's main fact, not a tiny detail.
- The question must make sense without having seen the passage (no "in this passage").

Also write {n_unanswerable} questions a viewer might plausibly ask about this topic that NONE of the \
passages answer (for example a related fact, a later event, or a detail the video never gives)."""

SCHEMA = obj({"questions": arr(obj({"passage": INT, "question": STR})), "unanswerable": arr(STR)})


def ask(passages: list[str], n_unanswerable: int) -> dict:
    numbered = "\n\n".join(f"PASSAGE {i}:\n{t}" for i, t in enumerate(passages))
    return common.claude().json(QUESTION_SYSTEM.format(n_unanswerable=n_unanswerable),
                                [{"role": "user", "content": numbered}], SCHEMA, effort="medium")


def for_video(v: dict) -> dict:
    windows = common.video_windows(v["id"])
    print(f"  {v['title']}: {len(windows)} narration windows")
    res = ask([w["text"] for w in windows], 6)
    qs = [{"q": x["question"].strip(), "ord": windows[x["passage"]]["ord"],
           "start_s": windows[x["passage"]]["start_s"], "end_s": windows[x["passage"]]["end_s"],
           "text": windows[x["passage"]]["text"]}
          for x in res["questions"] if 0 <= x["passage"] < len(windows) and x["question"].strip()]
    return {"video_id": v["id"], "title": v["title"], "project_key": v["project_key"], "questions": qs,
            "unanswerable": [u.strip() for u in res["unanswerable"] if u.strip()]}


def source_projects() -> list[str]:
    with common.studio_store()._conn() as c:
        return [r["project_key"] for r in c.execute(
            "select project_key from project_documents group by project_key having count(*) > 0 order by project_key")]


def for_sources(project_key: str, sample: int = 20) -> dict:
    store = common.studio_store()
    doc_ids = store.project_documents(project_key)
    with store._conn() as c:
        chunks = c.execute("select c.document_id, c.ord, c.text, d.title from chunks c join documents d "
                           "on d.id = c.document_id where c.document_id = any(%s) order by c.id", (doc_ids,)).fetchall()
    picked = random.Random(7).sample(chunks, min(sample, len(chunks)))
    print(f"  {project_key}: {len(doc_ids)} sources, {len(chunks)} passages, {len(picked)} sampled")
    res = ask([f"(from {c['title']})\n{c['text']}" for c in picked], 0)
    qs = [{"q": x["question"].strip(), "document_id": picked[x["passage"]]["document_id"],
           "ord": picked[x["passage"]]["ord"], "source": picked[x["passage"]]["title"]}
          for x in res["questions"] if 0 <= x["passage"] < len(picked) and x["question"].strip()]
    return {"project_key": project_key, "questions": qs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="write every question again")
    args = ap.parse_args()
    data = (None if args.refresh else common.load("questions.json")) or {"videos": [], "sources": []}
    have_v = {x["video_id"] for x in data["videos"]}
    have_s = {x["project_key"] for x in data["sources"]}

    print("Videos:")
    for v in common.videos():
        if v["id"] not in have_v:
            data["videos"].append(for_video(v))
    print("Research sources:")
    for key in source_projects():
        if key not in have_s:
            data["sources"].append(for_sources(key))
    data["made_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    common.save("questions.json", data)
    n = sum(len(x["questions"]) for x in data["videos"]) + sum(len(x["questions"]) for x in data["sources"])
    print(f"\nSaved {n} questions to {common.DATA / 'questions.json'}")


if __name__ == "__main__":
    main()
