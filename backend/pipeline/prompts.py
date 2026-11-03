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

OLD_LIMBS = "thin black stick limbs"
BODY = (
    "thin black stick arms and legs that show as plain black lines wherever clothing does not cover them, "
    "with sleeves and trousers drawn as flat colored clothing over them, and simple round cartoon hands "
    "that are always the same color as the head, never black, unless a character's look gives gloves or mittens"
)

BASE_STYLE = (
    "Minimalist stick figure illustration, clean hand-drawn style: bold black outlines, round heads "
    "(white unless a character's look gives a skin tone) with simple expressive faces (dot eyes, "
    "eyebrows, line mouth) drawn the same way for everyone, " + BODY + ", "
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
stocky), hair and facial hair, headwear, clothing with its colors and whether its sleeves are long or short, and one item they carry. Spell \
out every detail so the image model has nothing to invent, e.g. "stick figure, tall and thin, short \
gray hair, tiny round glasses, a gray bowler hat, a long navy coat with brass buttons, carrying a \
brown leather briefcase". Each look must be easy to tell apart from the others at a glance. Never \
aim for a real likeness.
  Heads are white by default. Only when race or ethnicity is part of the history being told (civil \
rights, apartheid, colonialism, slavery, segregation), give a skin tone as a plain color right after \
"stick figure", e.g. "stick figure, medium brown head and hands, …", and use the same words in all of \
that character's variants. A skin tone only changes the fill color: never describe or change facial \
features or body shape to show ethnicity, and describe hair like anyone else's. Otherwise do not mention skin at all.
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
- Each beat says who is drawn in it ("in this image:"), with the exact look for that point in the \
story. Describe every one of them with that look text, copied word for word, and never refer to \
them vaguely ("a dusty figure", "a man", "the prisoner") instead. Never write a character's name in \
the scene (the image model may refuse real people or try to draw a real likeness): the look text \
alone tells the images who is who. Do not draw other characters from \
the CHARACTERS list in that image; unnamed extras are fine. Extras have white heads, unless the \
CHARACTERS give skin tones: then a crowd may mix plain skin-tone fill colors where the story calls \
for it, with every face drawn the same simple way. Never add, drop or change details of a \
look on your own (no "now with a beard"): if a look changes, it is because a variant says so.
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


CAST_SYSTEM = """You cast the images of a narrated stick-figure video. Each beat of narration becomes \
one still image. For every beat, decide which of the CHARACTERS below are drawn in that image, so \
each of them can be described the same way in every image they are in.
- Work out who the picture shows at that moment even when the narration does not name them: follow \
"he", "she", "they", "the man", "a tired figure" back to the character they mean, and include who is \
physically there (the soldiers pulling someone out AND the person being pulled out).
- Beats that continue the same moment keep the same people in the picture until the story moves on.
- For each one, pick the look for that point in the story: "" for their main look, or the exact \
`when` text of one of their variants.
- Only list characters from the list, using their names exactly as written. Leave out crowds and \
unnamed extras (the image can still show them). An image of only a place, an object, a map or an \
abstract metaphor has an empty cast."""

CAST_SCHEMA = obj({"beats": arr(obj({"idx": INT, "cast": arr(obj({"name": STR, "variant": STR}))}))})


def _find(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    """Exact match first, then ignoring case, then one name containing the other ("Eric Maddox" for
    "Eric Maddox (Army interrogator)")."""
    v = value.strip().casefold()
    for test in (lambda x: x == v, lambda x: x.startswith(v) or v.startswith(x), lambda x: v in x or x in v):
        hit = next((it for it in items if v and test(it[key].strip().casefold())), None)
        if hit:
            return hit
    return None


def resolve_cast(guide: dict[str, Any], cast: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep only characters in the guide, with their canonical name and a variant that exists."""
    out: list[dict[str, str]] = []
    for c in cast:
        ch = _find(guide["characters"], "name", c.get("name", ""))
        if not ch or any(o["name"] == ch["name"] for o in out):
            continue
        v = _find(ch.get("variants") or [], "when", c.get("variant", "")) if c.get("variant") else None
        out.append({"name": ch["name"], "variant": v["when"] if v else ""})
    return out


def cast_looks(guide: dict[str, Any], cast: list[dict[str, str]] | None) -> list[tuple[str, str]]:
    """(name, exact look text) for each character drawn in an image."""
    out = []
    for c in resolve_cast(guide, cast or []):
        ch = _find(guide["characters"], "name", c["name"])
        v = _find(ch.get("variants") or [], "when", c["variant"]) if c["variant"] else None
        out.append((c["name"], v["look"] if v else character_look(ch)))
    return out


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def missing_looks(scene: str, looks: list[tuple[str, str]]) -> list[str]:
    """Names of characters whose look text is not in the scene word for word."""
    s = _norm(scene)
    return [name for name, look in looks if _norm(look) not in s]


def with_looks(scene: str, looks: list[tuple[str, str]]) -> str:
    """Last resort when Claude keeps leaving a look out: add it to the end of the scene."""
    gone = [look for name, look in looks if name in missing_looks(scene, looks)]
    return f"{scene.rstrip('.')}. Characters in this image: {'; '.join(gone)}." if gone else scene


def _cast_line(looks: list[tuple[str, str]]) -> str:
    if not looks:
        return "    in this image: none of the listed characters"
    return "    in this image (copy each look, not the name): " + "; ".join(f"{name} = {look}" for name, look in looks)


def cast_beats(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
               group: int = 80, progress: Callable[[str, float], None] = lambda m, f: None,
               known: dict[int, list[dict[str, str]]] | None = None) -> dict[int, list[dict[str, str]]]:
    """Return {beat idx: [{"name", "variant"}]}: who is drawn in each image, decided from the whole
    story before any prompt is written. Groups go in story order and see the cast of the beats just
    before them, so a scene that runs across groups keeps its people."""
    if not guide["characters"]:
        return {b["idx"]: [] for b in beats}
    chars = "\n".join(character_lines(c) for c in guide["characters"])
    system = cached(f"{CAST_SYSTEM}\n\nCHARACTERS\n{chars}\n\nFULL SCRIPT (for context)\n{script}")
    out: dict[int, list[dict[str, str]]] = dict(known or {})
    groups = [beats[i:i + group] for i in range(0, len(beats), group)]
    for n, g in enumerate(groups, 1):
        prev = sorted(i for i in out if i < g[0]["idx"])[-6:]
        lines = []
        if prev:
            lines += ["Already cast (the images just before these):"] + [
                f"  {i}: " + (", ".join(c["name"] + (f" ({c['variant']})" if c["variant"] else "") for c in out[i]) or "none")
                for i in prev]
        lines += ["BEATS TO CAST:"] + [f"{b['idx']}: {b['text']}" for b in g]
        want = {b["idx"] for b in g}
        for _ in range(2):
            res = claude.json(system, [{"role": "user", "content": "\n".join(lines)}], CAST_SCHEMA, effort="medium")
            for b in res["beats"]:
                if b["idx"] in want:
                    out[b["idx"]] = resolve_cast(guide, b["cast"])
            if want <= out.keys():
                break
        progress(f"Cast group {n} of {len(groups)}", n / len(groups))
    return {b["idx"]: out.get(b["idx"], []) for b in beats}


def _context_system(script: str, guide: dict[str, Any]) -> list[dict[str, Any]]:
    return cached(f"{SCENE_SYSTEM}\n\n{visual_bible(guide)}\n\nFULL SCRIPT (for context)\n{script}")


def _previous(written: dict[int, dict[str, str]], before_idx: int, n: int = CARRY_OVER) -> list[str]:
    prev = sorted(i for i in written if i < before_idx)[-n:]
    return [f"  {i}: {written[i]['scene']}" for i in prev]


def write_scenes(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
                 group: int = 40, progress: Callable[[str, float], None] = lambda m, f: None,
                 written: dict[int, dict[str, str]] | None = None,
                 opening: set[int] | None = None,
                 cast: dict[int, list[dict[str, str]]] | None = None) -> dict[int, dict[str, str]]:
    """Return {beat idx: {"scene", "label"}}.

    Groups are written in story order, one after another: each request sees the last scenes
    already written (from earlier groups, or from `written`, the project's existing prompts), so the
    images carry on from each other instead of every group starting fresh. `opening` holds the beats
    of the first minute (also used for the Short), which get extra eye-catching images. `cast` (from
    cast_beats) says who is in each image; every scene must carry those characters' looks word for
    word, and is asked for again (then patched) if it leaves one out."""
    opening = opening or set()
    looks = {b["idx"]: cast_looks(guide, (cast or {}).get(b["idx"])) for b in beats}
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
        lines += ["BEATS TO ILLUSTRATE:"]
        for b in g:
            lines += [f"{b['idx']}: {b['text']}"] + ([_cast_line(looks[b["idx"]])] if cast is not None else [])
        lines += ["Narration just after (do not describe):"] + [f"  {b['idx']}: {b['text']}" for b in after]
        want = {b["idx"] for b in g}
        out: dict[int, dict[str, str]] = {}
        good: set[int] = set()
        for _ in range(3):
            todo = sorted(want - good)
            if not todo:
                break
            ask = "\n".join(lines)
            if out:
                ask += f"\n\nOnly return scenes for these beat indices: {todo}"
                fix = [f"  {i}: left out {', '.join(missing_looks(out[i]['scene'], looks[i]))}" for i in todo if i in out]
                if fix:
                    ask += ("\nThese scenes did not describe everyone in the image with their exact look text; "
                            "rewrite them with each look copied word for word:\n" + "\n".join(fix))
            res = claude.json(system, [{"role": "user", "content": ask}], SCENES_SCHEMA, effort="medium")
            for s in res["scenes"]:
                if s["idx"] in want:
                    out[s["idx"]] = {"scene": s["scene"].strip(), "label": clean_label(s.get("label", ""))}
                    if not missing_looks(out[s["idx"]]["scene"], looks[s["idx"]]):
                        good.add(s["idx"])
        for i in out:
            out[i]["scene"] = with_looks(out[i]["scene"], looks[i])
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
                   opening: bool = False, cast: list[dict[str, str]] | None = None) -> dict[str, str]:
    by_idx = {b["idx"]: b for b in beats}
    written = written or {}
    looks = cast_looks(guide, cast)
    near = [by_idx[i] for i in range(idx - 2, idx + 3) if i in by_idx]
    ask = "\n".join(f"{'>> ' if b['idx'] == idx else '   '}{b['idx']}: {b['text']}" for b in near)
    ask = f"Write a fresh scene for beat {idx} only (marked >>).\n{ask}"
    if cast is not None:
        ask += "\n" + _cast_line(looks)
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
            return {"scene": with_looks(s["scene"].strip(), looks), "label": clean_label(s.get("label", ""))}
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


def with_body_rule(style_prefix: str) -> str:
    """Style guides made before the arms-and-hands rule get it in place of their old limbs phrase."""
    if BODY in style_prefix:
        return style_prefix
    return style_prefix.replace(OLD_LIMBS, BODY, 1)


def full_prompt(style_prefix: str, scene: str, title: str = "") -> str:
    body = f"{scene.rstrip('.')}. {with_body_rule(style_prefix)}"
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
