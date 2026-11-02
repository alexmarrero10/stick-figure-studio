from pipeline.shots import build_shots

CFG = {"cut_lead_s": 0.1, "min_shot_s": 1.0, "max_shot_s": 5.0, "punch_in_scale": 1.15, "tail_s": 0.5}
FPS = 30


def setup(beat_times, texts=None):
    """beat_times: list of (start, end) seconds for each beat, one word per beat."""
    words = [{"idx": i, "text": "w.", "start": s, "end": e} for i, (s, e) in enumerate(beat_times)]
    beats = [{"idx": i, "word_start": i, "word_end": i, "text": (texts[i] if texts else "word.")}
             for i in range(len(beat_times))]
    images = {i: f"img{i}.png" for i in range(len(beat_times))}
    return beats, words, images


def test_lead_and_contiguity():
    beats, words, images = setup([(0.2, 2.0), (2.5, 4.5), (5.0, 7.0)])
    plan = build_shots(beats, words, images, 7.2, CFG, FPS)
    shots = plan["shots"]
    assert shots[0]["start_frame"] == 0
    assert shots[1]["start_frame"] == round((2.5 - 0.1) * FPS)
    for a, b in zip(shots, shots[1:]):
        assert a["end_frame"] == b["start_frame"]
    assert plan["total_frames"] == round((7.2 + 0.5) * FPS)


def test_short_shot_merges_and_keeps_longer_image():
    # Beat 1 lasts 0.5 s and is mid-sentence, so it merges.
    beats, words, images = setup([(0.0, 2.0), (2.1, 2.5), (2.6, 4.0)], texts=["a,", "b,", "c."])
    plan = build_shots(beats, words, images, 4.2, CFG, FPS)
    shots = plan["shots"]
    assert all(s["end_frame"] - s["start_frame"] >= FPS for s in shots)
    merged = next(s for s in shots if 1 in s["beat_ids"])
    assert len(merged["beat_ids"]) == 2
    assert "img1.png" in plan["unused_images"]


def test_long_shot_stays_one_unzoomed_shot():
    beats, words, images = setup([(0.0, 12.0)])
    plan = build_shots(beats, words, images, 12.0, CFG, FPS)
    shots = plan["shots"]
    assert len(shots) == 1
    assert shots[0]["scale"] == 1.0 and shots[0]["image"] == "img0.png"
    assert shots[0]["end_frame"] == round(12.5 * FPS)


def test_no_shot_is_ever_zoomed():
    times = [(i * 7.0, i * 7.0 + 6.5) for i in range(10)]  # long beats that used to become punch-ins
    beats, words, images = setup(times)
    plan = build_shots(beats, words, images, 70.0, CFG, FPS)
    assert {s["scale"] for s in plan["shots"]} == {1.0}


def test_total_matches_audio_plus_tail():
    times = [(i * 2.0, i * 2.0 + 1.8) for i in range(50)]
    beats, words, images = setup(times)
    plan = build_shots(beats, words, images, 100.0, CFG, FPS)
    assert plan["shots"][-1]["end_frame"] == round(100.5 * FPS)
    assert sum(s["end_frame"] - s["start_frame"] for s in plan["shots"]) == plan["total_frames"]
