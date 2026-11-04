"""Offline end-to-end: script → beats → (fake) word timings → shots → MP4 + FCPXML. Needs ffmpeg."""
import json
import subprocess

import pytest
from PIL import Image, ImageDraw

from pipeline import assemble, captions, fcpxml, ffmpeg, scenes, shots
from tests.test_voice import make_wav

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")

TEXT = ("Picture this. A man walks into a bank with nothing but a pen, a smile, and a plan "
        "so simple it should never have worked. He signs his name, waits patiently, and leaves "
        "with a briefcase full of cash. Nobody stops him.")


def test_render_matches_audio(tmp_path):
    beats = scenes.build_beats(TEXT)
    n = len(TEXT.split())
    # Fake timings: 0.35 s per word, slight pause at sentence ends.
    words, t = [], 0.3
    for i, w in enumerate(TEXT.split()):
        words.append({"idx": i, "text": w, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 0.35 + (0.3 if scenes.ends_sentence(w) else 0)
    dur = round(t + 0.3, 3)
    wav = tmp_path / "voice.wav"
    make_wav(wav, dur, tone_spans=[(w["start"], w["end"]) for w in words])

    imgs = {}
    for b in beats:
        p = tmp_path / f"img_{b['idx']:02d}.png"
        im = Image.new("RGB", (1376, 768), "white")
        ImageDraw.Draw(im).ellipse((600, 200, 776, 376), outline="black", width=8)
        im.save(p)
        imgs[b["idx"]] = str(p)

    cfg_shots = {"cut_lead_s": 0.08, "min_shot_s": 1.0, "max_shot_s": 5.0, "punch_in_scale": 1.15, "tail_s": 0.6}
    plan = shots.build_shots(beats, words, imgs, dur, cfg_shots, 30)
    out = tmp_path / "video.mp4"
    res = assemble.render(plan["shots"], wav, out, {"fps": 30, "width": 640, "height": 360, "crf": 28},
                          tmp_path / "_work")
    assert abs(res["duration"] - plan["total_frames"] / 30) < 0.1

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                            "-show_entries", "stream=nb_read_frames,r_frame_rate", "-of", "json", str(out)],
                           capture_output=True, text=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert int(stream["nb_read_frames"]) == plan["total_frames"]
    assert stream["r_frame_rate"] == "30/1"

    xml = fcpxml.build(plan["shots"], wav, dur, "E2E")
    assert xml.count("<video ") == len(plan["shots"])
    assert "-->" in captions.build_srt(words)
    assert n == words[-1]["idx"] + 1


def test_zoom_only_on_long_shots():
    cfg = {"zoom_min_seconds": 4, "zoom_per_second": 0.015}
    assert assemble.zoom_for(119, 30, cfg) == 0.0  # just under 4 s stays still
    assert assemble.zoom_for(120, 30, cfg) == pytest.approx(0.06)
    assert assemble.zoom_for(30 * 20, 30, cfg) == 0.12  # capped, so very long shots don't crawl in too far
    assert assemble.zoom_for(300, 30, {**cfg, "zoom_per_second": 0}) == 0.0  # 0 turns it off
    assert assemble.zoom_for(150, 30, {}) == pytest.approx(0.075)  # defaults when config predates zoom


def _frame_at(video, n, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\,{n})",
                    "-frames:v", "1", str(dst)], check=True)
    return Image.open(dst).convert("L")


def test_zoomed_segment_keeps_exact_frames_and_moves_in(tmp_path):
    frame = tmp_path / "f.png"
    im = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(im).rectangle((20, 20, 619, 339), outline="black", width=6)  # border near the edges
    im.save(frame)
    wav = tmp_path / "voice.wav"
    make_wav(wav, 10.0)
    out = tmp_path / "out.mp4"
    assemble.encode([(frame, 150, 0.1), (frame, 60, 0.0)], wav, out, 30, "23", tmp_path / "_work",
                    size=(640, 360))

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                            "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(out)],
                           capture_output=True, text=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert int(stream["nb_read_frames"]) == 210
    assert (stream["width"], stream["height"]) == (640, 360)

    first, last = _frame_at(out, 0, tmp_path / "a.png"), _frame_at(out, 149, tmp_path / "b.png")
    # At 10% zoom the border (x=20) moves out to about x=-12: gone from the last frame of the shot.
    assert first.getpixel((22, 180)) < 100
    assert last.getpixel((22, 180)) > 150
    # The plain still that follows doesn't move.
    still_a, still_b = _frame_at(out, 150, tmp_path / "c.png"), _frame_at(out, 209, tmp_path / "d.png")
    assert still_a.getpixel((22, 180)) < 100 and still_b.getpixel((22, 180)) < 100
