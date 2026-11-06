"""Render the preview MP4 with FFmpeg.

Each image is pre-rendered once to a 1920x1080 frame with Pillow. Each shot is then
encoded as a segment of an exact frame count, the segments are joined without re-encoding, and
the voice is muxed in. Exact frame counts keep the picture locked to the word timings.
"""
from __future__ import annotations

import contextvars
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from pipeline import ffmpeg


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def render_frame(image: str | None, scale: float, size: tuple[int, int], bg: str, dst: Path,
                 label: str = "") -> None:
    w, h = size
    canvas = Image.new("RGB", size, _hex_to_rgb(bg))
    if image and Path(image).exists():
        with Image.open(image) as im:
            im = im.convert("RGB")
            ar, target = im.width / im.height, w / h
            # Near-16:9 images fill the frame; others are fitted with padding so nothing is cut off.
            if abs(ar - target) / target < 0.04:
                fit = max(w / im.width, h / im.height)
            else:
                fit = min(w / im.width, h / im.height)
            fit *= scale
            nw, nh = round(im.width * fit), round(im.height * fit)
            im = im.resize((nw, nh), Image.LANCZOS)
            canvas.paste(im, ((w - nw) // 2, (h - nh) // 2))
    else:
        d = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except OSError:
            font = ImageFont.load_default()
        d.text((80, h // 2 - 60), "MISSING IMAGE", fill=(200, 40, 40), font=font)
        d.text((80, h // 2 + 10), label[:90], fill=(60, 60, 60), font=font)
    canvas.save(dst)


def zoom_for(n_frames: int, fps: int, cfg: dict[str, Any]) -> float:
    """How far a shot slowly zooms in (0.06 = ends 6% closer). Only long shots move: a still that
    sits on screen for many seconds feels frozen, while short ones already change often enough."""
    per_s = float(cfg.get("zoom_per_second", 0.015) or 0)
    seconds = n_frames / fps
    if per_s <= 0 or seconds < float(cfg.get("zoom_min_seconds", 3)):
        return 0.0
    return min(per_s * seconds, 0.12)


def render(shots: list[dict[str, Any]], audio: Path, out: Path, cfg: dict[str, Any],
           work_dir: Path, beat_text: dict[int, str] | None = None,
           progress: Callable[[str, float], None] = lambda m, f: None) -> dict[str, Any]:
    fps = cfg.get("fps", 30)
    size = (cfg.get("width", 1920), cfg.get("height", 1080))
    bg = cfg.get("background", "#F7F4EC")
    crf = str(cfg.get("crf", 18))
    if work_dir.exists():
        shutil.rmtree(work_dir)
    frames_dir, segs_dir = work_dir / "frames", work_dir / "segments"
    frames_dir.mkdir(parents=True)
    segs_dir.mkdir()

    # 1. Unique frames.
    frame_for: dict[tuple[str | None, float, str], Path] = {}
    for s in shots:
        label = "" if s["image"] else f"beat {s['beat_ids'][0]}: {(beat_text or {}).get(s['beat_ids'][0], '')}"
        key = (s["image"], s["scale"], label)
        if key not in frame_for:
            name = hashlib.md5(repr(key).encode()).hexdigest()[:12] + ".png"
            frame_for[key] = frames_dir / name
    for n, (key, path) in enumerate(frame_for.items()):
        progress(f"Preparing frames ({n + 1}/{len(frame_for)})", 0.25 * n / max(1, len(frame_for)))
        render_frame(key[0], key[1], size, bg, path, key[2])

    # 2-3. Encode and join the shots, then add the voice.
    stills = []
    for s in shots:
        label = "" if s["image"] else f"beat {s['beat_ids'][0]}: {(beat_text or {}).get(s['beat_ids'][0], '')}"
        n_frames = s["end_frame"] - s["start_frame"]
        zoom = zoom_for(n_frames, fps, cfg) if s["image"] else 0.0
        stills.append((frame_for[(s["image"], s["scale"], label)], n_frames, zoom))
    encode(stills, audio, out, fps, crf, work_dir, progress, size=size)
    video_dur = ffmpeg.duration(out)
    expected = shots[-1]["end_frame"] / fps if shots else 0
    progress("Done", 1.0)
    return {"path": str(out), "duration": round(video_dur, 3), "expected": round(expected, 3),
            "frames_dir": str(frames_dir)}


def zoom_filter(n_frames: int, zoom: float, size: tuple[int, int], fps: int) -> str:
    """A slow, centered zoom-in from 1.0 to 1 + zoom over the shot. The frame is upscaled 2x first so
    zoompan's whole-pixel steps land on half pixels of the output and the motion doesn't wobble."""
    w, h = size
    return (f"scale={w * 2}:{h * 2}:flags=lanczos,"
            f"zoompan=z='1+{zoom:.4f}*on/{max(1, n_frames - 1)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
            f":d=1:s={w}x{h}:fps={fps}")


def encode(stills: list[tuple], audio: Path, out: Path, fps: int, crf: str, work_dir: Path,
           progress: Callable[[str, float], None] = lambda m, f: None, max_s: float | None = None,
           size: tuple[int, int] | None = None) -> None:
    """stills: (frame image, number of frames[, zoom]) in order. Each becomes a segment of exactly that
    many frames, zooming in slowly when zoom > 0 (needs size); the segments are joined without
    re-encoding and the voice is added. With max_s, the audio is cut there too (the video is expected
    to be cut to the same length by the caller)."""
    segs_dir = work_dir / "segments"
    segs_dir.mkdir(parents=True, exist_ok=True)
    seg_paths: list[Path] = []
    jobs = []
    for i, (frame, n_frames, *rest) in enumerate(stills):
        zoom = rest[0] if rest and size else 0.0
        seg = segs_dir / f"seg_{i:04d}.mp4"
        seg_paths.append(seg)
        look = ["-vf", zoom_filter(n_frames, zoom, size, fps)] if zoom else ["-tune", "stillimage"]
        jobs.append([
            "-loop", "1", "-framerate", str(fps), "-i", str(frame), "-frames:v", str(n_frames),
            "-c:v", "libx264", "-preset", "veryfast", *look, "-crf", crf,
            "-pix_fmt", "yuv420p", "-r", str(fps), "-video_track_timescale", str(fps * 1000), str(seg),
        ])
    done = 0
    # Each encode runs in the job's context, so stopping the job reaches the ffmpeg processes.
    tasks = [(contextvars.copy_context(), a) for a in jobs]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in pool.map(lambda t: t[0].run(ffmpeg.run, t[1]), tasks):
            done += 1
            if done % 10 == 0 or done == len(jobs):
                progress(f"Encoding shots ({done}/{len(jobs)})", 0.25 + 0.65 * done / len(jobs))

    progress("Joining shots and adding the voice-over", 0.92)
    list_file = work_dir / "segments.txt"
    list_file.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in seg_paths), encoding="utf-8")
    video_only = work_dir / "video_only.mp4"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(video_only)])
    cut = ["-t", f"{max_s:.3f}"] if max_s else []
    ffmpeg.run([
        "-i", str(video_only), "-i", str(audio), "-map", "0:v", "-map", "1:a", *cut,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out),
    ])
    shutil.rmtree(segs_dir, ignore_errors=True)
