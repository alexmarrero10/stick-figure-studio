"""Image prompts: the style guide, cast, scenes, titles, character looks and the prompt routes."""
import time

from pipeline import prompts
from tests.helpers import ROOT, FakeClaude, project_with_beats, wait_job


class PlaceFake(FakeClaude):
    """Like FakeClaude, but the staging step also puts every image on the tundra."""

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        res = super().json(system, messages, schema, max_tokens, effort)
        for b in res.get("beats", []):
            b["place"] = "tundra"
        return res


SADDAM = {"characters": [
    {"name": "Saddam Hussein", "look": "stick figure, stocky, thick black mustache, black beret",
     "variants": [{"when": "in hiding, December 2003", "look": "stick figure, stocky, long scruffy gray-black beard, no hat"}]},
    {"name": "American soldiers", "look": "stick figure, sandy khaki helmet, black rifle", "variants": []},
], "props": [], "locations": [], "setting_notes": ""}


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


HOLE = ("from above: a square dark opening in brown dirt, a white slab lid beside it. "
        "From the side: a narrow shaft two stick figures deep, one small yellow bulb")


STAGED = {**SADDAM, "props": [{"name": "the spider hole", "look": HOLE}, {"name": "the rope", "look": "a coiled tan rope"}],
          "locations": [{"name": "orange grove", "look": "rows of dark green orange trees at night"}]}


class StageFake:
    def __init__(self, fix_on_retry=True):
        self.fix_on_retry = fix_on_retry
        self.asks: list[str] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        ask = messages[-1]["content"]
        self.asks.append(ask)
        if "beats" in schema["properties"]:
            return {"beats": [{"idx": 0, "cast": [], "objects": [{"name": "the rope", "view": ""}],
                               "place": "orange grove"}]}
        retry = len(self.asks) > 2
        text = ("Soldiers lift a coiled tan rope among rows of dark green orange trees at night."
                if retry and self.fix_on_retry else "Soldiers lift the rope in the grove.")
        return {"scenes": [{"idx": 0, "label": "Rope", "scene": text}]}


def test_batch_checkmarks(client, temp_db):
    pid = project_with_beats(temp_db, 30)
    assert client.put(f"/api/projects/{pid}/prompts/batch/2/done", json={"done": True}).json() == {"done_batches": [2]}
    client.put(f"/api/projects/{pid}/prompts/batch/1/done", json={"done": True})
    client.put(f"/api/projects/{pid}/prompts/batch/2/done", json={"done": False})
    assert client.get(f"/api/projects/{pid}/prompts").json()["done_batches"] == [1]


def test_scenes_are_written_in_order_with_previous_scenes():
    fake = FakeClaude()
    guide = {"characters": [{"name": "F", "look": "stick figure with a scarf"}],
             "props": [{"name": "Erebus", "look": "a black-hulled ship"}], "locations": [], "setting_notes": ""}
    beats = [{"idx": i, "text": f"w{i}."} for i in range(100)]
    out = prompts.write_scenes(fake, "script", guide, beats, group=40)
    assert sorted(out) == list(range(100))
    asks = [a for _, a in fake.calls]
    assert len(asks) == 3
    assert "already written" not in asks[0]
    # The second request sees the last scenes of the first group, so the images carry on.
    assert "Scenes already written" in asks[1] and "  39: Beat 39" in asks[1] and "  31: Beat 31" not in asks[1]
    assert "  79: Beat 79" in asks[2]
    # The visual bible tells Claude to reuse the fixed look word for word.
    assert "RECURRING OBJECTS (use the look text word for word)\n- Erebus: a black-hulled ship" in fake.calls[0][0]


def test_generate_route_stores_props_and_batch_text(client, temp_db, monkeypatch):
    pid = project_with_beats(temp_db, 30)
    fake = FakeClaude()
    monkeypatch.setattr("app.routes.prompts.claude", lambda: fake)
    job = client.post(f"/api/projects/{pid}/prompts/generate", json={}).json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    data = client.get(f"/api/projects/{pid}/prompts").json()
    assert data["style"]["props"][0]["name"] == "Erebus"
    assert data["style"]["locations"][0]["name"] == "Tundra"
    assert len(data["prompts"]) == 30
    # Who is in each image was decided first, saved with the prompt, and their look is in the scene.
    assert fake.calls[1][1].startswith("BEATS TO CAST:")
    assert all(p["characters"] == [{"name": "Franklin", "variant": ""}] for p in data["prompts"])
    assert "in this image (copy each look, not the name): Franklin = stick figure, white head and hands, with a plaid tartan scarf" in fake.calls[2][1]
    assert all("stick figure, white head and hands, with a plaid tartan scarf" in p["scene"] for p in data["prompts"])
    text2 = data["batch_texts"]["2"]
    assert text2.startswith("INSTRUCTIONS FOR BATCH 2 OF 2")
    assert "continue the same video" in text2
    assert "\n\nScene. Beat 24: a three-masted ship" in text2  # titles have no numbers
    assert text2.count("\n\n") == 7  # header + 6 prompts + naming reminder
    assert text2.rstrip().endswith("never with names or numbers of your own.")


def test_check_looks_adds_missing_places_and_skips_hand_edited_prompts(client, temp_db, monkeypatch):
    pid = project_with_beats(temp_db, 30)
    monkeypatch.setattr("app.routes.prompts.claude", lambda: FakeClaude())
    wait_job(client.post(f"/api/projects/{pid}/prompts/generate", json={}).json(), "done")
    first = client.get(f"/api/projects/{pid}/prompts").json()["prompts"][0]
    client.put(f"/api/projects/{pid}/prompts/{first['beat_id']}", json={"scene": "My own scene."})
    monkeypatch.setattr("app.routes.prompts.claude", lambda: PlaceFake())
    job = wait_job(client.post(f"/api/projects/{pid}/prompts/check-looks").json(), "done")
    assert job["result"]["fixed"] == 29 and job["result"]["skipped_edited"] == 1 and job["result"]["batches"] == [1, 2]
    rows = client.get(f"/api/projects/{pid}/prompts").json()["prompts"]
    assert rows[0]["scene"] == "My own scene."
    assert all(r["things"] == {"objects": [], "place": "Tundra"} for r in rows)
    assert all("flat white snowy tundra under a pale gray sky" in r["scene"] for r in rows[1:])
    assert all(r["characters"] == [{"name": "Franklin", "variant": ""}] for r in rows)


def test_prompt_rules_forbid_text_bubbles_and_camera_moves():
    assert "no look may contain writing" in prompts.STYLE_SYSTEM
    assert "speech bubbles" in prompts.SCENE_SYSTEM and "never camera movement" in prompts.SCENE_SYSTEM


def test_prompt_text_starts_with_its_title_and_no_number():
    row = {"idx": 30, "scene": "A foggy street with gas lamps.", "label": "Victorian London street"}
    text = prompts.prompt_text("STYLE", row, 24)
    assert text == "Victorian London street. A foggy street with gas lamps. STYLE"


def test_titles_are_unique_in_each_batch_and_never_hold_digits():
    rows = [{"idx": 0, "label": "Oval Office", "scene": "A wide view of a desk by tall windows."},
            {"idx": 1, "label": "Oval Office", "scene": "A close-up of a telephone on the desk."},
            {"idx": 2, "label": "Oval Office", "scene": "A close-up of a telephone on the desk."},
            {"idx": 24, "label": "Oval Office", "scene": "Rain on the windows."},
            {"idx": 3, "label": "1972 election night", "scene": "Balloons fall."}]
    t = prompts.batch_titles(rows, 24)
    assert t[0] == "Oval Office" and t[1] == "Oval Office telephone" and t[2] not in (t[0], t[1])
    assert t[24] == "Oval Office"  # another batch may reuse it
    assert t[3] == "election night"


def test_fallback_label_and_cleaning():
    assert prompts.clean_label('"Vault door, opening!" 1') == "Vault door opening"
    # Flow keeps only the first 3 words of a title, so titles stop there and never end on "in", "the"...
    assert prompts.clean_label("Night raids in Tikrit") == "Night raids"
    assert prompts.image_title("Most hunted man alive", "x") == "Most hunted man"
    assert prompts.image_title("", "The stick figure with the red scarf runs") == "Red scarf runs"
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
    ], "props": [], "locations": [], "setting_notes": ""}
    bible = prompts.visual_bible(guide)
    assert "- Saddam: stick figure, stocky, thick black mustache, olive beret" in bible
    assert "    in hiding, 2003: stick figure, stocky, long scruffy gray-black beard, no hat" in bible
    assert "variants" in prompts.STYLE_SYSTEM and 'no "now with a beard"' in prompts.SCENE_SYSTEM


def test_cast_is_matched_to_the_guide_and_its_variants():
    cast = prompts.resolve_cast(SADDAM, [{"name": "saddam", "variant": "In hiding, December 2003"},
                                         {"name": "Saddam Hussein", "variant": ""},  # duplicate, dropped
                                         {"name": "A random farmer", "variant": ""},  # not in the guide
                                         {"name": "American soldiers", "variant": "made up"}])
    assert cast == [{"name": "Saddam Hussein", "variant": "in hiding, December 2003"},
                    {"name": "American soldiers", "variant": ""}]
    looks = prompts.cast_looks(SADDAM, cast)
    assert looks[0] == ("Saddam Hussein", "stick figure, stocky, long scruffy gray-black beard, no hat")


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


def test_the_style_has_the_arms_and_hands_rule():
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


def test_objects_seen_from_several_sides_are_split_into_views():
    assert prompts.look_views(HOLE) == [
        ("from above", "a square dark opening in brown dirt, a white slab lid beside it."),
        ("From the side", "a narrow shaft two stick figures deep, one small yellow bulb")]
    assert prompts.look_views("a coiled tan rope") == [("", "a coiled tan rope")]
    t = prompts.resolve_things(STAGED, {"objects": [{"name": "Spider hole", "view": "from the side"},
                                                    {"name": "a unicorn", "view": ""}], "place": "Orange Grove"})
    assert t == {"objects": [{"name": "the spider hole", "view": "From the side"}], "place": "orange grove"}
    assert prompts.thing_looks(STAGED, t) == [
        ("the spider hole (From the side)", "a narrow shaft two stick figures deep, one small yellow bulb"),
        ("orange grove", "rows of dark green orange trees at night")]


def test_scene_that_leaves_out_an_object_or_place_is_rewritten_then_patched():
    beats = [{"idx": 0, "text": "They pulled him out."}]
    fake = StageFake()
    cast, things = prompts.stage_beats(fake, "script", STAGED, beats)
    assert things[0] == {"objects": [{"name": "the rope", "view": ""}], "place": "orange grove"}
    out = prompts.write_scenes(fake, "script", STAGED, beats, cast=cast, things=things)
    assert "recurring objects and place (copy each look, not the name): the rope = a coiled tan rope" in fake.asks[1]
    assert "left out the rope, orange grove" in fake.asks[2]
    assert out[0]["scene"].startswith("Soldiers lift a coiled tan rope")
    fake = StageFake(fix_on_retry=False)
    out = prompts.write_scenes(fake, "script", STAGED, beats, cast=cast, things=things)
    assert out[0]["scene"] == ("Soldiers lift the rope in the grove. Also in this image: a coiled tan rope; "
                               "rows of dark green orange trees at night.")


def test_patch_scenes_keeps_the_fix_only_when_every_look_is_there():
    fake = StageFake()
    fake.asks = ["", "", ""]  # make the fake answer with the fixed scene
    row = {"idx": 0, "scene": "Soldiers lift the rope in the grove.", "looks": [],
           "things": prompts.thing_looks(STAGED, {"objects": [{"name": "the rope", "view": ""}], "place": "orange grove"})}
    out = prompts.patch_scenes(fake, "script", STAGED, [row])
    assert out == {0: "Soldiers lift a coiled tan rope among rows of dark green orange trees at night."}
    assert "missing looks (copy each, not the name): the rope = a coiled tan rope" in fake.asks[-1]


def test_looks_never_describe_facial_features():
    nixon = ("stick figure, white head and hands, medium height, dark brown wavy hair combed straight back, "
             "heavy dark eyebrows, prominent rounded nose, big jowls, no hat, long-sleeved dark navy suit")
    out = prompts.add_head_colors([{"name": "Nixon", "look": nixon,
                                    "variants": [{"when": "1974", "look": nixon + ", thin lips"}]}])[0]
    for look in (out["look"], out["variants"][0]["look"]):
        assert "nose" not in look and "jowls" not in look and "lips" not in look
        assert "dark brown wavy hair combed straight back" in look and "heavy dark eyebrows" in look
    # Words that only contain a feature word are kept.
    kept = "stick figure, white head and hands, gray earmuffs, years older, a clipboard"
    assert prompts.without_face_features(kept) == kept
    # Every face is drawn the same way, with no nose, and the rules tell Claude to pin hair down.
    assert "no nose" in prompts.BASE_STYLE and "flat solid-color" in prompts.BASE_STYLE
    assert "Never describe \\na nose" not in prompts.STYLE_SYSTEM and "Never describe a nose" in prompts.STYLE_SYSTEM
    assert "one exact color" in prompts.STYLE_SYSTEM


def test_main_characters_get_a_character_sheet_used_by_every_batch():
    guide = {"characters": [
        {"name": "Richard Nixon", "look": "stick figure, white head and hands, short dark brown wavy hair", "variants": []},
        {"name": "Frank Wills", "look": "stick figure, white head and hands, navy guard cap",
         "variants": [{"when": "1990s", "look": "stick figure, white head and hands, gray knit cap"}]},
        {"name": "Special prosecutor", "look": "stick figure, white head and hands, bow tie", "variants": []}]}
    rows = ([{"characters": [{"name": "Richard Nixon", "variant": ""}]}] * 10
            + [{"characters": [{"name": "Frank Wills", "variant": ""}]}] * 9
            + [{"characters": [{"name": "Frank Wills", "variant": "1990s"}]}] * 8
            + [{"characters": [{"name": "Special prosecutor", "variant": ""}]}] * 3)
    refs = prompts.main_characters(guide, rows, min_images=8)
    assert [r["title"] for r in refs] == ["Richard Nixon", "Frank Wills", "Frank Wills alternate look"]
    assert refs[2]["look"].endswith("gray knit cap")  # a variant gets its own reference
    assert prompts.main_characters(guide, rows, min_images=0) == []

    sheet = prompts.character_sheet_text("STYLE", refs)
    assert sheet.startswith("INSTRUCTIONS FOR THE CHARACTER SHEET") and "generate 3 character reference" in sheet
    assert "\n\nRichard Nixon. Character reference of one character only: stick figure" in sheet
    assert "plain light gray background" in sheet and "STYLE" in sheet
    assert prompts.character_sheet_text("STYLE", []) == ""

    batch = [{"batch_no": 1, "idx": 0, "scene": "Nixon at his desk", "label": "Desk"}]
    text = prompts.batch_texts("STYLE", batch, 24, refs)[1]
    assert "Use the character reference images" in text and "them: Richard Nixon, Frank Wills" in text
    assert "character reference" not in prompts.batch_texts("STYLE", batch, 24)[1]


def test_style_rules_ask_for_variety_between_similar_characters_and_inside_groups():
    s = prompts.STYLE_SYSTEM
    assert "no two characters share the same main clothing color" in s
    assert "at least three things" in s and "never one look copied for every member" in s
    assert "may wear exactly the same clothes" in s and "Never vary noses" in s


def test_regenerating_all_prompts_keeps_batch_checkmarks(client, temp_db, monkeypatch):
    pid = project_with_beats(temp_db, 30)
    monkeypatch.setattr("app.routes.prompts.claude", lambda: FakeClaude())
    wait_job(client.post(f"/api/projects/{pid}/prompts/generate", json={}).json(), "done")
    client.put(f"/api/projects/{pid}/prompts/batch/1/done", json={"done": True})
    wait_job(client.post(f"/api/projects/{pid}/prompts/generate", json={"only_missing": False}).json(), "done")
    assert client.get(f"/api/projects/{pid}/prompts").json()["done_batches"] == [1]
    page = (ROOT / "frontend" / "src" / "steps" / "Images.tsx").read_text(encoding="utf-8")
    assert "batch checkmarks are cleared" not in page
