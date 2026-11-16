"""Shorts: the opening, where the Short ends, the vertical render, and assembling it with the video."""
import json
import subprocess

import pytest
from PIL import Image, ImageDraw

from pipeline import ffmpeg, prompts, shorts
from tests.helpers import make_wav


def _assemble(client, temp_db, monkeypatch, channel="NextDoorHistorian", short_fails=False):
    """Run the Assemble job with the slow parts faked; returns the finished job."""
    import time as _time

    from app.routes import assemble as route
    p = temp_db.create_project("Franklin")
    words = [{"text": "w", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(200)]
    plan = {"shots": [{"image": "a.png", "start_frame": 0, "end_frame": 30, "scale": 1.0, "beat_ids": [0]}],
            "missing_images": [], "unused_images": [], "total_frames": 30}
    monkeypatch.setattr(route, "_plan", lambda pid: plan)
    monkeypatch.setattr(route.db, "get_voiceover", lambda pid: {"audio_path": "voice.wav", "duration_s": 100.0, "script_version_id": None})
    monkeypatch.setattr(route.db, "list_words", lambda pid: words)
    monkeypatch.setattr(route.fcpxml, "build", lambda *a, **k: "<fcpxml/>")
    monkeypatch.setattr(route, "short_cfg", lambda: {"min_seconds": 50, "max_seconds": 70, "channel_name": channel})
    monkeypatch.setattr(route.assemble, "render", lambda *a, **k: {"duration": 100.0, "expected": 100.0})
    monkeypatch.setattr(route.shorts, "choose_cut", lambda claude, w, lo, hi: 61.5)
    monkeypatch.setattr(route, "claude", lambda: None)
    made = []

    def fake_short(shots, audio, out, vcfg, scfg, work, progress, seconds=None):
        if short_fails:
            raise RuntimeError("ffmpeg broke")
        made.append(seconds)
        return {"duration": seconds}

    monkeypatch.setattr(route.shorts, "render", fake_short)
    job = client.post(f"/api/projects/{p['id']}/assemble").json()
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        _time.sleep(0.02)
    return p, job, made


def _words(text_at: list[tuple[str, float]]) -> list[dict]:
    """One word per (text, start) with a 0.3 s duration."""
    return [{"idx": n, "text": t, "start": s, "end": s + 0.3} for n, (t, s) in enumerate(text_at)]


class CutFake:
    def __init__(self, pick):
        self.pick, self.asks = pick, []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        self.asks.append(messages[-1]["content"])
        return {"sentence": self.pick}


def test_opening_beats_from_timings_or_estimate():
    beats = [{"idx": i, "word_start": i * 10, "text": "w"} for i in range(40)]
    words = [{"start": i * 0.5} for i in range(400)]  # 5 s per beat
    assert shorts.opening_beats(beats, words, 59) == set(range(12))
    assert shorts.opening_beats(beats, [], 59, wpm=180) == set(range(18))  # 3.33 s per beat


def test_opening_images_are_marked_for_claude():
    from tests.helpers import FakeClaude
    fake = FakeClaude()
    guide = {"characters": [], "props": [], "locations": [], "setting_notes": ""}
    beats = [{"idx": i, "text": f"w{i}."} for i in range(60)]
    prompts.write_scenes(fake, "s", guide, beats, group=40, opening={0, 1, 2, 3, 4, 5})
    assert "Beats 0-5 are OPENING IMAGES" in fake.calls[0][1]
    assert "OPENING IMAGES" not in fake.calls[1][1]
    assert "OPENING IMAGES: the beats marked as the opening" in fake.calls[0][0]


def test_cut_shots_stops_at_59_seconds():
    shots_ = [{"image": f"{i}.png", "start_frame": i * 300, "end_frame": (i + 1) * 300, "scale": 1.0, "beat_ids": [i]}
              for i in range(10)]
    cut = shorts.cut_shots(shots_, 30, 59)
    assert len(cut) == 6 and cut[-1]["end_frame"] == 1770


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")
def test_short_render_is_vertical_and_cuts_at_59_seconds(tmp_path):
    wav = tmp_path / "voice.wav"
    make_wav(wav, 64.0)
    imgs = []
    for i in range(4):
        p = tmp_path / f"{i}.png"
        im = Image.new("RGB", (1376, 768), (247, 244, 236))
        ImageDraw.Draw(im).rectangle((0, 0, 1375, 767), outline=(200, 30, 30), width=40)  # red edge to see trimming
        ImageDraw.Draw(im).ellipse((588, 284, 788, 484), fill=(20, 60, 160))
        im.save(p)
        imgs.append(str(p))
    shots_ = [{"image": imgs[i % 4], "start_frame": i * 480, "end_frame": (i + 1) * 480, "scale": 1.0, "beat_ids": [i]}
              for i in range(4)]  # 64 s of shots
    out = tmp_path / "short.mp4"
    cfg = {"max_seconds": 59, "channel_name": "Stick Figure History", "width": 1080, "height": 1920,
           "image_aspect": 1.5, "margin": 24}
    res = shorts.render(shots_, wav, out, {"fps": 30, "crf": 28, "background": "#F7F4EC"}, cfg, tmp_path / "_w")
    assert abs(res["duration"] - 59.0) < 0.1
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,nb_frames,duration", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)["streams"]
    v = next(s for s in probe if s["codec_type"] == "video")
    a = next(s for s in probe if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1080, 1920) and int(v["nb_frames"]) == 59 * 30
    assert abs(float(a["duration"]) - 59.0) < 0.1

    frame = next((tmp_path / "_w" / "frames").glob("*.png"))
    with Image.open(frame) as f:
        L = shorts.layout(cfg)
        assert f.size == (1080, 1920)
        # The picture fills the width between the margins and is trimmed at the sides (no red side edge).
        mid = L["img_top"] + L["img_h"] // 2
        assert f.getpixel((L["img_x"] + 2, mid)) != (200, 30, 30)
        assert f.getpixel((540, mid))[2] > 120  # the blue circle is centred
        # The channel name is drawn just under the picture, on the left half.
        assert L["text_y"] > L["img_top"] + L["img_h"]
        left = f.crop((0, L["text_y"] - 30, 540, L["text_y"] + 30)).convert("L")
        right = f.crop((900, L["text_y"] - 30, 1080, L["text_y"] + 30)).convert("L")
        assert left.getextrema()[1] > 200 and right.getextrema()[1] < 60  # white name on black
        assert f.getpixel((540, 40)) == (0, 0, 0)  # the rest is black background


def test_assemble_makes_the_full_video_and_the_short(client, temp_db, monkeypatch):
    p, job, made = _assemble(client, temp_db, monkeypatch)
    assert job["status"] == "done" and job["result"]["short"] == {"duration": 61.5}
    assert made == [61.5] and job["result"]["short_error"] is None
    assert temp_db.get_short(p["id"])["cut_s"] == 61.5 and temp_db.project_status(p["id"])["short"]


def test_assemble_keeps_the_full_video_when_the_short_cant_be_made(client, temp_db, monkeypatch):
    _, job, made = _assemble(client, temp_db, monkeypatch, channel="")
    assert job["status"] == "done" and made == [] and "channel name" in job["result"]["short_error"]
    _, job, _ = _assemble(client, temp_db, monkeypatch, short_fails=True)
    assert job["status"] == "done" and "ffmpeg broke" in job["result"]["short_error"]


def test_short_ends_on_the_cliffhanger_sentence_claude_picks_between_50_and_70_seconds():
    words = _words([("It", 0), ("began.", 1), ("Soldiers", 48), ("waited.", 49), ("Then", 55), ("silence.", 56),
                    ("Someone", 62), ("screamed.", 63), ("Answer", 71), ("given.", 72)])
    fake = CutFake(pick=2)
    assert shorts.choose_cut(fake, words, 50, 70) == pytest.approx(56.7)
    assert "2 (possible ending) [57s]: Then silence." in fake.asks[0]
    assert "(possible ending) [50s]" not in fake.asks[0] and "Answer given" not in fake.asks[0]
    assert shorts.choose_cut(CutFake(pick=1), words, 50, 70) == pytest.approx(56.7)  # not a possible ending


def test_short_cuts_at_the_longest_length_when_no_sentence_ends_in_the_window():
    words = _words([("A", 0), ("very", 40), ("long", 60), ("sentence.", 75)])
    assert shorts.choose_cut(CutFake(pick=0), words, 50, 70) == 70.0
    one = _words([("Hello.", 0), ("Then", 52), ("silence.", 53)])
    fake = CutFake(pick=0)
    assert shorts.choose_cut(fake, one, 50, 70) == pytest.approx(53.7) and not fake.asks  # one choice: no need to ask
