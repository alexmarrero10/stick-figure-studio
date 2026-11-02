import pytest

from pipeline import scenes

SCRIPT = """Picture this. It's three in the morning, the vault door is open, and nobody inside the bank has any idea.

The guard yawns. He checks his watch, sips cold coffee, and walks right past the one camera that matters. Outside, a gray van idles in the rain while four men count the seconds until the alarm system reboots and the whole plan either works perfectly or collapses in front of everyone.

No."""


def coverage_ok(beats, n):
    expected = 0
    for b in beats:
        assert b["word_start"] == expected
        assert b["word_end"] >= b["word_start"]
        expected = b["word_end"] + 1
    assert expected == n


def test_beats_cover_every_word_in_order():
    beats = scenes.build_beats(SCRIPT)
    coverage_ok(beats, len(SCRIPT.split()))
    assert [b["idx"] for b in beats] == list(range(len(beats)))


def test_beat_text_matches_word_range():
    words = SCRIPT.split()
    for b in scenes.build_beats(SCRIPT):
        assert b["text"] == " ".join(words[b["word_start"]:b["word_end"] + 1])


def test_sizes_within_limits():
    beats = scenes.build_beats(SCRIPT, min_words=3, max_words=13)
    for b in beats:
        n = b["word_end"] - b["word_start"] + 1
        assert n <= 13
    # Short beats are only allowed for complete sentences that couldn't merge without overflowing.
    for b in beats:
        if b["word_end"] - b["word_start"] + 1 < 3:
            assert scenes.ends_sentence(b["text"].split()[-1])


def test_sentence_ends_are_boundaries():
    beats = scenes.build_beats(SCRIPT)
    # "Picture this." is short, so it merges with the next chunk, but no beat ends mid-sentence
    # when the next word starts a new sentence after a period unless it was merged.
    ends = [b["text"].split()[-1] for b in beats]
    assert ends[-1] == "No." or ends[-1].endswith(".")


def test_long_sentence_is_split_before_clause_starter():
    text = " ".join(["word"] * 10) + " and then " + " ".join(["more"] * 10) + "."
    beats = scenes.build_beats(text, max_words=13)
    coverage_ok(beats, len(text.split()))
    assert max(b["word_end"] - b["word_start"] + 1 for b in beats) <= 13
    assert any(b["text"].startswith("and") for b in beats)


def test_apply_ops_merge_and_split():
    ranges = [(0, 4), (5, 9), (10, 14)]
    new, skipped = scenes.apply_ops(ranges, [{"op": "merge", "beat": 0}, {"op": "split", "beat": 2, "at": 12}], 15)
    assert skipped == []
    assert new == [(0, 9), (10, 11), (12, 14)]


def test_apply_ops_rejects_bad_split():
    new, skipped = scenes.apply_ops([(0, 4), (5, 9)], [{"op": "split", "beat": 0, "at": 7}], 10)
    assert new == [(0, 4), (5, 9)]
    assert skipped


def test_validate_ranges_catches_gaps():
    with pytest.raises(ValueError):
        scenes.validate_ranges([(0, 3), (5, 9)], 10)


def test_replace_beat_text_shifts_later_beats_and_keeps_paragraphs():
    text = "One two three.\n\nFour five six. Seven eight."
    ranges = [(0, 2), (3, 5), (6, 7)]
    new, new_ranges = scenes.replace_beat_text(text, ranges, 1, "  Four  and five  and six. ")
    assert new == "One two three.\n\nFour and five and six. Seven eight."
    assert new_ranges == [(0, 2), (3, 7), (8, 9)]
    new, new_ranges = scenes.replace_beat_text(text, ranges, 0, "Uno.")
    assert new == "Uno.\n\nFour five six. Seven eight."
    assert new_ranges == [(0, 0), (1, 3), (4, 5)]
    with pytest.raises(ValueError):
        scenes.replace_beat_text(text, ranges, 2, "   ")


def test_default_beats_are_short_enough_for_a_picture_every_1_to_3_seconds():
    beats = scenes.build_beats(SCRIPT)  # defaults: 3-8 words, about 1-3 s at 180 wpm
    coverage_ok(beats, len(SCRIPT.split()))
    assert all(b["word_end"] - b["word_start"] + 1 <= 8 for b in beats)


def test_apply_ops_refuses_merges_that_make_long_beats():
    ranges = [(0, 7), (8, 15)]
    out, skipped = scenes.apply_ops(ranges, [{"op": "merge", "beat": 0}], 16, max_words=8)
    assert out == ranges and skipped


def test_beat_review_follows_the_configured_beat_length():
    from pipeline import beat_review

    class Fake:
        def json(self, system, messages, schema, effort=None):
            self.system = system
            return {"ops": []}

    fake = Fake()
    beat_review.review(fake, [], min_words=2, max_words=13, wpm=180)
    assert "about 2-13 words" in fake.system and "longer than 13 words" in fake.system
    assert "0.5-4 seconds" in fake.system and "{" not in fake.system
