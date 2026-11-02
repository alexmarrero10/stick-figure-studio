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
