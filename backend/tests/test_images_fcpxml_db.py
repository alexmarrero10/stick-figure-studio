import os
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from pipeline import captions, fcpxml, images


def make_png(path: Path, created: str | None = None, mtime: float | None = None):
    im = Image.new("RGB", (160, 90), "white")
    if created:
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo()
        info.add_text("Creation Time", created)
        im.save(path, pnginfo=info)
    else:
        im.save(path)
    if mtime:
        os.utime(path, (mtime, mtime))


def test_order_by_embedded_time_beats_mtime(tmp_path):
    make_png(tmp_path / "zzz.png", created="2026:01:01 10:00:00", mtime=3000)
    make_png(tmp_path / "aaa.png", created="2026:01:01 10:00:05", mtime=1000)
    out = images.order_images(tmp_path)
    assert [x["name"] for x in out] == ["zzz.png", "aaa.png"]
    assert {x["sort_source"] for x in out} == {"metadata"}


def test_order_by_mtime_then_name(tmp_path):
    make_png(tmp_path / "b.png", mtime=2000)
    make_png(tmp_path / "a.png", mtime=3000)
    make_png(tmp_path / "c.png", mtime=1000)
    assert [x["name"] for x in images.order_images(tmp_path)] == ["c.png", "b.png", "a.png"]


def test_filename_fallback_uses_natural_order(tmp_path):
    for n in ("img10.png", "img2.png", "img1.png"):
        make_png(tmp_path / n, mtime=5000)
    out = images.order_images(tmp_path)
    assert [x["name"] for x in out] == ["img1.png", "img2.png", "img10.png"]
    assert out[0]["sort_source"] == "filename"


def test_fcpxml_structure(tmp_path):
    img = tmp_path / "a.png"
    make_png(img)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"")
    shots = [
        {"image": str(img), "start_frame": 0, "end_frame": 45, "scale": 1.0, "beat_ids": [0]},
        {"image": str(img), "start_frame": 45, "end_frame": 120, "scale": 1.15, "beat_ids": [1]},
    ]
    xml = fcpxml.build(shots, audio, 3.9, "Test")
    root = ET.fromstring(xml.split("\n", 2)[2])
    spine = root.find(".//spine")
    clips = list(spine)
    assert [c.get("offset") for c in clips] == ["0s", "45/30s"]
    assert [c.get("duration") for c in clips] == ["45/30s", "75/30s"]
    assert clips[1].find("adjust-transform").get("scale") == "1.15 1.15"
    assert clips[0].find("asset-clip").get("lane") == "-1"
    assert root.find(".//sequence").get("duration") == "120/30s"
    assert root.find(".//media-rep").get("src").startswith("file:///")


def test_srt_cues():
    words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, t in enumerate("Picture this. A vault door, wide open.".split())]
    srt = captions.build_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert "Picture this." in srt


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


def test_label_number_parsing():
    assert images.label_number("7 - Victorian London street.png") == 7
    assert images.label_number("07_Victorian_London_street (1).png") == 7
    assert images.label_number("12. Vault door.jpg") == 12
    assert images.label_number("20260101_123000.png") is None
    assert images.label_number("image_3.png") is None
    assert images.label_number("0 - nothing.png") is None


def test_numbered_images_go_to_their_slot(tmp_path):
    # Created out of order, and number 2 is missing: slots follow the numbers, not the times.
    make_png(tmp_path / "3 - Vault.png", mtime=1000)
    make_png(tmp_path / "1 - Street.png", mtime=3000)
    make_png(tmp_path / "4 - Escape.png", mtime=2000)
    placed, warnings = images.assign_positions(images.order_images(tmp_path), 4)
    assert [(x["name"], x["position"]) for x in placed] == [("1 - Street.png", 0), ("3 - Vault.png", 2), ("4 - Escape.png", 3)]
    assert {x["sort_source"] for x in placed} == {"label"}
    assert warnings == []


def test_duplicate_and_unnumbered_images(tmp_path):
    make_png(tmp_path / "1 - Street.png", mtime=1000)
    make_png(tmp_path / "1 - Street (1).png", mtime=2000)  # newer redo of 1
    make_png(tmp_path / "loose.png", mtime=500)
    placed, warnings = images.assign_positions(images.order_images(tmp_path), 3)
    pos = {x["name"]: x["position"] for x in placed}
    assert pos["1 - Street (1).png"] == 0
    assert pos["loose.png"] == 1  # unnumbered fills the first free slot
    assert pos["1 - Street.png"] == 3  # the older duplicate becomes an extra
    assert len(warnings) == 1


def test_extract_zip_flattens_and_skips_junk(tmp_path):
    import io, zipfile
    src = tmp_path / "src.png"
    make_png(src)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(src, "Flow export/1 - Street.png")
        z.write(src, "other/1 - Street.png")
        z.write(src, "__MACOSX/Flow export/._1 - Street.png")
        z.writestr("notes.txt", "hi")
    out = tmp_path / "batch"
    out.mkdir()
    saved = images.extract_zip(buf.getvalue(), out)
    assert saved == ["1 - Street.png", "1 - Street (1).png"]
    assert sorted(p.name for p in out.iterdir()) == ["1 - Street (1).png", "1 - Street.png"]


def test_migration_brings_old_saved_data_up_to_date(temp_db):
    from pipeline import prompts
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
