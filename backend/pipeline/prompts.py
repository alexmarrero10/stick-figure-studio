"""Step 4: image prompts for Google Flow, one per beat, written out in batches of 24.

Consistency across a whole video comes from a visual bible (the style guide): characters with a
full fixed look, plus recurring objects and places, each with one fixed look that every prompt
repeats word for word. Scenes are written in story order, each group seeing the scenes already
written before it, so neighbouring images flow into each other.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from pipeline.claude_client import INT, STR, Claude, arr, cached, obj

BASE_STYLE = (
    "Minimalist stick figure illustration, clean hand-drawn style: bold black outlines, round white "
    "heads with simple expressive faces (dot eyes, eyebrows, line mouth), thin black stick limbs, "
    "flat colors for props, clothing and backgrounds ({palette}). The background fills the whole frame "
    "and matches the scene's place, time of day and lighting: night scenes are dark, indoor scenes show "
    "the room, never a blank white or paper background. Uncluttered composition with one clear focal point, "
    "16:9 widescreen. No text, no letters, no numbers, no captions, no speech bubbles, no watermark."
)

STYLE_SYSTEM = """You are the art director for a stick-figure explainer channel. Every image in a \
video must look like it belongs to the same series, and anything that appears more than once must \
look the same every time. Images are generated one at a time, so consistency only comes from \
describing each recurring thing with exactly the same words in every prompt. From the script, define:
- palette: 4-6 flat accent colors that suit the story's mood, as plain color names (e.g. "muted red, \
navy blue, mustard yellow, sage green").
- characters: every recurring person or group, at most 8. For each, a `look` of 20-40 words that \
fully fixes how the stick figure is drawn, starting with "stick figure": build (tall, short, \
stocky), hair and facial hair, headwear, clothing with its colors, and one item they carry. Spell \
out every detail so the image model has nothing to invent, e.g. "stick figure, tall and thin, short \
gray hair, tiny round glasses, a gray bowler hat, a long navy coat with brass buttons, carrying a \
brown leather briefcase". Each look must be easy to tell apart from the others at a glance. Do not \
use skin color or real likeness.
  If the story changes how a character looks (in hiding, in disguise, years older, captured, in \
uniform), add a `variants` entry for each change: `when` names that part of the story, and `look` \
is the complete 20-40 word look for it, written in full (not "same as before but…"), keeping \
whatever stays the same in the same words, e.g. when "in hiding, December 2003": "stick figure, \
stocky, long scruffy gray-black beard, messy uncombed black hair, no hat, a dirty charcoal \
undershirt and loose olive trousers". Otherwise leave `variants` empty.
- props: every object, vehicle or animal that appears in more than one beat (a ship, a car, a \
map, a dog, a hole in the ground), at most 12. For each, a `look` of 20-40 words fixing its size \
next to a stick figure, its shape, colors from the palette and two or three distinctive details \
that stay visible from any angle. For something seen from several sides (a hole seen from above, \
from the side and from inside; a building seen outside and inside), say what each side looks \
like, e.g. "a three-masted wooden ship about ten stick figures long, black hull, one mustard-gold \
stripe along the side, cream sails, a small red flag at the stern".
- locations: every place the story returns to, at most 8. For each, a `look` of 20-40 words fixing \
the background: landscape or room, the fixed objects and where they are, colors and light, e.g. \
"flat white snowy tundra under a pale gray sky, low icy-blue ridges on the horizon, scattered dark \
rocks, one tall dark rock spire on the left".
- setting_notes: one or two sentences on the overall world (era, climate, time of day) that apply \
to every image.

The image model must never draw text, so no look may contain writing, lettering, titles, mastheads, \
labels or numbers: describe newspapers, letters, maps and notes by shape and color only (e.g. "a \
folded cream broadsheet covered in thin gray squiggle lines")."""

LOOK = obj({"name": STR, "look": STR})
STYLE_SCHEMA = obj({
    "palette": STR,
    "setting_notes": STR,
    "characters": arr(obj({"name": STR, "look": STR, "variants": arr(obj({"when": STR, "look": STR}))})),
    "props": arr(LOOK),
    "locations": arr(LOOK),
})

SCENE_SYSTEM = """You write image prompts for Google Flow that illustrate a narrated stick-figure \
video. Each beat of narration gets ONE still image that is on screen while those words are spoken. \
The fixed style text is added automatically; you write only the scene description.

Every image is generated on its own, with no memory of the others, so the words are the only thing \
that keeps the video consistent. For each beat, write a scene description (40-150 words) that:
- Shows literally and clearly what the narration says at that moment, or a simple visual metaphor \
if it is abstract (e.g. a giant clock looming over a tiny figure for "time was running out").
- Describes every character in the picture with their full look text from the CHARACTERS list, \
copied word for word, never by name alone. When the story is at a point covered by one of their \
variants, use that variant's look instead. Never add, drop or change details on your own (no \
"now with a beard"): if the look changes, it is because a variant says so.
- Whenever a RECURRING OBJECT or RECURRING PLACE from the lists below appears, describe it with its \
exact look text, copied word for word. Never paraphrase, shorten or recolor it, and never invent a \
different look for something on the lists.
- Always sets the background to match that moment of the story: name the place, the time of day \
and the light or sky color (e.g. "dark navy night sky with a thin moon", "dim lamp-lit room with \
brown walls", "harsh midday desert sun"). Keep it the same as neighbouring beats that happen at the \
same place and time. For an abstract metaphor, use a solid background color that fits the mood. \
Never leave the background blank or white.
- Flows on from the scene before it: if the story stays in the same place, keep the same location \
look, time of day, weather and prop positions; carry over changes the story has made (a ship \
trapped in ice stays trapped, a broken window stays broken) until the story changes them.
- Beats are short (1-3 seconds), so several in a row often cover the same moment. Treat them like \
quick cuts in one sequence: move the story on a little in each (a reaction, the next step of the \
action, a detail being noticed) rather than repeating the same picture.
- Gives the action, the emotion on the faces and a camera framing. Vary framing across \
neighbouring beats (wide shot, medium shot, close-up on hands or an object, over-the-shoulder, \
top-down, silhouette) so cuts feel dynamic, while the place and objects stay the same.
- Never asks for written words, signs with lettering, numbers, logos, real brands, real faces, \
speech bubbles or thought bubbles. Show money as stacks of green bills, documents as blank paper or \
gray squiggle lines, screens as glowing rectangles, and speaking as an open mouth and gestures.
- Describes a single still frame: never camera movement such as zooming, panning or tracking.
- Avoids gore and graphic violence: imply danger with poses, shadows and props.

OPENING IMAGES: the beats marked as the opening are the first minute of the video, which is also \
posted on its own as a YouTube Short, Reel and TikTok. They must stop a viewer scrolling past, so \
make them the most eye-catching images in the video: one bold, dramatic focal point; big, \
exaggerated emotions (wide eyes, gaping mouths, frantic poses); strong contrast and the boldest \
colors of the palette; close-ups and low or high dramatic angles; danger, scale or mystery you can \
see at a glance (a towering iceberg over a tiny ship, a figure frozen in a doorway). Keep them \
simple enough to read on a phone screen in under a second, and still consistent with the visual \
bible.

Also give each beat a label: a 1-3 word title for the image naming its setting or subject (e.g. \
"Victorian London street", "Vault door opening"). Plain words only, no punctuation or numbers."""

SCENES_SCHEMA = obj({"scenes": arr(obj({"idx": INT, "label": STR, "scene": STR}))})

# How many already-written scenes each request sees, so the next images flow on from them.
CARRY_OVER = 8


def make_style_guide(claude: Claude, script: str) -> dict[str, Any]:
    g = claude.json(STYLE_SYSTEM, [{"role": "user", "content": f"SCRIPT\n{script}"}], STYLE_SCHEMA, effort="medium")
    g["style_prefix"] = BASE_STYLE.format(palette=g["palette"])
    return g


def character_look(c: dict[str, Any]) -> str:
    # Guides made before full looks only had a short marker.
    return c.get("look") or f"stick figure with {c.get('marker', '')}"


def character_lines(c: dict[str, Any]) -> str:
    lines = [f"- {c['name']}: {character_look(c)}"]
    lines += [f"    {v['when']}: {v['look']}" for v in c.get("variants") or []]
    return "\n".join(lines)


def visual_bible(guide: dict[str, Any]) -> str:
    def looks(items: list[dict[str, str]]) -> str:
        return "\n".join(f"- {x['name']}: {x['look']}" for x in items) or "- (none)"
    chars = "\n".join(character_lines(c) for c in guide["characters"]) or "- (none)"
    return (f"CHARACTERS (use the look text word for word)\n{chars}\n\nRECURRING OBJECTS (use the look text word for word)\n"
            f"{looks(guide.get('props') or [])}\n\nRECURRING PLACES (use the look text word for word)\n"
            f"{looks(guide.get('locations') or [])}\n\nWORLD\n{guide.get('setting_notes', '')}")


def _context_system(script: str, guide: dict[str, Any]) -> list[dict[str, Any]]:
    return cached(f"{SCENE_SYSTEM}\n\n{visual_bible(guide)}\n\nFULL SCRIPT (for context)\n{script}")


def _previous(written: dict[int, dict[str, str]], before_idx: int, n: int = CARRY_OVER) -> list[str]:
    prev = sorted(i for i in written if i < before_idx)[-n:]
    return [f"  {i}: {written[i]['scene']}" for i in prev]


def write_scenes(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
                 group: int = 40, progress: Callable[[str, float], None] = lambda m, f: None,
                 written: dict[int, dict[str, str]] | None = None,
                 opening: set[int] | None = None) -> dict[int, dict[str, str]]:
    """Return {beat idx: {"scene", "label"}}.

    Groups are written in story order, one after another: each request sees the last scenes
    already written (from earlier groups, or from `written`, the project's existing prompts), so the
    images carry on from each other instead of every group starting fresh. `opening` holds the beats
    of the first minute (also used for the Short), which get extra eye-catching images."""
    opening = opening or set()
    system = _context_system(script, guide)
    groups = [beats[i:i + group] for i in range(0, len(beats), group)]
    by_idx = {b["idx"]: b for b in beats}
    known: dict[int, dict[str, str]] = dict(written or {})

    def run(g: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
        prev = _previous(known, g[0]["idx"])
        before = [by_idx[i] for i in range(g[0]["idx"] - 3, g[0]["idx"]) if i in by_idx and i not in known]
        after = [by_idx[i] for i in range(g[-1]["idx"] + 1, g[-1]["idx"] + 4) if i in by_idx]
        lines: list[str] = []
        if prev:
            lines += ["Scenes already written for the images just before these (continue on from them; "
                      "do not rewrite them):"] + prev
        if before:
            lines += ["Narration just before (do not describe):"] + [f"  {b['idx']}: {b['text']}" for b in before]
        hook = sorted(b["idx"] for b in g if b["idx"] in opening)
        if hook:
            lines += [f"Beats {hook[0]}-{hook[-1]} are OPENING IMAGES (see the rules): make them the most "
                      "eye-catching images of the video."]
        lines += ["BEATS TO ILLUSTRATE:"] + [f"{b['idx']}: {b['text']}" for b in g]
        lines += ["Narration just after (do not describe):"] + [f"  {b['idx']}: {b['text']}" for b in after]
        want = {b["idx"] for b in g}
        out: dict[int, dict[str, str]] = {}
        for _ in range(3):
            missing = sorted(want - out.keys())
            if not missing:
                break
            ask = "\n".join(lines)
            if out:
                ask += f"\n\nOnly return scenes for these beat indices: {missing}"
            res = claude.json(system, [{"role": "user", "content": ask}], SCENES_SCHEMA, effort="medium")
            for s in res["scenes"]:
                if s["idx"] in want:
                    out[s["idx"]] = {"scene": s["scene"].strip(), "label": clean_label(s.get("label", ""))}
        return out

    scenes: dict[int, dict[str, str]] = {}
    for n, g in enumerate(groups, 1):
        res = run(g)
        scenes.update(res)
        known.update(res)
        progress(f"Wrote prompts for group {n} of {len(groups)}", n / len(groups))
    return scenes


def regenerate_one(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
                   idx: int, note: str = "", written: dict[int, dict[str, str]] | None = None,
                   opening: bool = False) -> dict[str, str]:
    by_idx = {b["idx"]: b for b in beats}
    written = written or {}
    near = [by_idx[i] for i in range(idx - 2, idx + 3) if i in by_idx]
    ask = "\n".join(f"{'>> ' if b['idx'] == idx else '   '}{b['idx']}: {b['text']}" for b in near)
    ask = f"Write a fresh scene for beat {idx} only (marked >>).\n{ask}"
    around = [f"  {i}: {written[i]['scene']}" for i in range(idx - 3, idx + 4) if i != idx and i in written]
    if around:
        ask += "\n\nThe neighbouring images look like this; keep the new one consistent with them:\n" + "\n".join(around)
    if opening:
        ask += "\n\nThis beat is an OPENING IMAGE (see the rules): make it eye-catching."
    if note:
        ask += f"\n\nDirection from the channel owner: {note}"
    res = claude.json(_context_system(script, guide), [{"role": "user", "content": ask}], SCENES_SCHEMA, effort="medium")
    for s in res["scenes"]:
        if s["idx"] == idx:
            return {"scene": s["scene"].strip(), "label": clean_label(s.get("label", ""))}
    raise ValueError("Claude did not return a scene for that beat")


# Flow names a downloaded image after the first 3 words of its prompt's title, so titles stop there.
LABEL_WORDS = 3
DANGLING = set("a an the of on in at to from with and or its their his her".split())


def clean_label(label: str) -> str:
    """Keep labels safe for file names: words only, at most 3 of them, not ending on "of", "the"..."""
    words = re.sub(r"[^A-Za-z0-9' ]+", " ", label).split()[:LABEL_WORDS]
    while len(words) > 1 and words[-1].lower() in DANGLING:
        words.pop()
    return " ".join(words)


# Camera directions and filler that make poor titles ("Medium shot of the stick figure with the ...").
FILLER = set("""a an the of on in at to from with and or its their his her showing shows shot shots view angle
close closeup close-up up extreme medium wide tight full over the-shoulder shoulder top down top-down low high
establishing framing frame focus focused stick figure figures""".split())


def fallback_label(scene: str) -> str:
    """A label from the scene's first meaningful words, for prompts that have no title yet."""
    words = [w for w in re.sub(r"[^A-Za-z0-9' -]+", " ", scene).split() if w.lower() not in FILLER]
    return clean_label(" ".join(words[:LABEL_WORDS]).capitalize()) or "Image"


LABELS_SYSTEM = """You title images for a stick-figure video. For each scene description, write a 1-3 word title naming the image's setting or subject (e.g. "Victorian London street", "Vault door opening", "Frozen tundra survey"). Never more than 3 words: Flow keeps only the first 3 words when it names the image file. Never use camera words (shot, close-up, wide, angle) or "stick figure". Plain words only, no punctuation or numbers."""

LABELS_SCHEMA = obj({"labels": arr(obj({"idx": INT, "label": STR}))})


def write_labels(claude: Claude, rows: list[dict[str, Any]], group: int = 60,
                 progress: Callable[[str, float], None] = lambda m, f: None) -> dict[int, str]:
    """Titles for existing prompts without rewriting their scenes. rows need idx and scene."""
    out: dict[int, str] = {}
    groups = [rows[i:i + group] for i in range(0, len(rows), group)]
    for n, g in enumerate(groups, 1):
        ask = "\n".join(f"{r['idx']}: {r['scene']}" for r in g)
        res = claude.json(LABELS_SYSTEM, [{"role": "user", "content": ask}], LABELS_SCHEMA, effort="low")
        want = {r["idx"] for r in g}
        for item in res["labels"]:
            label = clean_label(item.get("label", ""))
            if item["idx"] in want and label:
                out[item["idx"]] = label
        progress(f"Titled {n} of {len(groups)} groups", n / len(groups))
    return out


def image_title(number: int, label: str, scene: str) -> str:
    """'7 - Victorian London street'. Flow names the downloaded image after the start of the prompt."""
    return f"{number} - {clean_label(label) or fallback_label(scene)}"


def full_prompt(style_prefix: str, scene: str, title: str = "") -> str:
    body = f"{scene.rstrip('.')}. {style_prefix}"
    return f"{title}. {body}" if title else body


def batch_of(position: int, batch_size: int = 24) -> int:
    """1-based batch number for the beat at a 0-based position."""
    return position // batch_size + 1


def number_in_batch(position: int, batch_size: int = 24) -> int:
    """1-based image number within its batch for the beat at a 0-based position."""
    return position % batch_size + 1


def prompt_text(style_prefix: str, p: dict[str, Any], batch_size: int = 24) -> str:
    """The full numbered prompt for a stored prompt row (needs idx, scene, label)."""
    title = image_title(number_in_batch(p["idx"], batch_size), p.get("label", ""), p["scene"])
    return full_prompt(style_prefix, p["scene"], title)


def batch_header(batch_no: int, n_batches: int, count: int) -> str:
    """A note for the Flow agent at the top of each batch. The same agent makes every batch, so it
    is told to keep matching the images it has already made."""
    text = (f"INSTRUCTIONS FOR BATCH {batch_no} OF {n_batches} (do not make an image for this paragraph). "
            f"Generate {count} images, one for each numbered prompt below, in order, one image per prompt. "
            f"Each image is named after its prompt's number and title, for example \"1 - Victorian London "
            f"street\"; keep that number with its image. ")
    if batch_no > 1:
        text += "These images continue the same video as the earlier batches you made. "
    text += ("Keep every recurring character, object and place looking exactly the same in every image: "
             "the prompts repeat the same description for each one, so follow those descriptions closely and "
             "match how you drew them before. Keep the same art style throughout.")
    return text


def batch_texts(style_prefix: str, prompts: list[dict[str, Any]], batch_size: int = 24) -> dict[int, str]:
    """{batch number: the text to paste into Flow}: the agent note, then one prompt per paragraph."""
    batches: dict[int, list[str]] = {}
    for p in prompts:
        batches.setdefault(p["batch_no"], []).append(prompt_text(style_prefix, p, batch_size))
    total = max(batches, default=0)
    return {n: "\n\n".join([batch_header(n, total, len(items)), *items]) + "\n"
            for n, items in sorted(batches.items())}


def write_batch_files(folder: Path, style_prefix: str, prompts: list[dict[str, Any]], batch_size: int = 24) -> list[str]:
    """Write batch_XX.txt files, ready to paste into Flow."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("batch_*.txt"):
        old.unlink()
    names = []
    for n, text in batch_texts(style_prefix, prompts, batch_size).items():
        name = f"batch_{n:02d}.txt"
        (folder / name).write_text(text, encoding="utf-8")
        names.append(name)
    return names
