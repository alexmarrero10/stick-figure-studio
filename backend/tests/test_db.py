"""The SQLite database: script versions, staleness and migrations."""
from pipeline import prompts


def test_db_versions_and_staleness(temp_db):
    db = temp_db
    p = db.create_project("The Great Heist")
    assert p["slug"] == "the-great-heist"
    assert db.create_project("The Great Heist")["slug"] == "the-great-heist-2"
    v1 = db.save_script(p["id"], "one two three", "generated")
    db.replace_beats(p["id"], v1["id"], [{"idx": 0, "word_start": 0, "word_end": 2, "text": "one two three"}])
    db.save_voiceover(p["id"], v1["id"], "x.wav", 1.0,
                      [{"idx": i, "text": t, "start": i * 0.3, "end": i * 0.3 + 0.2} for i, t in enumerate(["one", "two", "three"])], [])
    st = db.project_status(p["id"])
    assert not st["beats_stale"] and not st["voice_stale"]
    db.save_script(p["id"], "one two three four", "manual")
    st = db.project_status(p["id"])
    assert st["beats_stale"] and st["voice_stale"]
    assert [v["source"] for v in db.list_script_versions(p["id"])] == ["manual", "generated"]
    beat = db.list_beats(p["id"])[0]
    db.upsert_prompts(p["id"], [{"beat_id": beat["id"], "batch_no": 1, "scene": "a scene"}])
    assert db.list_prompts(p["id"])[0]["scene"] == "a scene"
    db.replace_beats(p["id"], v1["id"], [])
    assert db.list_prompts(p["id"]) == []  # prompts cascade with beats


def test_migration_brings_old_saved_data_up_to_date(temp_db):
    db = temp_db
    pid = db.create_project("Old Project")["id"]
    keep = {"name": "New", "look": "stick figure, white head and hands, red cap"}
    db.save_style_guide(pid, "round white heads, thin black stick limbs, flat colors", [{"name": "Old", "marker": "a red scarf"}, keep])
    db.save_publish_meta(pid, {"titles": ["T"], "thumbnail_prompts": ["a", "b", "c"]})
    with db.tx() as conn:  # run 012 again over the old-format rows
        conn.execute("CREATE TABLE social_posts (id INTEGER PRIMARY KEY)")
        conn.execute("DELETE FROM schema_migrations WHERE name = '012_tidy_old_data.sql'")
    db.migrate()
    guide = db.get_style_guide(pid)
    assert guide["style_prefix"] == f"round white heads, {prompts.BODY}, flat colors"
    assert guide["characters"][0]["look"] == "stick figure, white head and hands, with a red scarf"
    assert guide["characters"][1] == keep
    assert db.get_publish_meta(pid) == {"titles": ["T"]}
    with db.tx() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'social_posts'").fetchone()
