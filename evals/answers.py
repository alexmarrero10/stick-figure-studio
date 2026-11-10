"""Layer 2: are the chatbot's answers correct, backed by the video, and properly timestamped?

Asks the real chatbot (same code and model as the site) a sample of the saved questions with known
answers, the questions the video does NOT answer, and a summary request. Then:
- in code: does every cited [m:ss] point to a narration window the answer was given? Does it cite the
  window that actually holds the answer?
- Claude judges each answer: grounded (every claim backed by the passages), correct (matches the known
  passage), and for unanswerable questions, whether it said so instead of inventing facts.

Uses Gemini's free tier (one answer per question) and Claude on your plan for judging.

    .venv\\Scripts\\python evals\\answers.py               # 8 known-answer questions per video
    .venv\\Scripts\\python evals\\answers.py --per-video 15
"""
from __future__ import annotations

import argparse
import random
import time

import common
import scoring as sc
from pipeline.claude_client import INT, STR, arr, obj

JUDGE_SYSTEM = """You grade a history-video chatbot's answers. Be strict and fair.

Each item has the PASSAGES the chatbot was given, the QUESTION, its ANSWER and the EXPECTED part:
either the passage that holds the right answer, or "UNANSWERABLE" when the video doesn't cover it.

For each item give:
- grounded: "yes" if every factual claim in the answer is supported by the passages, "partly" if some \
claims are not, "no" if the main claims are not. Saying "the video doesn't cover that" counts as grounded, \
and so do claims the answer clearly labels as general knowledge (e.g. "the video and its sources don't \
cover that, but from general history: ...") as long as they aren't false.
- correct: for answerable questions, "yes" if it answers the question in line with the expected \
passage, "partly" if incomplete or slightly off, "no" if wrong or it wrongly said the video doesn't \
cover it. "n/a" for unanswerable questions.
- handled_unanswerable: for UNANSWERABLE items, "yes" if it said the video doesn't cover it (it may add \
related facts from the passages, or a general-knowledge answer clearly labeled as such), "no" if it \
presented an answer not found in the passages as if the video or its sources said it. "n/a" otherwise.
- note: one short sentence on the main problem, or "" if none."""

JUDGE_SCHEMA = obj({"grades": arr(obj({"id": INT, "grounded": STR, "correct": STR,
                                        "handled_unanswerable": STR, "note": STR}))})


def judge(items: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for start in range(0, len(items), 6):
        batch = items[start:start + 6]
        parts = []
        for i in batch:
            expected = "UNANSWERABLE" if i["kind"] == "unanswerable" else (
                "SUMMARY REQUEST (judge correct as: a fair summary of the passages)" if i["kind"] == "summary"
                else f"[{i['start_s']:.0f}-{i['end_s']:.0f} s] {i['gold_text']}")
            parts.append(f"=== ITEM {i['id']} ===\nPASSAGES:\n{i['context']}\n\nQUESTION: {i['q']}\n"
                         f"ANSWER: {i['answer']}\n\nEXPECTED: {expected}")
        res = common.claude().json(JUDGE_SYSTEM, [{"role": "user", "content": "\n\n".join(parts)}],
                                   JUDGE_SCHEMA, effort="medium")
        out.update({g["id"]: g for g in res["grades"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-video", type=int, default=8, help="known-answer questions per video")
    args = ap.parse_args()
    site = common.site()
    data = common.need_questions()
    live = {v["id"]: v for v in common.videos()}

    items = []
    for sv in data["videos"]:
        v = live.get(sv["video_id"])
        if not v:
            print(f"Skipping {sv['title']}: not on the site any more (run make_questions.py --refresh)")
            continue
        picked = random.Random(sv["video_id"]).sample(sv["questions"], min(args.per_video, len(sv["questions"])))
        items += [{"video": v, "kind": "known", "q": x["q"], "start_s": x["start_s"], "end_s": x["end_s"],
                   "gold_text": x["text"]} for x in picked]
        items += [{"video": v, "kind": "unanswerable", "q": q} for q in sv["unanswerable"]]
        items.append({"video": v, "kind": "summary", "q": "Can you summarize this video?"})

    print(f"Asking the chatbot {len(items)} questions...")
    for i, it in enumerate(items):
        it["id"] = i
        found = common.retry(site.gather, it["video"], it["q"])
        it["context"], it["score"] = found["context"], round(found["relevance"], 3)
        windows = found["moments"] + found["near"]
        if found["relevance"] < site.CHAT_MIN_SIMILARITY:
            it["answer"], it["gated"] = site.OFF_TOPIC_TEXT, True
            continue
        t0 = time.time()
        it["answer"] = common.answer(site.CHAT_SYSTEM, site.chat_contents([], it["context"], it["q"])) \
            or site.NO_ANSWER_TEXT
        it["seconds"], it["gated"] = round(time.time() - t0, 2), False
        times = sc.parse_times(it["answer"])
        it["citations_valid"], it["citations"] = sc.citation_check(times, windows)
        if it["kind"] == "known":
            it["cites_answer"] = any(sc.in_window(t, it["start_s"], it["end_s"]) for t in times)
        print(f"  {i + 1}/{len(items)}")

    answered = [it for it in items if not it["gated"]]
    print(f"Claude is grading {len(answered)} answers...")
    grades = judge(answered)
    for it in answered:
        g = grades.get(it["id"], {})
        it.update({k: g.get(k, "unknown") for k in ("grounded", "correct", "handled_unanswerable")})
        it["note"] = g.get("note", "")

    known = [it for it in items if it["kind"] == "known"]
    unans = [it for it in items if it["kind"] == "unanswerable"]
    cites = sum(it.get("citations", 0) for it in answered)
    valid = sum(it.get("citations_valid", 0) for it in answered)
    gated_real = [it for it in items if it["gated"]]
    k_ans = [it for it in known if not it["gated"]]
    grounded = sc.grade_mean([it["grounded"] for it in answered])
    correct = sc.grade_mean([it["correct"] for it in k_ans])
    handled = sc.grade_mean([it["handled_unanswerable"] for it in unans if not it["gated"]])
    body = [
        f"{len(items)} questions on {len({it['video']['id'] for it in items})} videos: {len(known)} with a known "
        f"answer, {len(unans)} the video doesn't answer, and a summary request per video. Grades: yes = 1, "
        "partly = 0.5, no = 0.\n",
        sc.md_table(["", "Score"], [
            ["Grounded (every claim backed by the passages)", sc.pct(grounded)],
            ["Correct (known-answer questions)", sc.pct(correct)],
            ["Cites the moment that holds the answer", sc.pct(sum(1 for it in k_ans if it.get("cites_answer"))
                                                             / (len(k_ans) or 1))],
            ["Timestamps that point to a real passage", f"{valid} of {cites} ({sc.pct(valid / cites if cites else None)})"],
            ["Says so when the video doesn't cover it", sc.pct(handled)],
            ["Turned away by the relevance check", f"{len(gated_real)} of {len(items)} (all are real questions)"],
            ["Median answer time", f"{sc.med([it['seconds'] for it in answered if 'seconds' in it]):.1f} s"],
        ]),
    ]
    weak = [it for it in answered if "no" in (it["grounded"], it["correct"], it["handled_unanswerable"])
            or it["grounded"] == "partly" or it["correct"] == "partly"]
    if weak:
        body += ["\n## Answers to look at\n"]
        body += [f"- **{it['q']}** ({it['video']['title'][:30]}; {it['kind']}): grounded {it['grounded']}, "
                 f"correct {it['correct']}, unanswerable handled {it['handled_unanswerable']}. _{it['note']}_  \n"
                 f"  > {it['answer'][:400]}" for it in weak]
    if gated_real:
        body += ["\n## Turned away by the relevance check\n",
                 sc.md_table(["Video", "Question", "Score"], [[it["video"]["title"][:30], it["q"], it["score"]]
                                                              for it in gated_real])]
    for it in items:
        it["video"] = it["video"]["title"]
    headline = {"grounded": grounded, "correct": correct, "timestamps_valid": valid / cites if cites else None,
                "unanswerable_handled": handled, "questions": len(items)}
    common.report("answers", "Layer 2: chatbot answers", "\n".join(body), headline, items)


if __name__ == "__main__":
    main()
