"""Live checks that the site's chatbot really uses the RAG database (Supabase + Gemini, real data).

Skipped unless you ask for them, because they use the network and the Gemini free tier
(about 15 embeddings and 5 answers, roughly a minute):

    PowerShell:  $env:LIVE_EVALS=1; .venv\\Scripts\\python -m pytest -q evals/tests/test_chatbot_live.py
    Git Bash:    LIVE_EVALS=1 .venv/Scripts/python -m pytest -q evals/tests/test_chatbot_live.py

Questions come from evals/data/questions.json (make_questions.py), so the passage holding each answer is
known. They check: the question finds that passage (narration or research source), it isn't turned away
as off-topic, the answer cites the video or a source, and questions beyond the video get a straight answer.
"""
import os
import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.skipif(os.environ.get("LIVE_EVALS") != "1",
                                reason="live test: set LIVE_EVALS=1 (uses Supabase and the Gemini free tier)")

NARRATION_PER_VIDEO = 4
SOURCE_QUESTIONS = 6
MIN_HIT_RATE = 0.75  # retrieval isn't perfect; fail when it clearly gets worse
DISCLAIMER = re.compile(r"\b(don'?t|doesn'?t|do not|does not|didn'?t)\s+(cover|mention|say|discuss)|general history",
                        re.I)


@pytest.fixture(scope="module")
def live():
    import common
    data = common.load("questions.json")
    if not data:
        pytest.skip("No question set. Run: .venv\\Scripts\\python evals\\make_questions.py")
    videos = common.videos()
    return {"common": common, "site": common.site(), "data": data,
            "by_id": {v["id"]: v for v in videos}, "by_key": {v["project_key"]: v for v in videos}}


@pytest.fixture(scope="module")
def narration(live):
    """Known-answer narration questions with what the chatbot found for each."""
    out = []
    for sv in live["data"]["videos"]:
        v = live["by_id"].get(sv["video_id"])
        if not v:
            continue
        for x in random.Random(sv["video_id"]).sample(sv["questions"], min(NARRATION_PER_VIDEO, len(sv["questions"]))):
            out.append({"video": v, **x, "found": live["common"].retry(live["site"].gather, v, x["q"])})
    if not out:
        pytest.skip("None of the question set's videos are on the site")
    return out


@pytest.fixture(scope="module")
def research(live):
    """Questions answered by a research source (not the narration), with what the chatbot found."""
    pool = [(live["by_key"][g["project_key"]], q) for g in live["data"].get("sources", [])
            if g["project_key"] in live["by_key"] for q in g["questions"]]
    if not pool:
        pytest.skip("No research-source questions for a video on the site")
    picked = random.Random(7).sample(pool, min(SOURCE_QUESTIONS, len(pool)))
    return [{"video": v, **q, "found": live["common"].retry(live["site"].gather, v, q["q"])} for v, q in picked]


def _rate(items, hit):
    misses = [i["q"] for i in items if not hit(i)]
    return 1 - len(misses) / len(items), misses


def test_narration_questions_find_the_passage_that_answers_them(narration):
    rate, misses = _rate(narration, lambda i: i["ord"] in [m["ord"] for m in i["found"]["moments"]])
    assert rate >= MIN_HIT_RATE, f"found the right narration passage for {rate:.0%}; missed: {misses}"


def test_research_questions_find_their_source_document(research):
    rate, misses = _rate(research, lambda i: i["source"] in [s["title"] for s in i["found"]["sources"]])
    assert rate >= MIN_HIT_RATE, f"found the right research source for {rate:.0%}; missed: {misses}"


def test_questions_the_database_answers_are_not_turned_away(live, narration, research):
    cutoff = live["site"].CHAT_MIN_SIMILARITY
    gated = [(i["q"], round(i["found"]["relevance"], 2)) for i in narration + research
             if i["found"]["relevance"] < cutoff]
    assert not gated, f"turned away as off-topic (cutoff {cutoff}): {gated}"


def _ask(live, item):
    site = live["site"]
    return live["common"].answer(site.CHAT_SYSTEM, site.chat_contents([], item["found"]["context"], item["q"]))


def test_answers_cite_the_narration_they_were_given(live, narration):
    sc = __import__("scoring")
    for item in narration[:2]:
        answer = _ask(live, item)
        windows = item["found"]["moments"] + item["found"]["near"]
        valid, total = sc.citation_check(sc.parse_times(answer), windows)
        assert total and valid == total, f"{item['q']!r}: timestamps don't point at given passages: {answer}"
        assert not DISCLAIMER.search(answer), f"{item['q']!r}: has a disclaimer: {answer}"


def test_answers_to_research_questions_cite_a_source_or_the_video(live, research):
    for item in research[:2]:
        answer = _ask(live, item)
        assert "[Source:" in answer or re.search(r"\[\d+:\d{2}", answer), f"{item['q']!r}: no citation: {answer}"
        assert not DISCLAIMER.search(answer), f"{item['q']!r}: has a disclaimer: {answer}"


def test_questions_beyond_the_video_get_a_straight_answer(live):
    v = next((v for v in live["by_key"].values() if "watergate" in v["title"].lower()), None)
    if not v:
        pytest.skip("The Watergate video isn't on the site")
    q = "who did nixon run against in his campaign while this took place?"
    found = live["common"].retry(live["site"].gather, v, q)
    assert found["relevance"] >= live["site"].CHAT_MIN_SIMILARITY, "turned away as off-topic"
    answer = _ask(live, {"q": q, "found": found})
    assert "McGovern" in answer, answer
    assert not DISCLAIMER.search(answer), f"has a disclaimer: {answer}"
