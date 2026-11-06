"""The vertical Short cut from the start of a video, made by Assemble next to the full video.

The Short reuses the main video's shots and voice from the start up to the cliffhanger sentence
that ends between `min_seconds` and `max_seconds` (50-70 by default), and stops right there. Each 16:9 picture is trimmed a little at the sides, scaled to the phone's width and
centred on the paper-coloured background; the channel name sits just under it, on the left.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from pipeline import ffmpeg
from pipeline.assemble import _hex_to_rgb, encode
from pipeline.claude_client import INT, Claude, obj

def opening_beats(beats: list[dict[str, Any]], words: list[dict[str, Any]], seconds: float = 59,
                  wpm: float = 180) -> set[int]:
    """Beat indices heard in the first `seconds` of the video: from the word timings when there is a
    voice-over, otherwise estimated from the word count."""
    out: set[int] = set()
    for b in beats:
        if words and b["word_start"] < len(words):
            start = words[b["word_start"]]["start"]
        else:
            start = b["word_start"] * 60 / wpm
        if start < seconds:
            out.add(b["idx"])
    return out


_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")

CUT_SYSTEM = """You choose where a Short ends. The Short is the opening of a narrated history video, \
posted on its own as a YouTube Short, Reel and TikTok; it stops right after the sentence you pick, \
and must make viewers want the full video. Pick the sentence that lands the strongest cliffhanger: a \
reveal that is just starting, or a question left hanging. Never pick one that answers the question \
the opening raised, and avoid ending in the middle of an explanation. Only the sentences marked as \
possible endings can be picked; between equally good ones, prefer the earlier."""

CUT_SCHEMA = obj({"sentence": INT})


def sentences(words: list[dict[str, Any]], until: float) -> list[dict[str, Any]]:
    """The narration's sentences that start before `until` seconds, with the time each one ends."""
    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for n, w in enumerate(words):
        if not cur and w["start"] >= until:
            break
        cur.append(w)
        if _SENTENCE_END.search(w["text"]) or n == len(words) - 1:
            nxt = words[n + 1]["start"] if n + 1 < len(words) else w["end"] + 0.4
            out.append({"text": " ".join(x["text"] for x in cur), "end": min(w["end"] + 0.4, max(w["end"], nxt))})
            cur = []
    return out


def cut_key(words: list[dict[str, Any]], max_s: float) -> str:
    """Changes whenever the narration of the Short's window changes (a new voice-over)."""
    return hashlib.md5(repr([(w["text"], w["start"]) for w in words if w["start"] < max_s + 15]).encode()).hexdigest()


def choose_cut(claude: Claude, words: list[dict[str, Any]], min_s: float = 50, max_s: float = 70) -> float:
    """Seconds where the Short ends: just after the cliffhanger sentence that ends between min_s and
    max_s. With no sentence ending in that window, it cuts at max_s."""
    sents = sentences(words, max_s)
    picks = [n for n, s in enumerate(sents) if min_s <= s["end"] <= max_s]
    if not picks:
        return float(max_s)
    if len(picks) == 1:
        return sents[picks[0]]["end"]
    lines = [f"{n}{' (possible ending)' if n in picks else ''} [{s['end']:.0f}s]: {s['text']}" for n, s in enumerate(sents)]
    res = claude.json(CUT_SYSTEM, [{"role": "user", "content": "SENTENCES\n" + "\n".join(lines)}], CUT_SCHEMA,
                      effort="low")
    n = res.get("sentence")
    return sents[n if n in picks else picks[0]]["end"]


def cut_shots(shots: list[dict[str, Any]], fps: int, seconds: float) -> list[dict[str, Any]]:
    """The shots of the first `seconds`, the last one cut short exactly there."""
    limit = round(seconds * fps)
    out = []
    for s in shots:
        if s["start_frame"] >= limit:
            break
        out.append({**s, "end_frame": min(s["end_frame"], limit)})
    return out


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def layout(cfg: dict[str, Any]) -> dict[str, int]:
    """Where the picture and the channel name go on the vertical frame."""
    w, h = cfg.get("width", 1080), cfg.get("height", 1920)
    margin = cfg.get("margin", 24)
    img_w = w - 2 * margin
    img_h = round(img_w / cfg.get("image_aspect", 1.5))
    # A little above centre: the apps cover the bottom of the screen with the caption and buttons.
    img_top = round(h * 0.46 - img_h / 2)
    # The channel name sits just under the picture, lined up with its left edge.
    return {"w": w, "h": h, "img_x": margin, "img_top": img_top, "img_w": img_w, "img_h": img_h,
            "text_x": margin + 16, "text_y": img_top + img_h + 56}


def render_frame(image: str | None, cfg: dict[str, Any], bg: str, channel: str, dst: Path) -> None:
    L = layout(cfg)
    canvas = Image.new("RGB", (L["w"], L["h"]), _hex_to_rgb(bg))
    if image and Path(image).exists():
        with Image.open(image) as im:
            im = im.convert("RGB")
            target = L["img_w"] / L["img_h"]
            if im.width / im.height > target:  # trim the sides a little to the target shape
                keep = round(im.height * target)
                x0 = (im.width - keep) // 2
                im = im.crop((x0, 0, x0 + keep, im.height))
            fit = min(L["img_w"] / im.width, L["img_h"] / im.height)
            nw, nh = round(im.width * fit), round(im.height * fit)
            im = im.resize((nw, nh), Image.LANCZOS)
            canvas.paste(im, (L["img_x"] + (L["img_w"] - nw) // 2, L["img_top"] + (L["img_h"] - nh) // 2))
    if channel.strip():
        channel = "@" + channel.strip().lstrip("@")  # shown as a handle, e.g. @StickFigureHistory
        d = ImageDraw.Draw(canvas)
        size = int(cfg.get("text_size", 46))
        font = _font(size)
        while size > 28 and d.textlength(channel, font=font) > L["w"] - 2 * L["text_x"]:
            size -= 4
            font = _font(size)
        d.text((L["text_x"], L["text_y"]), channel, fill=_hex_to_rgb(cfg.get("text_color", "#1A1A1A")),
               font=font, anchor="lm")
    canvas.save(dst)


def render(shots: list[dict[str, Any]], audio: Path, out: Path, video_cfg: dict[str, Any],
           short_cfg: dict[str, Any], work_dir: Path,
           progress: Callable[[str, float], None] = lambda m, f: None, seconds: float | None = None) -> dict[str, Any]:
    """Render the Short. `shots` are the main video's shots; only the first `seconds` (from
    choose_cut, else max_seconds) are used."""
    fps = video_cfg.get("fps", 30)
    seconds = float(seconds or short_cfg.get("max_seconds", 70))
    shots = cut_shots(shots, fps, seconds)
    if not shots:
        raise ValueError("The video has no shots yet. Assemble it first.")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True)
    channel = short_cfg.get("channel_name", "") or ""
    bg = video_cfg.get("background", "#F7F4EC")

    frame_for: dict[str | None, Path] = {}
    for s in shots:
        if s["image"] not in frame_for:
            frame_for[s["image"]] = frames_dir / (hashlib.md5(repr(s["image"]).encode()).hexdigest()[:12] + ".png")
    for n, (image, path) in enumerate(frame_for.items()):
        progress(f"Preparing vertical frames ({n + 1}/{len(frame_for)})", 0.25 * n / len(frame_for))
        render_frame(image, short_cfg, bg, channel, path)

    stills = [(frame_for[s["image"]], s["end_frame"] - s["start_frame"]) for s in shots]
    length = min(seconds, shots[-1]["end_frame"] / fps)
    encode(stills, audio, out, fps, str(video_cfg.get("crf", 18)), work_dir, progress, max_s=length)
    progress("Done", 1.0)
    return {"path": str(out), "duration": round(ffmpeg.duration(out), 3), "expected": round(length, 3),
            "shots": len(shots)}
