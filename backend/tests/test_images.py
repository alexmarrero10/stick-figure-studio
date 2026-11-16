"""Images: matching uploaded files to their slots, bulk upload, drag and swap, and image status."""
import io
import zipfile
from pathlib import Path

from PIL import Image

from pipeline import images
from pipeline import images as images_mod
from tests.helpers import make_png, project_with_beats


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (160, 90), "white").save(buf, "PNG")
    return buf.getvalue()


def make_zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(f"Flow download/{n}", png_bytes())
    return buf.getvalue()


def upload(client, pid, batch, files):
    return client.post(f"/api/projects/{pid}/images/{batch}/upload", files=files).json()


def filled(resp, batch=1):
    b = next(x for x in resp["images"]["batches"] if x["batch_no"] == batch)
    return [s["image"]["name"] if s["image"] else None for s in b["slots"]]


WORDS = ("apple bridge candle desert eagle forest garden harbor island jungle kettle lantern meadow "
         "orchard palace quarry river saddle temple valley wagon yacht zebra anchor beacon cellar "
         "dagger ember falcon goblet").split()


def _slots(resp, batch=1):
    b = next(x for x in resp["batches"] if x["batch_no"] == batch)
    return [s["image"]["name"] if s["image"] else None for s in b["slots"]]


def _upload(client, pid, names, batch=1):
    return client.post(f"/api/projects/{pid}/images/{batch}/upload",
                       files=[("files", (n, png_bytes(), "image/png")) for n in names]).json()


def _move(client, pid, path, to, batch=1):
    r = client.post(f"/api/projects/{pid}/images/{batch}/move", json={"path": path, "to": to})
    assert r.status_code == 200, r.text
    return r.json()


def _path(resp, name, batch=1):
    b = next(x for x in resp["batches"] if x["batch_no"] == batch)
    return next(im["path"] for im in [s["image"] for s in b["slots"] if s["image"]] + b["extra"] if im["name"] == name)


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
    import io
    import zipfile
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


def test_reupload_only_adds_missing_images(client, temp_db):
    pid = project_with_beats(temp_db, 30)  # batch 1 has 24 slots
    first = upload(client, pid, 1, [("files", ("b1.zip", make_zip(["1 - Ship.png", "3 - Ice.png"]), "application/zip"))])
    assert first["added"] == 2 and first["skipped"] == 0
    assert filled(first)[:4] == ["1 - Ship.png", None, "3 - Ice.png", None]

    # Re-upload the whole download, now with 2 and 4 as well and a second take of 1 under another name.
    again = upload(client, pid, 1, [("files", ("b1.zip", make_zip(
        ["1 - Ship.png", "1 - Ship (1).png", "2 - Camp.png", "3 - Ice.png", "4 - Sled.png"]), "application/zip"))])
    assert again["added"] == 2 and again["skipped"] == 3
    assert filled(again)[:5] == ["1 - Ship.png", "2 - Camp.png", "3 - Ice.png", "4 - Sled.png", None]
    batch = next(x for x in again["images"]["batches"] if x["batch_no"] == 1)
    assert batch["count"] == 4 and batch["extra"] == []

    # Loose image files follow the same rule, and numbers past the end of the batch are skipped.
    loose = upload(client, pid, 1, [("files", ("4 - Sled.png", png_bytes(), "image/png")),
                                    ("files", ("5 - Shore.png", png_bytes(), "image/png")),
                                    ("files", ("30 - Nope.png", png_bytes(), "image/png"))])
    assert loose["added"] == 1 and loose["skipped"] == 2
    assert filled(loose)[4] == "5 - Shore.png"


def test_unnumbered_images_stop_when_batch_is_full(client, temp_db):
    pid = project_with_beats(temp_db, 26)  # batch 2 has 2 slots
    r = upload(client, pid, 2, [("files", (f"img{i}.png", png_bytes(), "image/png")) for i in range(4)])
    assert r["added"] == 2 and r["skipped"] == 2
    assert filled(r, 2) == ["img0.png", "img1.png"]


def test_clear_batch_removes_every_image(client, temp_db):
    pid = project_with_beats(temp_db, 30)
    upload(client, pid, 1, [("files", ("b.zip", make_zip(["1 - A.png", "2 - B.png", "extra.png"]), "application/zip"))])
    upload(client, pid, 2, [("files", ("1 - Z.png", png_bytes(), "image/png"))])
    r = client.post(f"/api/projects/{pid}/images/1/clear").json()
    assert r["removed"] == 3
    b1, b2 = r["batches"][0], r["batches"][1]
    assert b1["count"] == 0 and all(s["image"] is None for s in b1["slots"])
    assert b2["count"] == 1  # other batches untouched
    p = temp_db.get_project(pid)
    from app.storage import batch_images_dir
    assert list(batch_images_dir(p["slug"], 1).iterdir()) == []


def test_images_named_after_their_prompt_title_land_in_that_slot(client, temp_db):
    pid = project_with_beats(temp_db, 6)
    beats = temp_db.list_beats(pid)
    labels = ["Ship in ice", "Snowy camp", "Ship in ice", "Sled dogs", "Frozen sea", "Night sky"]
    temp_db.upsert_prompts(pid, [{"beat_id": b["id"], "batch_no": 1, "scene": f"A scene about {lbl.lower()} and lanterns.",
                                  "label": lbl, "characters": None, "things": None} for b, lbl in zip(beats, labels)])
    titles = client.get(f"/api/projects/{pid}/prompts").json()["prompts"]
    assert [t["title"] for t in titles][:3] == ["Ship in ice", "Snowy camp", "Ship in scene"]  # made unique
    # Flow downloads in any order, with its own spacing and copy numbers.
    r = upload(client, pid, 1, [("files", ("b1.zip", make_zip(
        ["Sled_dogs.png", "Ship in scene (1).png", "Ship in ice.png", "Snowy camp 7f3a.png", "random.png"]),
        "application/zip"))])
    assert filled(r)[:5] == ["1 - Ship in ice.png", "2 - Snowy camp 7f3a.png", "3 - Ship in scene (1).png",
                             "4 - Sled_dogs.png", "random.png"]


def test_slot_for_title_needs_one_clear_match():
    from pipeline import images as images_mod
    titles = {1: "Oval Office", 2: "Oval Office desk", 3: "Night raid"}
    assert images_mod.slot_for_title("Oval Office.png", titles) == 1
    assert images_mod.slot_for_title("oval_office_desk (2).jpg", titles) == 2
    assert images_mod.slot_for_title("Night raid extra words.png", titles) == 3
    assert images_mod.slot_for_title("Oval.png", titles) is None  # could be 1 or 2
    assert images_mod.slot_for_title("7 - Oval Office.png", titles) is None  # numbered files keep their number


def test_bulk_upload_sorts_each_flow_download_into_its_batch(client, temp_db):
    pid = project_with_beats(temp_db, 30)  # batch 1: 24 slots, batch 2: 6
    beats = temp_db.list_beats(pid)
    labels = [f"Old {w}" for w in WORDS[:30]]
    labels[25] = labels[3]  # batch 2 slot 2 has the same title as batch 1 slot 4
    temp_db.upsert_prompts(pid, [{"beat_id": b["id"], "batch_no": 1 + i // 24, "scene": f"A {lbl.lower()} scene.",
                                  "label": lbl, "characters": None, "things": None}
                                 for i, (b, lbl) in enumerate(zip(beats, labels))])

    def inner(names):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in names:
                z.writestr(n, png_bytes())
        return buf.getvalue()

    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        # batch 2's download as a zip: "Old desert" is in both batches, "random" matches nothing
        z.writestr("all/flow (2).zip", inner(["Old_dagger.png", "Old desert.png", "random.png"]))
        for lbl in labels[:24]:  # batch 1's download as a folder
            z.writestr(f"all/first/{lbl}.png", png_bytes())
        z.writestr("Mystery.png", png_bytes())  # no title, no batch
    r = client.post(f"/api/projects/{pid}/images/upload-all",
                    files=[("files", ("everything.zip", outer.getvalue(), "application/zip"))]).json()
    assert r["added"] == {"1": 24, "2": 3}
    assert r["unplaced"] == ["Mystery.png"]
    assert filled(r)[3] == "4 - Old desert.png"
    b2 = filled(r, 2)
    assert b2[:3] == ["random.png", "2 - Old desert.png", "3 - Old_dagger.png"]  # random fills a free slot

    # Doing it again adds nothing.
    again = client.post(f"/api/projects/{pid}/images/upload-all",
                        files=[("files", ("everything.zip", outer.getvalue(), "application/zip"))]).json()
    assert again["added"] == {} and again["skipped"] == 27


def test_plan_group_uses_the_batch_name_when_titles_dont_match():
    from pipeline import images as images_mod
    titles = {1: {1: "Night raid"}, 2: {1: "Oval Office"}, 3: {1: "Night raid"}}
    assert images_mod.plan_group("batch_02", ["a.png", "b.png"], titles) == [2, 2]
    assert images_mod.plan_group("x", ["Oval Office.png", "c.png"], titles) == [2, 2]
    assert images_mod.plan_group("x", ["Night raid.png"], titles) == [None]  # in two batches
    assert images_mod.plan_group("batch 3", ["Night raid.png"], titles) == [3]


def test_plan_group_settles_titles_shared_by_batches_from_zip_order():
    from pipeline import images as images_mod
    titles = {1: {1: "Back", 2: "Guard", 3: "Night raid"}, 2: {1: "Back", 2: "Guard spots tape", 3: "Sunrise"}}
    # One flat Flow zip, newest batch first, with Flow's hex suffixes.
    names = ["Sunrise_0a1b2c3d.jpg", "Back_11111111.jpg", "Guard_spots_tape_9f9f9f9f.jpg",
             "Night_raid_22222222.jpg", "Back_33333333.jpg", "Guard_44444444.jpg"]
    assert images_mod.plan_group("download", names, titles) == [2, 2, 2, 1, 1, 1]


def test_pick_an_image_for_an_empty_slot(client, temp_db):
    pid = project_with_beats(temp_db, 30)
    beat = temp_db.list_beats(pid)[2]
    temp_db.upsert_prompts(pid, [{"beat_id": beat["id"], "batch_no": 1, "scene": "x", "label": "Spider hole"}])
    r = client.post(f"/api/projects/{pid}/images/1/slot/2", files={"file": ("download.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    assert _slots(r.json()["images"])[:4] == [None, None, "3 - Spider hole.png", None]
    # It stays in that slot when the folder is read again.
    assert _slots(client.post(f"/api/projects/{pid}/images/1/rescan").json()["images"])[2] == "3 - Spider hole.png"

    taken = client.post(f"/api/projects/{pid}/images/1/slot/2", files={"file": ("b.png", png_bytes(), "image/png")})
    assert taken.status_code == 400 and "already has an image" in taken.json()["detail"]
    assert client.post(f"/api/projects/{pid}/images/1/slot/40",
                       files={"file": ("b.png", png_bytes(), "image/png")}).status_code == 400
    assert client.post(f"/api/projects/{pid}/images/1/slot/0",
                       files={"file": ("notes.txt", b"hi", "text/plain")}).status_code == 400


def test_drag_swaps_two_images_and_the_swap_sticks(client, temp_db):
    pid = project_with_beats(temp_db, 30)
    imgs = _upload(client, pid, ["1 - Palace.png", "2 - Farm.png", "3 - Hole.png"])["images"]
    r = _move(client, pid, _path(imgs, "1 - Palace.png"), 2)
    assert _slots(r)[:3] == ["1 - Hole.png", "2 - Farm.png", "3 - Palace.png"]
    # Files were renamed, so reading the folder again keeps the new order.
    again = client.post(f"/api/projects/{pid}/images/1/rescan").json()["images"]
    assert _slots(again)[:3] == ["1 - Hole.png", "2 - Farm.png", "3 - Palace.png"]

    # Onto an empty slot: it just moves there.
    r = _move(client, pid, _path(again, "2 - Farm.png"), 5)
    assert _slots(r)[:6] == ["1 - Hole.png", None, "3 - Palace.png", None, None, "6 - Farm.png"]


def test_dragging_an_extra_onto_a_slot(client, temp_db):
    pid = project_with_beats(temp_db, 2)  # one batch of 2 slots
    imgs = _upload(client, pid, ["1 - Palace.png", "2 - Farm.png"])["images"]
    # A third image lands as an extra (its number is past the end of the batch).
    folder = Path(_path(imgs, "1 - Palace.png")).parent
    (folder / "9 - Hole.png").write_bytes(png_bytes())
    imgs = client.post(f"/api/projects/{pid}/images/1/rescan").json()["images"]
    assert [im["name"] for im in imgs["batches"][0]["extra"]] == ["9 - Hole.png"]

    r = _move(client, pid, _path(imgs, "9 - Hole.png"), 0)
    assert _slots(r) == ["1 - Hole.png", "2 - Farm.png"]
    assert [im["name"] for im in r["batches"][0]["extra"]] == ["Palace.png"]  # the one it pushed out


def test_move_refuses_paths_outside_the_batch(client, temp_db, tmp_path):
    pid = project_with_beats(temp_db, 30)
    _upload(client, pid, ["1 - Palace.png"])
    outside = tmp_path / "1 - Elsewhere.png"
    outside.write_bytes(png_bytes())
    r = client.post(f"/api/projects/{pid}/images/1/move", json={"path": str(outside), "to": 1})
    assert r.status_code == 400 and outside.exists()


def test_numbered_rewrites_the_slot_number():
    assert images_mod.numbered("12_-_Vault.jpg", 3) == "3 - Vault.jpg"
    assert images_mod.numbered("7 - Ship.png", None) == "Ship.png"
    assert images_mod.numbered("photo.png", 4) == "4 - photo.png"


def test_image_status_counts_filled_slots(client, temp_db):
    pid = project_with_beats(temp_db, 3)
    status = lambda: client.get(f"/api/projects/{pid}").json()["status"]  # noqa: E731
    assert status()["images_filled"] == 0 and status()["images_complete"] is False

    _upload(client, pid, ["1 - A.png", "2 - B.png"])
    assert status()["images_filled"] == 2 and status()["images_complete"] is False

    # An extra doesn't make the batch complete.
    folder = Path(temp_db.list_images(pid)[0]["path"]).parent
    (folder / "9 - Extra.png").write_bytes(png_bytes())
    client.post(f"/api/projects/{pid}/images/1/rescan")
    s = status()
    assert s["images"] == 3 and s["images_filled"] == 2 and s["images_complete"] is False

    _upload(client, pid, ["3 - C.png"])
    assert status()["images_filled"] == 3 and status()["images_complete"] is True


def test_image_status_with_no_beats_is_not_complete(temp_db):
    pid = temp_db.create_project("Blank")["id"]
    s = temp_db.project_status(pid)
    assert s["images_filled"] == 0 and s["images_complete"] is False
