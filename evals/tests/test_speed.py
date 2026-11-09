"""The speed test's pure helpers (no network, no Claude)."""
import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import speed  # noqa: E402


def test_fit_words_keeps_short_sources_whole_and_shares_the_rest():
    assert speed.fit_words([100, 200], 1000) == [100, 200]
    assert speed.fit_words([100, 5000, 5000], 1100) == [100, 500, 500]
    keep = speed.fit_words([300, 9000, 4000, 50], 6000)
    assert sum(keep) <= 6000 and keep[0] == 300 and keep[3] == 50 and keep[1] == keep[2]


def test_full_sources_gives_one_whole_passage_per_usable_source():
    docs = [{"status": "ok", "title": "A", "url": "https://a", "text": "one two three four"},
            {"status": "skipped", "title": "B", "url": "https://b", "text": "x " * 50},
            {"status": "ok", "title": "C", "url": "https://c", "text": "w " * 10}]
    chunks, info = speed.full_sources(docs, max_words=8)
    assert [c["title"] for c in chunks] == ["A", "C"]
    assert chunks[0]["text"] == "one two three four"
    assert len(chunks[1]["text"].split()) == 4
    assert info == {"sources": 2, "words": 14, "words_kept": 8, "trimmed": 1}


def test_full_sources_format_like_rag_excerpts():
    from pipeline import rag
    chunks, _ = speed.full_sources([{"status": "ok", "title": "A", "url": "https://a", "text": "hello there"}])
    assert rag.format_excerpts(chunks) == "[1] A <https://a>\nhello there"


def test_parse_ways():
    assert speed.parse_ways("rag, full") == ["rag", "full"]
    for bad in ("rag,rag", "rag,web", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            speed.parse_ways(bad)
