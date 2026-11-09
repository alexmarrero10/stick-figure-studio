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
    "eyebrows, line mouth, no nose) drawn exactly the same way for everyone, hair drawn as one flat "
    "solid-color shape, " + BODY + ", "
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
fully fixes how the stick figure is drawn, starting with "stick figure" and its head color: build \
(tall, short, stocky), hair and facial hair, headwear, clothing with its colors and whether its \
sleeves are long or short, and one item they carry.
  Hair is what makes a character recognizable, so pin it down completely: one exact color ("dark \
brown", "steel gray", never just "dark" or "varied"), length, texture and how it sits, e.g. "short \
dark brown wavy hair combed straight back, receding at the temples". Use the same hair words in every \
variant unless the story changes the hair.
  Faces are the same simple face for everyone (dot eyes, eyebrows, line mouth, no nose). Never describe \
a nose, lips, jowls, chin, cheeks, ears, skin or face shape, even when the real person was known for \
them: exaggerated features turn into ethnic caricatures and change from image to image. Tell \
characters apart by build, hair, facial hair, glasses, headwear, clothing and what they carry.
  Spell out every detail so the image model has \
nothing to invent, e.g. "stick figure, white head and hands, tall and thin, short gray hair, tiny \
round glasses, a gray bowler hat, a long navy coat with brass buttons, carrying a brown leather \
briefcase". Each look must be easy to tell apart from the others at a glance. Never aim for a real \
likeness.
  Every look states its head color, the same words in all of that character's variants, so the \
image model never picks one itself: "white head and hands" by default. Only when race or ethnicity \
is part of the history being told (civil rights, apartheid, colonialism, slavery, segregation), use \
a plain skin tone in place of white, e.g. "stick figure, medium brown head and hands, …". A skin \
tone only changes the fill color: never describe or change facial features or body shape to show \
ethnicity, and describe hair like anyone else's.
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
like, each side starting with its name and a colon ("from above: … From the side: …"), e.g. "a three-masted wooden ship about ten stick figures long, black hull, one mustard-gold \
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
posted on its own as a Short. They must stop a viewer scrolling past, so \
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
    g["characters"] = add_head_colors(g["characters"])
    return g


def character_look(c: dict[str, Any]) -> str:
    # Guides made before full looks only had a short marker.
    return c.get("look") or with_head_color(f"stick figure with {c.get('marker', '')}")


_LEAD = re.compile(r"(stick figures?)\b[,\s]*", re.I)


def with_head_color(look: str) -> str:
    """Puts "white head and hands" after "stick figure" in a look that gives no head color, so the
    image model never chooses one itself (it otherwise drifts between white and light brown)."""
    m = _LEAD.match(look or "")
    if not m or re.search(r"\bheads? and hands\b", look, re.I):
        return look
    tone = "white heads and hands" if m.group(1).lower().endswith("s") else "white head and hands"
    return f"{m.group(1)}, {tone}, {look[m.end():]}"


_FACE = re.compile(r"\b(nose|noses|nostrils?|lips?|jowls?|jowly|chins?|cheeks?|cheekbones?|ears?|"
                   r"complexion|jaw|jawline|face shape|(?:round|long|thin|wide|narrow|square|oval) face)\b", re.I)


def without_face_features(look: str) -> str:
    """Drops any part of a look that describes the face itself (nose, lips, jowls...). Every face is drawn
    the same simple way: described features become caricatures, which can read as ethnic stereotypes, and
    they change from image to image. Hair, facial hair, eyebrows and glasses stay."""
    return ", ".join(p for p in re.split(r",\s*", look or "") if not _FACE.search(p))


def add_head_colors(characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cleans every look before it is saved: a fixed head color, and no facial features."""
    out = []
    for c in characters:
        c = {**c}
        if c.get("look"):
            c["look"] = with_head_color(without_face_features(c["look"]))
        if c.get("variants"):
            c["variants"] = [{**v, "look": with_head_color(without_face_features(v["look"]))}
                             for v in c["variants"]]
        out.append(c)
    return out


def changed_looks(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(old look, new look) for every character look or variant that differs between two guides,
    matched by name and `when`, longest first so a look that contains another is replaced whole."""
    pairs = []
    for o in old:
        n = _find(new, "name", o["name"])
        if not n:
            continue
        if o.get("look") and n.get("look") and o["look"] != n["look"]:
            pairs.append((o["look"], n["look"]))
        for ov in o.get("variants") or []:
            nv = _find(n.get("variants") or [], "when", ov["when"])
            if nv and ov.get("look") and nv.get("look") and ov["look"] != nv["look"]:
                pairs.append((ov["look"], nv["look"]))
    return sorted(pairs, key=lambda p: -len(p[0]))


def replace_looks(scene: str, pairs: list[tuple[str, str]]) -> str:
    """Scenes copy each look word for word, so a changed look can be swapped in place."""
    for old, new in pairs:  # a look that starts a sentence is capitalised ("Stick figures, ...")
        scene = re.sub(re.escape(old), lambda m: m.group(0)[0] + new[1:], scene, flags=re.I)
    return scene


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
abstract metaphor has an empty cast.
- Also list the RECURRING OBJECTS that are visible in each image (`objects`), using their names \
exactly as written, including ones the narration only implies (the hole while someone is pulled \
out of it, the ship while the crew stand on its deck). For an object described from several sides, \
set `view` to the side the image shows, exactly as written before its colon ("from above", "From \
the side", "inside"); otherwise leave `view` "".
- Set `place` to the RECURRING PLACE the image happens in, its name exactly as written, or "" when \
it is somewhere else or an abstract metaphor. Beats that continue the same moment stay in the same \
place."""

CAST_SCHEMA = obj({"beats": arr(obj({"idx": INT, "cast": arr(obj({"name": STR, "variant": STR})),
                                     "objects": arr(obj({"name": STR, "view": STR})), "place": STR}))})


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


_VIEW = re.compile(r"(?:^|(?<=[.;])\s+)([A-Za-z][A-Za-z' -]{1,25}):\s*")


def look_views(look: str) -> list[tuple[str, str]]:
    """(side, text) for an object described from several sides ("from above: ... From the side: ..."),
    or [("", look)] for one with a single look."""
    marks = list(_VIEW.finditer(look))
    if not marks or marks[0].start() > 0:
        return [("", look)]
    return [(m.group(1), look[m.end():marks[n + 1].start() if n + 1 < len(marks) else len(look)].strip())
            for n, m in enumerate(marks)]


def resolve_things(guide: dict[str, Any], things: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only objects and a place that are in the guide, with canonical names and a real side."""
    objects: list[dict[str, str]] = []
    for o in (things or {}).get("objects") or []:
        p = _find(guide.get("props") or [], "name", o.get("name", ""))
        if not p or any(x["name"] == p["name"] for x in objects):
            continue
        views = look_views(p["look"])
        v = _find([{"view": s} for s, _ in views], "view", o.get("view", "")) if views[0][0] else None
        objects.append({"name": p["name"], "view": (v or {"view": views[0][0]})["view"]})
    place = _find(guide.get("locations") or [], "name", (things or {}).get("place", ""))
    return {"objects": objects, "place": place["name"] if place else ""}


def thing_looks(guide: dict[str, Any], things: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(label, exact look text) for each recurring object and the place in an image."""
    t = resolve_things(guide, things)
    out = []
    for o in t["objects"]:
        views = dict(look_views(_find(guide["props"], "name", o["name"])["look"]))
        out.append((o["name"] + (f" ({o['view']})" if o["view"] else ""), views[o["view"]]))
    if t["place"]:
        out.append((t["place"], _find(guide["locations"], "name", t["place"])["look"]))
    return out


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def missing_looks(scene: str, looks: list[tuple[str, str]]) -> list[str]:
    """Names of characters whose look text is not in the scene word for word."""
    s = _norm(scene)
    return [name for name, look in looks if _norm(look) not in s]


def with_looks(scene: str, looks: list[tuple[str, str]], things: list[tuple[str, str]] = ()) -> str:
    """Last resort when Claude keeps leaving a look out: add it to the end of the scene."""
    for intro, items in (("Characters in this image", looks), ("Also in this image", things)):
        gone = [look for name, look in items if name in missing_looks(scene, items)]
        if gone:
            scene = f"{scene.rstrip('.')}. {intro}: {'; '.join(gone)}."
    return scene


def _cast_line(looks: list[tuple[str, str]], things: list[tuple[str, str]] | None = None) -> str:
    if not looks:
        line = "    in this image: none of the listed characters"
    else:
        line = "    in this image (copy each look, not the name): " + "; ".join(f"{name} = {look}" for name, look in looks)
    if things:
        line += ("\n    recurring objects and place (copy each look, not the name): "
                 + "; ".join(f"{name} = {look}" for name, look in things))
    return line


def _staged(c: list[dict[str, str]], t: dict[str, Any] | None) -> str:
    who = ", ".join(x["name"] + (f" ({x['variant']})" if x["variant"] else "") for x in c) or "none"
    if not t:
        return who
    what = ", ".join(o["name"] + (f" ({o['view']})" if o["view"] else "") for o in t["objects"]) or "none"
    return f"{who}; objects: {what}; place: {t['place'] or 'none'}"


def stage_beats(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
                group: int = 80, progress: Callable[[str, float], None] = lambda m, f: None,
                known: dict[int, list[dict[str, str]]] | None = None,
                known_things: dict[int, dict[str, Any]] | None = None,
                ) -> tuple[dict[int, list[dict[str, str]]], dict[int, dict[str, Any]]]:
    """Return ({beat idx: [{"name", "variant"}]}, {beat idx: {"objects": [{"name", "view"}], "place"}}):
    who is drawn in each image, and which recurring objects and place, decided from the whole story
    before any prompt is written. Groups go in story order and see the beats just before them, so a
    scene that runs across groups keeps its people, objects and place."""
    if not (guide["characters"] or guide.get("props") or guide.get("locations")):
        return {b["idx"]: [] for b in beats}, {b["idx"]: resolve_things(guide, None) for b in beats}
    chars = "\n".join(character_lines(c) for c in guide["characters"]) or "- (none)"
    objs = "\n".join(f"- {p['name']}: {p['look']}" for p in guide.get("props") or []) or "- (none)"
    places = "\n".join(f"- {p['name']}: {p['look']}" for p in guide.get("locations") or []) or "- (none)"
    system = cached(f"{CAST_SYSTEM}\n\nCHARACTERS\n{chars}\n\nRECURRING OBJECTS\n{objs}\n\nRECURRING PLACES\n{places}"
                    f"\n\nFULL SCRIPT (for context)\n{script}")
    out: dict[int, list[dict[str, str]]] = dict(known or {})
    things: dict[int, dict[str, Any]] = dict(known_things or {})
    groups = [beats[i:i + group] for i in range(0, len(beats), group)]
    for n, g in enumerate(groups, 1):
        prev = sorted(i for i in out if i < g[0]["idx"])[-6:]
        lines = []
        if prev:
            lines += ["Already cast (the images just before these):"] + [f"  {i}: {_staged(out[i], things.get(i))}"
                                                                         for i in prev]
        lines += ["BEATS TO CAST:"] + [f"{b['idx']}: {b['text']}" for b in g]
        want = {b["idx"] for b in g}
        done: set[int] = set()
        for _ in range(2):
            res = claude.json(system, [{"role": "user", "content": "\n".join(lines)}], CAST_SCHEMA, effort="medium")
            for b in res["beats"]:
                if b["idx"] in want:
                    out[b["idx"]] = resolve_cast(guide, b["cast"])
                    things[b["idx"]] = resolve_things(guide, b)
                    done.add(b["idx"])
            if want <= done:
                break
        progress(f"Cast group {n} of {len(groups)}", n / len(groups))
    return ({b["idx"]: out.get(b["idx"], []) for b in beats},
            {b["idx"]: things.get(b["idx"]) or resolve_things(guide, None) for b in beats})


def cast_beats(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
               group: int = 80, progress: Callable[[str, float], None] = lambda m, f: None,
               known: dict[int, list[dict[str, str]]] | None = None) -> dict[int, list[dict[str, str]]]:
    """Only who is drawn in each image (see stage_beats)."""
    return stage_beats(claude, script, guide, beats, group, progress, known)[0]


def _context_system(script: str, guide: dict[str, Any]) -> list[dict[str, Any]]:
    return cached(f"{SCENE_SYSTEM}\n\n{visual_bible(guide)}\n\nFULL SCRIPT (for context)\n{script}")


def _previous(written: dict[int, dict[str, str]], before_idx: int, n: int = CARRY_OVER) -> list[str]:
    prev = sorted(i for i in written if i < before_idx)[-n:]
    return [f"  {i}: {written[i]['scene']}" for i in prev]


def write_scenes(claude: Claude, script: str, guide: dict[str, Any], beats: list[dict[str, Any]],
                 group: int = 40, progress: Callable[[str, float], None] = lambda m, f: None,
                 written: dict[int, dict[str, str]] | None = None,
                 opening: set[int] | None = None,
                 cast: dict[int, list[dict[str, str]]] | None = None,
                 things: dict[int, dict[str, Any]] | None = None) -> dict[int, dict[str, str]]:
    """Return {beat idx: {"scene", "label"}}.

    Groups are written in story order, one after another: each request sees the last scenes
    already written (from earlier groups, or from `written`, the project's existing prompts), so the
    images carry on from each other instead of every group starting fresh. `opening` holds the beats
    of the first minute (also used for the Short), which get extra eye-catching images. `cast` (from
    cast_beats) says who is in each image; every scene must carry those characters' looks word for
    word, and is asked for again (then patched) if it leaves one out. `things` (from stage_beats)
    does the same for the recurring objects and place in each image."""
    opening = opening or set()
    looks = {b["idx"]: cast_looks(guide, (cast or {}).get(b["idx"])) for b in beats}
    stuff = {b["idx"]: thing_looks(guide, (things or {}).get(b["idx"])) for b in beats}
    need = {i: looks[i] + stuff[i] for i in looks}
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
            lines += [f"{b['idx']}: {b['text']}"] + ([_cast_line(looks[b["idx"]], stuff[b["idx"]])]
                                                     if cast is not None else [])
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
                fix = [f"  {i}: left out {', '.join(missing_looks(out[i]['scene'], need[i]))}" for i in todo if i in out]
                if fix:
                    ask += ("\nThese scenes did not describe everyone and everything listed for the image with "
                            "their exact look text; "
                            "rewrite them with each look copied word for word:\n" + "\n".join(fix))
            res = claude.json(system, [{"role": "user", "content": ask}], SCENES_SCHEMA, effort="medium")
            for s in res["scenes"]:
                if s["idx"] in want:
                    out[s["idx"]] = {"scene": s["scene"].strip(), "label": clean_label(s.get("label", ""))}
                    if not missing_looks(out[s["idx"]]["scene"], need[s["idx"]]):
                        good.add(s["idx"])
        for i in out:
            out[i]["scene"] = with_looks(out[i]["scene"], looks[i], stuff[i])
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
                   opening: bool = False, cast: list[dict[str, str]] | None = None,
                   things: dict[str, Any] | None = None) -> dict[str, str]:
    by_idx = {b["idx"]: b for b in beats}
    written = written or {}
    looks = cast_looks(guide, cast)
    stuff = thing_looks(guide, things)
    near = [by_idx[i] for i in range(idx - 2, idx + 3) if i in by_idx]
    ask = "\n".join(f"{'>> ' if b['idx'] == idx else '   '}{b['idx']}: {b['text']}" for b in near)
    ask = f"Write a fresh scene for beat {idx} only (marked >>).\n{ask}"
    if cast is not None:
        ask += "\n" + _cast_line(looks, stuff)
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
            return {"scene": with_looks(s["scene"].strip(), looks, stuff), "label": clean_label(s.get("label", ""))}
    raise ValueError("Claude did not return a scene for that beat")


def patch_scenes(claude: Claude, script: str, guide: dict[str, Any], rows: list[dict[str, Any]], group: int = 20,
                 progress: Callable[[str, float], None] = lambda m, f: None) -> dict[int, str]:
    """Fix written scenes that leave out a look, changing as little as possible. Each row has idx,
    scene, looks and things (as from cast_looks and thing_looks); returns {idx: fixed scene}."""
    out: dict[int, str] = {}
    system = _context_system(script, guide)
    groups = [rows[i:i + group] for i in range(0, len(rows), group)]
    for n, g in enumerate(groups, 1):
        todo = {r["idx"]: r for r in g}
        for _ in range(2):
            lines = ["Rewrite each scene below with as few changes as possible so that every look listed under it "
                     "appears in it word for word, replacing any vague or shortened mention of that character, object "
                     "or place. Keep everything else (action, framing, background, other details) the same, and keep "
                     "the label.", "BEATS TO ILLUSTRATE:"]
            for r in todo.values():
                gone = set(missing_looks(r["scene"], r["looks"] + r["things"]))
                lines += [f"{r['idx']}: {r['scene']}",
                          "    missing looks (copy each, not the name): "
                          + "; ".join(f"{name} = {look}" for name, look in r["looks"] + r["things"] if name in gone)]
            res = claude.json(system, [{"role": "user", "content": "\n".join(lines)}], SCENES_SCHEMA, effort="medium")
            for s in res["scenes"]:
                r = todo.get(s["idx"])
                if r and not missing_looks(s["scene"], r["looks"] + r["things"]):
                    out[r["idx"]] = s["scene"].strip()
                    del todo[r["idx"]]
            if not todo:
                break
        for r in todo.values():
            out[r["idx"]] = with_looks(r["scene"], r["looks"], r["things"])
        progress(f"Fixed group {n} of {len(groups)}", n / len(groups))
    return out


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


# --- character sheet (made in Flow before batch 1) ---------------------------

def main_characters(guide: dict[str, Any] | None, prompts: list[dict[str, Any]],
                    min_images: int = 8) -> list[dict[str, Any]]:
    """Characters (and their variants) drawn in at least `min_images` pictures, most frequent first.
    These get a reference image in Flow; characters seen only a few times keep just their description."""
    if not guide or min_images <= 0:
        return []
    counts: dict[tuple[str, str], int] = {}
    for p in prompts:
        for c in p.get("characters") or []:
            key = (c.get("name", ""), c.get("variant") or "")
            counts[key] = counts.get(key, 0) + 1
    out = []
    for (name, variant), n in counts.items():
        ch = _find(guide["characters"], "name", name)
        if not ch or n < min_images:
            continue
        v = _find(ch.get("variants") or [], "when", variant) if variant else None
        if variant and not v:
            continue
        out.append({"name": ch["name"], "variant": variant, "images": n,
                    "look": v["look"] if v else character_look(ch)})
    out.sort(key=lambda r: (-r["images"], r["name"], r["variant"]))
    for i, r in enumerate(out, 1):
        label = r["name"] + (f", {r['variant']}" if r["variant"] else "")
        r["title"] = f"C{i} - " + re.sub(r"[.\n]+", " ", label).strip()
    return out


def character_sheet_text(style_prefix: str, refs: list[dict[str, Any]]) -> str:
    """The text to paste into Flow before batch 1: one reference picture per main character."""
    if not refs:
        return ""
    head = (f"INSTRUCTIONS FOR THE CHARACTER SHEET (do not make an image for this paragraph). Before any batch, "
            f"generate {len(refs)} character reference images, one for each numbered prompt below, in order. Name "
            f"each image exactly with its prompt's number and title, the words before the first period, for example "
            f"\"{refs[0]['title']}\". These are the main characters of the video. In every later batch, whenever a "
            f"prompt describes one of them, use that character's reference image so they look exactly the same: "
            f"same hair, clothes, colors, build and face.")
    body = [f"{r['title']}. Character reference of one character only: {r['look'].rstrip('.')}. Full body, standing "
            f"straight and facing the viewer, arms relaxed at the sides, centered, on a plain light gray background "
            f"(for this reference image only, instead of a scene). {with_body_rule(style_prefix)}" for r in refs]
    foot = (f"REMINDER (do not make an image for this paragraph): name all {len(refs)} images exactly with their "
            f"prompt's number and title (e.g. \"{refs[0]['title']}\"), never with names of your own.")
    return "\n\n".join([head, *body, foot]) + "\n"


def batch_header(batch_no: int, n_batches: int, count: int, refs: list[dict[str, Any]] | None = None) -> str:
    """A note for the Flow agent at the top of each batch. The same agent makes every batch, so it
    is told to keep matching the images it has already made."""
    text = (f"INSTRUCTIONS FOR BATCH {batch_no} OF {n_batches} (do not make an image for this paragraph). "
            f"Generate {count} images, one for each numbered prompt below, in order, one image per prompt. "
            f"Name each image exactly with its prompt's number and title, the words before the first period, "
            f"for example \"1 - Victorian London street\"; never make up your own names, and keep that number "
            f"with its image. ")
    if batch_no > 1:
        text += "These images continue the same video as the earlier batches you made. "
    text += ("Keep every recurring character, object and place looking exactly the same in every image: "
             "the prompts repeat the same description for each one, so follow those descriptions closely and "
             "match how you drew them before. Keep the same art style throughout.")
    if refs:
        names = ", ".join(f"{r['title'].split(' - ', 1)[1]} ({r['title'].split(' - ', 1)[0]})" for r in refs)
        text += (f" Use the character reference images from the character sheet for these characters whenever a "
                 f"prompt describes them: {names}.")
    return text


def batch_texts(style_prefix: str, prompts: list[dict[str, Any]], batch_size: int = 24,
                refs: list[dict[str, Any]] | None = None) -> dict[int, str]:
    """{batch number: the text to paste into Flow}: the agent note, then one prompt per paragraph."""
    batches: dict[int, list[str]] = {}
    for p in prompts:
        batches.setdefault(p["batch_no"], []).append(prompt_text(style_prefix, p, batch_size))
    total = max(batches, default=0)
    return {n: "\n\n".join([batch_header(n, total, len(items), refs), *items, batch_footer(len(items))]) + "\n"
            for n, items in sorted(batches.items())}


def batch_footer(count: int) -> str:
    """Repeats the naming rule after the last prompt: Flow's agent sometimes names a whole batch itself."""
    return (f"REMINDER (do not make an image for this paragraph): name all {count} images exactly with their "
            f"prompt's number and title, the words before the first period (e.g. \"1 - Victorian London street\"), "
            f"never with names of your own.")


def write_batch_files(folder: Path, style_prefix: str, prompts: list[dict[str, Any]], batch_size: int = 24,
                      refs: list[dict[str, Any]] | None = None) -> list[str]:
    """Write characters.txt (when there are main characters) and batch_XX.txt files, ready to paste into Flow."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in [*folder.glob("batch_*.txt"), *folder.glob("characters.txt")]:
        old.unlink()
    names = []
    if refs:
        (folder / "characters.txt").write_text(character_sheet_text(style_prefix, refs), encoding="utf-8")
        names.append("characters.txt")
    for n, text in batch_texts(style_prefix, prompts, batch_size, refs).items():
        name = f"batch_{n:02d}.txt"
        (folder / name).write_text(text, encoding="utf-8")
        names.append(name)
    return names
