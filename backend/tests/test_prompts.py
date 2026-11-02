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
