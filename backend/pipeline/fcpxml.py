"""FCPXML 1.9 timeline export for DaVinci Resolve.

Every shot is its own still-image clip on the main storyline (a shot with a scale other than 1
carries an adjust-transform, though the planner never zooms), and the voice-over is a connected clip on an audio lane.
Media is referenced by absolute file:// URL, so Resolve links it automatically on import.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image


def _t(frames: int, fps: int) -> str:
    return "0s" if frames == 0 else f"{frames}/{fps}s"


def build(shots: list[dict[str, Any]], audio: Path, audio_duration: float, title: str,
          fps: int = 30, width: int = 1920, height: int = 1080) -> str:
    root = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="r1", name=f"FFVideoFormat{height}p{fps}",
                  frameDuration=f"1/{fps}s", width=str(width), height=str(height), colorSpace="1-1-1 (Rec. 709)")

    next_id = 2
    formats: dict[tuple[int, int], str] = {}
    assets: dict[str, str] = {}

    def rid() -> str:
        nonlocal next_id
        r = f"r{next_id}"
        next_id += 1
        return r

    for s in shots:
        img = s["image"]
        if not img or img in assets:
            continue
        with Image.open(img) as im:
            size = im.size
        if size not in formats:
            formats[size] = rid()
            ET.SubElement(resources, "format", id=formats[size], name="FFVideoFormatRateUndefined",
                          width=str(size[0]), height=str(size[1]), colorSpace="1-13-1")
        aid = rid()
        assets[img] = aid
        a = ET.SubElement(resources, "asset", id=aid, name=Path(img).stem, start="0s", duration="0s",
                          hasVideo="1", format=formats[size], videoSources="1")
        ET.SubElement(a, "media-rep", kind="original-media", src=Path(img).resolve().as_uri())

    audio_frames = math.ceil(audio_duration * fps)
    audio_id = rid()
    a = ET.SubElement(resources, "asset", id=audio_id, name=audio.stem, start="0s",
                      duration=_t(audio_frames, fps), hasAudio="1", audioSources="1", audioChannels="1",
                      audioRate="44100")
    ET.SubElement(a, "media-rep", kind="original-media", src=audio.resolve().as_uri())

    total = shots[-1]["end_frame"] if shots else audio_frames
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name=title)
    project = ET.SubElement(event, "project", name=title)
    seq = ET.SubElement(project, "sequence", format="r1", duration=_t(total, fps), tcStart="0s",
                        tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")

    for i, s in enumerate(shots):
        dur = s["end_frame"] - s["start_frame"]
        name = f"Shot {i + 1:03d} (beat {s['beat_ids'][0]})"
        if s["image"]:
            clip = ET.SubElement(spine, "video", ref=assets[s["image"]], name=name,
                                 offset=_t(s["start_frame"], fps), start="0s", duration=_t(dur, fps))
            if s["scale"] != 1.0:
                ET.SubElement(clip, "adjust-transform", scale=f"{s['scale']:g} {s['scale']:g}")
        else:
            clip = ET.SubElement(spine, "gap", name=f"{name} MISSING IMAGE",
                                 offset=_t(s["start_frame"], fps), start="0s", duration=_t(dur, fps))
        if i == 0:
            # Voice-over attached to the first clip, on the lane below the video.
            ET.SubElement(clip, "asset-clip", ref=audio_id, lane="-1", name="Voice-over", offset="0s",
                          start="0s", duration=_t(audio_frames, fps), audioRole="dialogue")

    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"
