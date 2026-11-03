from pipeline import prompts


def test_numbered_prompt_text():
    row = {"idx": 30, "scene": "A foggy street with gas lamps.", "label": "Victorian London street"}
    text = prompts.prompt_text("STYLE", row, 24)
    assert text == "7 - Victorian London street. A foggy street with gas lamps. STYLE"


def test_fallback_label_and_cleaning():
    assert prompts.clean_label('"Vault door, opening!" 1') == "Vault door opening"
    # Flow keeps only the first 3 words of a title, so titles stop there and never end on "in", "the"...
    assert prompts.clean_label("Night raids in Tikrit") == "Night raids"
    assert prompts.image_title(14, "Most hunted man alive", "x") == "14 - Most hunted man"
    assert prompts.image_title(1, "", "The stick figure with the red scarf runs") == "1 - Red scarf runs"
    scene = "Medium shot of the stick figure with the plaid tartan scarf walking across snowy tundra"
    assert prompts.fallback_label(scene) == "Plaid tartan scarf"
    assert prompts.number_in_batch(0) == 1 and prompts.number_in_batch(23) == 24 and prompts.number_in_batch(24) == 1


def test_backgrounds_follow_the_scene_not_a_white_page():
    style = prompts.BASE_STYLE.format(palette="navy blue")
    assert "off-white paper background," not in style and "night scenes are dark" in style
    assert "Always sets the background" in prompts.SCENE_SYSTEM


def test_characters_have_full_looks_and_story_variants():
    guide = {"characters": [
        {"name": "Saddam", "look": "stick figure, stocky, thick black mustache, olive beret",
         "variants": [{"when": "in hiding, 2003", "look": "stick figure, stocky, long scruffy gray-black beard, no hat"}]},
        {"name": "Old", "marker": "a red scarf"},
    ], "props": [], "locations": [], "setting_notes": ""}
    bible = prompts.visual_bible(guide)
    assert "- Saddam: stick figure, stocky, thick black mustache, olive beret" in bible
    assert "    in hiding, 2003: stick figure, stocky, long scruffy gray-black beard, no hat" in bible
    assert "- Old: stick figure, white head and hands, with a red scarf" in bible
    assert "variants" in prompts.STYLE_SYSTEM and 'no "now with a beard"' in prompts.SCENE_SYSTEM


SADDAM = {"characters": [
    {"name": "Saddam Hussein", "look": "stick figure, stocky, thick black mustache, black beret",
     "variants": [{"when": "in hiding, December 2003", "look": "stick figure, stocky, long scruffy gray-black beard, no hat"}]},
    {"name": "American soldiers", "look": "stick figure, sandy khaki helmet, black rifle", "variants": []},
], "props": [], "locations": [], "setting_notes": ""}


def test_cast_is_matched_to_the_guide_and_its_variants():
    cast = prompts.resolve_cast(SADDAM, [{"name": "saddam", "variant": "In hiding, December 2003"},
                                         {"name": "Saddam Hussein", "variant": ""},  # duplicate, dropped
                                         {"name": "A random farmer", "variant": ""},  # not in the guide
                                         {"name": "American soldiers", "variant": "made up"}])
    assert cast == [{"name": "Saddam Hussein", "variant": "in hiding, December 2003"},
                    {"name": "American soldiers", "variant": ""}]
    looks = prompts.cast_looks(SADDAM, cast)
    assert looks[0] == ("Saddam Hussein", "stick figure, stocky, long scruffy gray-black beard, no hat")


class CastFake:
    """Casts Saddam (in hiding) into every beat; the first scenes leave his look out ("a dusty figure")."""

    def __init__(self, fix_on_retry=True):
        self.fix_on_retry = fix_on_retry
        self.asks: list[str] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        ask = messages[-1]["content"]
        self.asks.append(ask)
        if "beats" in schema["properties"]:
            idxs = [int(l.split(":")[0]) for l in ask.split("BEATS TO CAST:")[1].strip().splitlines()]
            return {"beats": [{"idx": i, "cast": [{"name": "Saddam Hussein", "variant": "in hiding, December 2003"}]}
                              for i in idxs]}
        retry = len([a for a in self.asks if "BEATS TO ILLUSTRATE" in a]) > 1
        look = "stick figure, stocky, long scruffy gray-black beard, no hat"
        text = f"Soldiers stare down at {look}." if retry and self.fix_on_retry else "Soldiers stare down at a dusty figure."
        return {"scenes": [{"idx": 0, "label": "Dusty figure", "scene": text}]}


def test_scene_that_leaves_out_a_characters_look_is_rewritten():
    fake = CastFake()
    beats = [{"idx": 0, "text": "According to soldiers who were there,"}]
    cast = prompts.cast_beats(fake, "script", SADDAM, beats)
    out = prompts.write_scenes(fake, "script", SADDAM, beats, cast=cast)
    assert "in this image (copy each look, not the name): Saddam Hussein = stick figure, stocky, long scruffy gray-black beard, no hat" in fake.asks[1]
    assert "left out Saddam Hussein" in fake.asks[2]
    assert out[0]["scene"] == "Soldiers stare down at stick figure, stocky, long scruffy gray-black beard, no hat."


def test_look_is_added_when_claude_keeps_leaving_it_out():
    fake = CastFake(fix_on_retry=False)
    beats = [{"idx": 0, "text": "According to soldiers who were there,"}]
    out = prompts.write_scenes(fake, "script", SADDAM, beats, cast=prompts.cast_beats(fake, "script", SADDAM, beats))
    assert out[0]["scene"] == ("Soldiers stare down at a dusty figure. Characters in this image: "
                               "stick figure, stocky, long scruffy gray-black beard, no hat.")


def test_old_style_guides_get_the_arms_and_hands_rule():
    old = "round white heads, thin black stick limbs, flat colors"
    text = prompts.full_prompt(old, "a man waves")
    assert prompts.BODY in text and prompts.OLD_LIMBS not in text
    assert prompts.with_body_rule(prompts.with_body_rule(old)) == prompts.with_body_rule(old)
    assert prompts.BODY in prompts.BASE_STYLE


def test_every_look_gets_a_head_color_and_prompts_follow():
    assert prompts.with_head_color("stick figure, stocky, black beard") == \
        "stick figure, white head and hands, stocky, black beard"
    assert prompts.with_head_color("stick figures, medium build") == "stick figures, white heads and hands, medium build"
    assert prompts.with_head_color("stick figure with a red scarf") == "stick figure, white head and hands, with a red scarf"
    kept = "stick figure, medium brown head and hands, a red scarf"
    assert prompts.with_head_color(kept) == kept
    old = [{"name": "Guard", "look": "stick figure, burly, a checkered head scarf",
            "variants": [{"when": "captured", "look": "stick figure, burly, no head scarf, wrists bound"}]}]
    new = prompts.add_head_colors(old)
    assert prompts.add_head_colors(new) == new
    pairs = prompts.changed_looks(old, new)
    scene = "At night stick figure, burly, no head scarf, wrists bound sits. Stick figure, burly, a checkered head scarf stands."
    out = prompts.replace_looks(scene, pairs)
    assert out.count("white head and hands") == 2 and "Stick figure, white head and hands, burly, a checkered" in out
