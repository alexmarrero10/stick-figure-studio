"""API tests for the combined prompts + images step: slot-aware re-uploads, clearing a batch,
batch checkmarks, and consistent prompt writing (visual bible + scenes written in order)."""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pipeline import prompts


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    from app.main import app
    with TestClient(app) as c:
        yield c


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


def project_with_beats(db, n_beats: int) -> int:
    p = db.create_project("Franklin test")
    words = " ".join(f"w{i}." for i in range(n_beats))
    v = db.save_script(p["id"], words, "generated")
    db.replace_beats(p["id"], v["id"], [{"idx": i, "word_start": i, "word_end": i, "text": f"w{i}."}
                                        for i in range(n_beats)])
    return p["id"]


def upload(client, pid, batch, files):
    return client.post(f"/api/projects/{pid}/images/{batch}/upload", files=files).json()


def filled(resp, batch=1):
    b = next(x for x in resp["images"]["batches"] if x["batch_no"] == batch)
    return [s["image"]["name"] if s["image"] else None for s in b["slots"]]


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


def test_batch_checkmarks(client, temp_db):
    pid = project_with_beats(temp_db, 30)
    assert client.put(f"/api/projects/{pid}/prompts/batch/2/done", json={"done": True}).json() == {"done_batches": [2]}
    client.put(f"/api/projects/{pid}/prompts/batch/1/done", json={"done": True})
    client.put(f"/api/projects/{pid}/prompts/batch/2/done", json={"done": False})
    assert client.get(f"/api/projects/{pid}/prompts").json()["done_batches"] == [1]


class FakeClaude:
    """Returns a style guide with a recurring ship, and one scene per requested beat. Records requests."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        sys_text = system if isinstance(system, str) else system[0]["text"]
        ask = messages[-1]["content"]
        self.calls.append((sys_text, ask))
        if "props" in schema["properties"]:
            return {"palette": "navy blue, mustard gold", "setting_notes": "Arctic, 1840s.",
                    "characters": [{"name": "Franklin", "marker": "a plaid tartan scarf"}],
                    "props": [{"name": "Erebus", "look": "a three-masted ship with a black hull and one gold stripe"}],
                    "locations": [{"name": "Tundra", "look": "flat white snowy tundra under a pale gray sky"}]}
        if "beats" in schema["properties"]:  # the cast step: Franklin is in every image
            section = ask.split("BEATS TO CAST:")[1]
            idxs = [int(line.split(":")[0]) for line in section.strip().splitlines() if line.strip()]
            return {"beats": [{"idx": i, "cast": [{"name": "franklin", "variant": ""}]} for i in idxs]}
        section = ask.split("BEATS TO ILLUSTRATE:")[1].split("Narration just after")[0]
        idxs = [int(line.split(":")[0]) for line in section.strip().splitlines() if line.strip() and line[0] != " "]
        return {"scenes": [{"idx": i, "label": f"Scene {i}",
                            "scene": f"Beat {i}: a three-masted ship with a black hull and one gold stripe."} for i in idxs]}


def test_scenes_are_written_in_order_with_previous_scenes():
    fake = FakeClaude()
    guide = {"characters": [{"name": "F", "marker": "a scarf"}],
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
    assert "in this image (copy each look, not the name): Franklin = stick figure with a plaid tartan scarf" in fake.calls[2][1]
    assert all("stick figure with a plaid tartan scarf" in p["scene"] for p in data["prompts"])
    text2 = data["batch_texts"]["2"]
    assert text2.startswith("INSTRUCTIONS FOR BATCH 2 OF 2")
    assert "continue the same video" in text2
    assert "\n\n1 - Scene 24. Beat 24: a three-masted ship" in text2
    assert text2.count("\n\n") == 6  # header + 6 prompts


def test_page_is_never_cached(client):
    from app import main
    if not main.DIST.exists():
        pytest.skip("UI not built")
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_prompt_rules_forbid_text_bubbles_and_camera_moves():
    assert "no look may contain writing" in prompts.STYLE_SYSTEM
    assert "speech bubbles" in prompts.SCENE_SYSTEM and "never camera movement" in prompts.SCENE_SYSTEM
