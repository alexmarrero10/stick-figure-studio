"""Step 9: titles, description with sources, chapters, tags, thumbnail prompts."""
from __future__ import annotations

from typing import Any

from pipeline.claude_client import INT, STR, Claude, arr, obj
from pipeline.prompts import BASE_STYLE, visual_bible, with_body_rule

THUMB_RULES = """A thumbnail is seen tiny on a phone, so keep each one SIMPLE:
  - scene: One stick figure (two at most) with ONE big, exaggerated emotion (shock, terror, \
disbelief) and ONE large object, both filling the right two thirds of the frame. Nothing else: no \
crowds, no small details. Describe every recurring character, object or place from the visual bible \
with its look text copied word for word (for a character, the look for that point in the story), so \
the thumbnail matches the video; besides those looks, keep the scene under 25 words. Never write a \
character's name.
  - background: a simple, uncluttered version of the place where that moment happens, in the \
video's colors and light, with strong contrast against the figure (e.g. "dark navy night sky over \
dark green orange trees"). Never blank or plain white.
  Never ask for text, letters, numbers, signs or speech bubbles; the title is added afterwards."""

SYSTEM = f"""You package true-story YouTube videos for publishing. Write metadata that is accurate \
(no claims the video doesn't support), curiosity-driven and advertiser-friendly.

- titles: 5 options under 70 characters. Curiosity without lying. Vary the angle.
- description: 2 short hook paragraphs (the first 150 characters show in search, so lead with the \
mystery). Do NOT include chapters or sources; they are appended automatically.
- tags: 12-20 search phrases.
- chapters: 5-8 chapters. Each starts at a beat index where the story clearly moves to a new part. \
The first chapter MUST start at beat 0. Titles are 2-5 words and must not spoil the ending.
- thumbnails: 3 thumbnail ideas, each a different angle on the video's biggest mystery or moment \
(e.g. a shocked face next to the key object; the dangerous or mysterious thing shown huge; a tiny \
figure dwarfed by something). {THUMB_RULES}"""

THUMB_ASK_SYSTEM = f"""You turn a YouTube creator's idea for a thumbnail into an image prompt for \
their stick-figure history video. Draw what they ask for, filling in what they leave out. Follow \
these rules unless the request clearly asks otherwise (for example more figures): \
{THUMB_RULES}"""

THUMB_SCHEMA = obj({"scene": STR, "background": STR})

SCHEMA = obj({
    "titles": arr(STR),
    "description": STR,
    "tags": arr(STR),
    "chapters": arr(obj({"beat": INT, "title": STR})),
    "thumbnails": arr(obj({"scene": STR, "background": STR})),
})

# Thumbnails use the video's own style text, so they look like its images, plus what a thumbnail
# needs to read at a glance on a phone.
THUMB_FRAMING = (
    "YouTube thumbnail: a huge exaggerated expression, big bold shapes that read at a glance on a phone, "
    "high contrast, the left third of the frame kept clear."
)


def thumbnail_prompt(scene: str, background: str, style_prefix: str | None = None) -> str:
    style = with_body_rule(style_prefix) if style_prefix else BASE_STYLE.format(palette="bold flat colors")
    return (f"{scene.strip().rstrip('.')}. Background: {background.strip().rstrip('.') or 'a simple bold backdrop'}. "
            f"{THUMB_FRAMING} {style}")


def ask_thumbnail(claude: Claude, request: str, title: str, script: str,
                  guide: dict[str, Any] | None = None) -> str:
    """A thumbnail prompt in the video's style, written from the creator's own description."""
    msg = f"VIDEO TITLE: {title}\n\nSCRIPT\n{script}"
    if guide:
        msg += f"\n\nVISUAL BIBLE (so the thumbnail matches the video)\n{visual_bible(guide)}"
    msg += f"\n\nTHE CREATOR'S IDEA FOR THE THUMBNAIL\n{request.strip()}"
    res = claude.json(THUMB_ASK_SYSTEM, [{"role": "user", "content": msg}], THUMB_SCHEMA, effort="medium")
    return thumbnail_prompt(res["scene"], res["background"], guide["style_prefix"] if guide else None)


def merge_tags(specific: list[str], general: list[str], limit: int = 500) -> list[str]:
    """The video's own tags, then the channel's general ones, without repeats and within YouTube's
    500-character limit (each tag counts its length plus a comma, plus quotes if it has a space)."""
    out: list[str] = []
    seen: set[str] = set()
    used = 0
    for tag in [*specific, *general]:
        tag = " ".join(tag.replace(",", " ").split())
        cost = len(tag) + 1 + (2 if " " in tag else 0)
        if not tag or tag.lower() in seen or used + cost > limit:
            continue
        seen.add(tag.lower())
        out.append(tag)
        used += cost
    return out


def _mmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def generate(claude: Claude, title: str, script: str, beats: list[dict[str, Any]],
             words: list[dict[str, Any]], sources: list[dict[str, str]],
             general_tags: list[str] | None = None, guide: dict[str, Any] | None = None) -> dict[str, Any]:
    beat_lines = "\n".join(f"{b['idx']}: {b['text']}" for b in beats)
    msg = f"WORKING TITLE: {title}\n\nSCRIPT\n{script}\n\nBEATS\n{beat_lines}"
    if guide:
        msg += f"\n\nVISUAL BIBLE (so thumbnails match the video)\n{visual_bible(guide)}"
    res = claude.json(SYSTEM, [{"role": "user", "content": msg}], SCHEMA, effort="medium")

    # Chapters need real timestamps; YouTube requires the first at 0:00 and each >= 10 s.
    by_idx = {b["idx"]: b for b in beats}
    chapters = []
    last_t = -999.0
    for c in sorted(res["chapters"], key=lambda c: c["beat"]):
        b = by_idx.get(c["beat"])
        if b is None:
            continue
        t = 0.0 if not chapters else (words[b["word_start"]]["start"] if words else 0.0)
        if chapters and t - last_t < 10:
            continue
        chapters.append({"time": _mmss(t), "title": c["title"]})
        last_t = t
    if not chapters or chapters[0]["time"] != "0:00":
        chapters.insert(0, {"time": "0:00", "title": "The story begins"})

    desc = res["description"].strip()
    if words and len(chapters) >= 3:
        desc += "\n\nChapters\n" + "\n".join(f"{c['time']} {c['title']}" for c in chapters)
    if sources:
        desc += "\n\nSources\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in sources[:15])
    return {
        "titles": res["titles"],
        "description": desc,
        "tags": merge_tags(res["tags"], general_tags or []),
        "chapters": chapters,
        "thumbnail_prompts": [thumbnail_prompt(t["scene"], t["background"], guide["style_prefix"] if guide else None)
                              for t in res["thumbnails"]],
    }
