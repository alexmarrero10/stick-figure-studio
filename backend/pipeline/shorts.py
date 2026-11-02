"""Vertical Shorts (YouTube Shorts, Instagram and Facebook Reels, TikTok) cut from the start of a video.

The Short reuses the main video's shots and voice for the first `max_seconds` (59 by default) and
stops dead there. Each 16:9 picture is trimmed a little at the sides, scaled to the phone's width and
centred on the paper-coloured background; the channel name sits just under it, on the left.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from pipeline import ffmpeg
from pipeline.assemble import _hex_to_rgb, encode
from pipeline.claude_client import STR, Claude, arr, obj

PLATFORMS = ("youtube", "instagram", "facebook", "tiktok")


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
           progress: Callable[[str, float], None] = lambda m, f: None) -> dict[str, Any]:
    """Render the Short. `shots` are the main video's shots; only the first max_seconds are used."""
    fps = video_cfg.get("fps", 30)
    seconds = float(short_cfg.get("max_seconds", 59))
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


# --- text for each app --------------------------------------------------------

TEXT_SYSTEM = """You write the text that goes with a YouTube Short, Instagram Reel, Facebook Reel and \
TikTok cut from the first minute of a narrated stick-figure history video. The clip stops abruptly on \
a cliffhanger, so the text must make viewers want to watch the full video on YouTube. Be accurate: \
promise nothing the video doesn't deliver.

- title: under 70 characters, curiosity-driven, no hashtags, no emojis.
- caption: 1-2 short sentences (under 200 characters) that tease the mystery and say the full story \
is on YouTube. No hashtags, no links (the link is added automatically).
- hashtags: 5-8 hashtags without the # sign, mixing broad ones (history, animation) with ones about \
this subject."""

TEXT_SCHEMA = obj({"title": STR, "caption": STR, "hashtags": arr(STR)})


def write_text(claude: Claude, title: str, opening: str) -> dict[str, Any]:
    msg = f"VIDEO TITLE: {title}\n\nNARRATION OF THE CLIP (it cuts off at the end of this):\n{opening}"
    res = claude.json(TEXT_SYSTEM, [{"role": "user", "content": msg}], TEXT_SCHEMA, effort="low")
    res["hashtags"] = clean_hashtags(res["hashtags"])
    return res


def clean_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = "".join(ch for ch in t.lstrip("#") if ch.isalnum() or ch == "_")
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def platform_text(short: dict[str, Any], platform: str) -> dict[str, str]:
    """The title and description/caption to post on one app, with the link to the full video."""
    title = short["title"].strip()
    caption = short["caption"].strip()
    url = short["youtube_url"].strip()
    tags = " ".join(f"#{t}" for t in short["hashtags"])
    if platform == "youtube":
        tags = " ".join(f"#{t}" for t in ["Shorts", *[t for t in short["hashtags"] if t.lower() != "shorts"]])
        full_title = title if "#shorts" in title.lower() else f"{title} #Shorts"
        if len(full_title) > 100:
            full_title = title[:100]
        desc = "\n\n".join(x for x in [caption, f"Watch the full video: {url}" if url else "", tags] if x)
        return {"title": full_title, "text": desc[:5000]}
    link = f"Full video on YouTube: {url}" if url else ""
    text = "\n\n".join(x for x in [caption, link, tags] if x)
    return {"title": title, "text": text[:2200]}
