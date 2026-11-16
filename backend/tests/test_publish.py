"""Publishing pack: title, description, tags and thumbnails."""
from pathlib import Path

from pipeline import prompts, publish
from tests.helpers import project_with_beats


class ThumbFake:
    def __init__(self):
        self.asks: list[str] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        self.asks.append(messages[-1]["content"])
        if "tags" in schema["properties"]:
            return {"title": "The Hole", "description": "Hook.", "tags": [], "chapters": []}
        if "idea" in schema["properties"]:
            return {"idea": f"Idea {len(self.asks)}", "scene": "A huge flashlight beam", "background": "night"}
        return {"scene": "A stick figure peeks out of a hole, a flashlight on his face", "background": "dark navy night"}


def test_thumbnail_from_your_idea_or_one_suggestion(client, temp_db, monkeypatch):
    pid = project_with_beats(temp_db, 3)
    temp_db.save_style_guide(pid, "Stick figure style, flat colors.", [])
    fake = ThumbFake()
    monkeypatch.setattr("app.routes.assemble.claude", lambda: fake)
    assert client.post(f"/api/projects/{pid}/publish/thumbnails", json={"request": " "}).status_code == 400
    # Works before the publishing pack exists.
    meta = client.post(f"/api/projects/{pid}/publish/thumbnails", json={"request": "Him peeking out of the hole"}).json()
    [custom] = meta["custom_thumbnails"]
    assert custom["request"] == "Him peeking out of the hole"
    assert custom["prompt"].startswith("A stick figure peeks out of a hole, a flashlight on his face. Background: dark navy night.")
    assert custom["prompt"].endswith("Stick figure style, flat colors.")
    assert "THE CREATOR'S IDEA FOR THE THUMBNAIL\nHim peeking out of the hole" in fake.asks[-1]
    # Give suggestion adds exactly one, and the next one is told to differ from what's listed.
    meta = client.post(f"/api/projects/{pid}/publish/thumbnails/suggest").json()
    assert len(meta["custom_thumbnails"]) == 2 and meta["custom_thumbnails"][1]["suggested"]
    assert meta["custom_thumbnails"][1]["prompt"].startswith("A huge flashlight beam. Background: night.")
    client.post(f"/api/projects/{pid}/publish/thumbnails/suggest")
    assert "ALREADY TRIED" in fake.asks[-1] and "- Him peeking out of the hole" in fake.asks[-1]
    # Generating the pack keeps the thumbnails; removing one drops it.
    assert len(client.post(f"/api/projects/{pid}/publish").json()["custom_thumbnails"]) == 3
    assert len(client.delete(f"/api/projects/{pid}/publish/thumbnails/0").json()["custom_thumbnails"]) == 2


def test_general_tags_are_added_without_repeats():
    tags = publish.merge_tags(["Franklin expedition", "History", "arctic"], ["animation", "history", "education"])
    assert tags == ["Franklin expedition", "History", "arctic", "animation", "education"]


def test_tags_stay_under_youtubes_limit():
    tags = publish.merge_tags([f"tag number {i}" for i in range(100)], ["animation"])
    assert sum(len(t) + 1 + (2 if " " in t else 0) for t in tags) <= 500
    assert "animation" not in tags or len(tags) < 100


def test_config_has_general_tags():
    from app.config import load_config
    assert {"animation", "history", "education"} <= set(load_config()["publish"]["general_tags"])


def test_publish_description_keeps_the_research_sources():
    class C:
        def json(self, *a, **k):
            return {"title": "One Title", "description": "Hook.", "tags": ["navy"], "chapters": [{"beat": 0, "title": "Start"}]}
    beats = [{"idx": 0, "word_start": 0, "text": "w"}]
    meta_ = publish.generate(C(), "T", "w", beats, [], [{"title": "Navy report", "url": "https://navy.mil/r"}],
                             ["animation", "history", "education"])
    assert "Sources\n- Navy report: https://navy.mil/r" in meta_["description"]
    assert meta_["tags"] == ["navy", "animation", "history", "education"]
    assert meta_["titles"] == ["One Title"]  # one suggested title, not five options
    assert "thumbnail_prompts" not in meta_  # thumbnails come one at a time from the Thumbnail panel
    assert "thumbnails" not in publish.SYSTEM


def test_thumbnail_prompt_uses_the_videos_style():
    thumb = publish.thumbnail_prompt("A shocked stick figure holds a huge silver fork", "deep navy blue")
    assert thumb.startswith("A shocked stick figure holds a huge silver fork. Background: deep navy blue. YouTube thumbnail")
    assert prompts.BODY in thumb  # no style guide yet: the default video style
    style = "Minimalist stick figure illustration, flat colors (sand beige)."
    assert publish.thumbnail_prompt("A", "B", style).endswith(style)


def test_publish_prompts_and_page_hold_no_other_videos_examples():
    page = (Path(__file__).parents[2] / "frontend/src/steps/Publish.tsx").read_text(encoding="utf-8")
    for name in ("Saddam", "Franklin", "Nixon", "Watergate"):
        assert name not in publish.SYSTEM and name not in publish.THUMB_SUGGEST_SYSTEM
        assert name not in publish.THUMB_ASK_SYSTEM and name not in page


def test_suggested_titles_are_short_and_never_give_the_answer():
    assert "under 55 characters" in publish.TITLE_RULES
    assert "NEVER contains the answer" in publish.TITLE_RULES
    assert "Why Hasn't Anyone" in publish.TITLE_RULES  # shapes distilled from the top channels
    assert publish.TITLE_RULES in publish.SYSTEM


def test_thumbnails_show_the_mystery_not_the_answer():
    for system in (publish.THUMB_ASK_SYSTEM, publish.THUMB_SUGGEST_SYSTEM):
        assert "Show the mystery, never the answer" in system
