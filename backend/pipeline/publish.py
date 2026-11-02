"""Step 9: titles, description with sources, chapters, tags, thumbnail prompts."""
from __future__ import annotations

from typing import Any

from pipeline.claude_client import INT, STR, Claude, arr, obj
from pipeline.prompts import visual_bible

SYSTEM = """You package true-story YouTube videos for publishing. Write metadata that is accurate \
(no claims the video doesn't support), curiosity-driven and advertiser-friendly.

- titles: 5 options under 70 characters. Curiosity without lying. Vary the angle.
- description: 2 short hook paragraphs (the first 150 characters show in search, so lead with the \
mystery), then a one-line note that the video is narrated with an AI voice and illustrated with \
stick-figure art. Do NOT include chapters or sources; they are appended automatically.
- tags: 12-20 search phrases.
- chapters: 5-8 chapters. Each starts at a beat index where the story clearly moves to a new part. \
The first chapter MUST start at beat 0. Titles are 2-5 words and must not spoil the ending.
- thumbnails: 3 thumbnail ideas, each a different angle on the video's biggest mystery or moment \
(e.g. a shocked face next to the key object; the dangerous or mysterious thing shown huge; a tiny \
figure dwarfed by something). A thumbnail is seen tiny on a phone, so keep each one SIMPLE:
  - scene: under 25 words. One stick figure (two at most) with ONE big, exaggerated emotion \
(shock, terror, disbelief) and ONE large object, both filling the right two thirds of the frame. \
Nothing else: no crowds, no busy scenery, no small details. Describe recurring characters and \
objects with their look from the visual bible, if one is given.
  - background: one plain, solid, bright color that contrasts with the scene (e.g. "bright red", \
"deep navy blue", "sunny yellow").
  Never ask for text, letters, numbers, signs or speech bubbles; the title is added afterwards."""

SCHEMA = obj({
    "titles": arr(STR),
    "description": STR,
    "tags": arr(STR),
    "chapters": arr(obj({"beat": INT, "title": STR})),
    "thumbnails": arr(obj({"scene": STR, "background": STR})),
})

# Thumbnails get their own short style instead of the long one for the video's images.
THUMB_STYLE = (
    "Simple bold stick figure thumbnail: thick black outlines, round white head with a huge exaggerated "
    "expression, flat bright colors, plain solid {background} background, high contrast, big shapes that "
    "read at a glance, left third of the frame left empty, 16:9. No text, no letters, no numbers."
)


def thumbnail_prompt(scene: str, background: str) -> str:
    return f"{scene.strip().rstrip('.')}. {THUMB_STYLE.format(background=background.strip() or 'bright yellow')}"


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
        "thumbnail_prompts": [thumbnail_prompt(t["scene"], t["background"]) for t in res["thumbnails"]],
    }
