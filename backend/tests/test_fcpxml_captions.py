"""The DaVinci Resolve timeline (FCPXML) and the captions file (SRT)."""
import xml.etree.ElementTree as ET

from pipeline import captions, fcpxml
from tests.helpers import make_png


def test_fcpxml_structure(tmp_path):
    img = tmp_path / "a.png"
    make_png(img)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"")
    shots = [
        {"image": str(img), "start_frame": 0, "end_frame": 45, "scale": 1.0, "beat_ids": [0]},
        {"image": str(img), "start_frame": 45, "end_frame": 120, "scale": 1.15, "beat_ids": [1]},
    ]
    xml = fcpxml.build(shots, audio, 3.9, "Test")
    root = ET.fromstring(xml.split("\n", 2)[2])
    spine = root.find(".//spine")
    clips = list(spine)
    assert [c.get("offset") for c in clips] == ["0s", "45/30s"]
    assert [c.get("duration") for c in clips] == ["45/30s", "75/30s"]
    assert clips[1].find("adjust-transform").get("scale") == "1.15 1.15"
    assert clips[0].find("asset-clip").get("lane") == "-1"
    assert root.find(".//sequence").get("duration") == "120/30s"
    assert root.find(".//media-rep").get("src").startswith("file:///")


def test_srt_cues():
    words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, t in enumerate("Picture this. A vault door, wide open.".split())]
    srt = captions.build_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "Picture this." in srt
