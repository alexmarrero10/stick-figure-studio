"""Tests for the November 2026 batch of changes: settings saves that report success or failure,
dropdown choices for model and effort, question titles, undo on the Beats step, the grammar check,
picking an image for an empty slot, dragging images to swap them, keeping batch checkmarks when
prompts are rewritten, and the Home screen's image status."""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from pipeline import images as images_mod
from pipeline import publish, script as script_mod
from tests.test_images_prompts_api import FakeClaude, _wait, png_bytes, project_with_beats

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from app import config, storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    # Settings saves go to a copy, never the real config.yaml.
    cfg = tmp_path / "config.yaml"
    shutil.copy(config.CONFIG_PATH, cfg)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config, "_cache", None)
    from app.main import app
    with TestClient(app) as c:
        yield c
    config._cache = None


# --- 1 + 2: settings -------------------------------------------------------------------------

def test_settings_save_returns_what_is_on_disk(client, tmp_path):
    r = client.put("/api/settings/config", json={"claude": {"effort": "medium", "code_model": "sonnet"}})
    assert r.status_code == 200
    assert r.json()["claude"]["effort"] == "medium"
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert on_disk["claude"]["effort"] == "medium" and on_disk["claude"]["code_model"] == "sonnet"


@pytest.mark.parametrize("bad", [{"effort": "extreme"}, {"code_model": "gpt"}, {"model": "claude-3-opus"}])
def test_settings_refuse_values_outside_the_dropdowns(client, tmp_path, bad):
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    r = client.put("/api/settings/config", json={"claude": bad})
    assert r.status_code == 400
    assert "must be one of" in r.json()["detail"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before  # nothing was saved


def test_settings_report_a_save_that_did_not_stick(client, monkeypatch):
    from app.routes import settings
    monkeypatch.setattr(settings, "save_config", lambda cfg: None)  # e.g. a read-only file
    r = client.put("/api/settings/config", json={"claude": {"effort": "low"}})
    assert r.status_code == 500 and "didn't keep" in r.json()["detail"]


def test_health_keeps_the_voice_name_in_step_with_the_id(client, tmp_path, monkeypatch):
    from app.routes import settings
    client.put("/api/settings/config", json={"voice": {"voice_id": "brian-id", "voice_name": "Josh"}})
    monkeypatch.setattr(settings, "get_key", lambda name: "k" if name == "ELEVENLABS_API_KEY" else "")
    monkeypatch.setattr(settings, "resolve_voice",
                        lambda key, vid, name: {"voice_id": vid, "name": "Brian - Deep, Resonant and Comforting"})
    monkeypatch.setattr(settings.claude_code, "auth_status", lambda: {})
    health = client.get("/api/settings/health").json()
    assert health["voice"]["name"].startswith("Brian")
    assert health["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert on_disk["voice"] == {**on_disk["voice"], "voice_id": "brian-id", "voice_name": "Brian"}


def test_dropdown_choices_cover_the_current_config(client):
    c = client.get("/api/settings/choices").json()
    assert c["effort"] == ["low", "medium", "high", "xhigh", "max"]
    assert set(c["code_model"]) == {"fable", "opus", "sonnet", "haiku"}
    assert "claude-opus-5-5" in c["model"]
    cfg = client.get("/api/settings").json()["config"]["claude"]
    assert cfg["effort"] in c["effort"] and cfg["code_model"] in c["code_model"] and cfg["model"] in c["model"]
    # The Settings page offers the same values.
    page = (ROOT / "frontend" / "src" / "steps" / "Settings.tsx").read_text(encoding="utf-8")
    for v in c["effort"] + c["code_model"] + c["model"]:
        assert f'value: "{v}"' in page


# --- 3: titles -------------------------------------------------------------------------------

def test_suggested_titles_are_short_and_never_give_the_answer():
    assert "under 55 characters" in publish.TITLE_RULES
    assert "NEVER contains the answer" in publish.TITLE_RULES
    assert "Why Hasn't Anyone" in publish.TITLE_RULES  # shapes distilled from the top channels
    assert publish.TITLE_RULES in publish.SYSTEM


def test_ideas_use_the_same_title_rules():
    from pipeline import ideas
    assert publish.TITLE_RULES in ideas.SYSTEM
    assert "never gives away the answer" in ideas.SYSTEM


def test_thumbnails_show_the_mystery_not_the_answer():
    for system in (publish.THUMB_ASK_SYSTEM, publish.THUMB_SUGGEST_SYSTEM):
        assert "Show the mystery, never the answer" in system


# --- 4: undo on the Beats step ---------------------------------------------------------------

def _ranges(client, pid):
    return [(b["word_start"], b["word_end"]) for b in client.get(f"/api/projects/{pid}/beats").json()]


def _two_word_beats(db, n):
    p = db.create_project("Undo test")
    text = " ".join(f"w{i}." for i in range(2 * n))
    v = db.save_script(p["id"], text, "generated")
    db.replace_beats(p["id"], v["id"], [{"idx": i, "word_start": 2 * i, "word_end": 2 * i + 1,
                                         "text": f"w{2 * i}. w{2 * i + 1}."} for i in range(n)])
    beats = db.list_beats(p["id"])
    db.upsert_prompts(p["id"], [{"beat_id": b["id"], "batch_no": 1, "scene": f"scene {b['idx']}",
                                 "label": f"Label {b['idx']}", "characters": [{"name": "Saddam", "variant": ""}]}
                                for b in beats[:3]])
    db.upsert_prompts(p["id"], [{"beat_id": beats[3]["id"], "batch_no": 1, "scene": "hand edited", "label": "Mine"}],
                      edited=True)
    return p["id"]


def test_undo_puts_back_the_last_split_and_merge(client, temp_db):
    pid = _two_word_beats(temp_db, 5)
    start = _ranges(client, pid)
    assert client.get(f"/api/projects/{pid}/beats/undo").json() == {"steps": 0}
    assert client.post(f"/api/projects/{pid}/beats/undo").status_code == 400

    client.post(f"/api/projects/{pid}/beats/ops", json={"ops": [{"op": "split", "beat": 1, "at": 3}]})
    after_split = _ranges(client, pid)
    assert len(after_split) == 6
    client.post(f"/api/projects/{pid}/beats/ops", json={"ops": [{"op": "merge", "beat": 3}]})
    assert client.get(f"/api/projects/{pid}/beats/undo").json() == {"steps": 2}

    # Undo the merge, then the split: back where we started, prompts and all.
    client.post(f"/api/projects/{pid}/beats/undo")
    assert _ranges(client, pid) == after_split
    client.post(f"/api/projects/{pid}/beats/undo")
    assert _ranges(client, pid) == start
    prompts = {p["idx"]: p for p in client.get(f"/api/projects/{pid}/prompts").json()["prompts"]}
    assert prompts[1]["scene"] == "scene 1" and prompts[1]["label"] == "Label 1"
    assert prompts[1]["characters"] == [{"name": "Saddam", "variant": ""}]
    assert prompts[3]["scene"] == "hand edited" and prompts[3]["edited"]
    assert client.get(f"/api/projects/{pid}/beats/undo").json() == {"steps": 0}


def test_rebuilding_or_editing_text_clears_undo(client, temp_db, monkeypatch):
    pid = _two_word_beats(temp_db, 5)
    client.post(f"/api/projects/{pid}/beats/ops", json={"ops": [{"op": "split", "beat": 0, "at": 1}]})
    assert client.get(f"/api/projects/{pid}/beats/undo").json()["steps"] == 1
    client.put(f"/api/projects/{pid}/beats/2/text", json={"text": "new words."})
    assert client.get(f"/api/projects/{pid}/beats/undo").json()["steps"] == 0

    client.post(f"/api/projects/{pid}/beats/ops", json={"ops": [{"op": "split", "beat": 0, "at": 1}]})
    client.post(f"/api/projects/{pid}/beats/build", json={"review": False})
    assert client.get(f"/api/projects/{pid}/beats/undo").json()["steps"] == 0


def test_undo_keeps_only_the_latest_steps(temp_db):
    pid = temp_db.create_project("Cap")["id"]
    for i in range(temp_db.BEAT_UNDO_STEPS + 5):
        temp_db.push_beat_undo(pid, {"n": i})
    assert temp_db.beat_undo_steps(pid) == temp_db.BEAT_UNDO_STEPS
    assert temp_db.pop_beat_undo(pid) == {"n": temp_db.BEAT_UNDO_STEPS + 4}


# --- 6: check grammar ------------------------------------------------------------------------

def test_edited_passages_finds_only_changed_sentences():
    before = "Saddam ran Iraq for decades. He hid near Tikrit. The soldiers searched the farm."
    after = "Saddam ran Iraq for decades. He hided near Tikrit in a hole. The soldiers searched the farm."
    assert script_mod.edited_passages(before, after) == ["He hided near Tikrit in a hole."]
    assert script_mod.edited_passages(after, after) == []


class GrammarFake:
    def __init__(self):
        self.asks: list[str] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        self.asks.append(messages[-1]["content"])
        assert "Fix only real mistakes" in system
        return {"reply": "Fixed one verb.", "edits": [
            {"find": "He hided near Tikrit", "replace": "He hid near Tikrit", "reason": "past tense of hide"},
            {"find": "not in the script", "replace": "x", "reason": "bad quote"},
            {"find": "same", "replace": "same", "reason": "no-op"}]}


def test_grammar_check_focuses_on_hand_edits(client, temp_db, monkeypatch):
    p = temp_db.create_project("Grammar")
    temp_db.save_script(p["id"], "Saddam ran Iraq. He hid near Tikrit. Soldiers came.", "generated")
    temp_db.save_script(p["id"], "Saddam ran Iraq. He hided near Tikrit. Soldiers came.", "manual")
    fake = GrammarFake()
    monkeypatch.setattr("app.routes.script.claude", lambda: fake)
    r = client.post(f"/api/projects/{p['id']}/script/grammar").json()
    assert "EDITED PASSAGES" in fake.asks[0] and "- He hided near Tikrit." in fake.asks[0]
    assert "- Saddam ran Iraq." not in fake.asks[0]
    assert r["passages"] == 1 and r["content"] == "Fixed one verb."
    assert [e["ok"] for e in r["edits"]] == [True, False]  # the no-op is dropped, the bad quote flagged
    # It shows up in the chat history like any other suggestion, and applies the usual way.
    assert client.get(f"/api/projects/{p['id']}/script/chat").json()[-1]["content"] == "Fixed one verb."
    out = client.post(f"/api/projects/{p['id']}/script/apply-edits",
                      json={"edits": r["edits"][:1], "instruction": "Check grammar"}).json()
    assert out["version"]["text"] == "Saddam ran Iraq. He hid near Tikrit. Soldiers came."


def test_grammar_check_needs_a_script(client, temp_db):
    p = temp_db.create_project("Empty")
    assert client.post(f"/api/projects/{p['id']}/script/grammar").status_code == 400


# --- 9 + 11: images --------------------------------------------------------------------------

def _slots(resp, batch=1):
    b = next(x for x in resp["batches"] if x["batch_no"] == batch)
    return [s["image"]["name"] if s["image"] else None for s in b["slots"]]


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


# --- 10: rewriting prompts keeps batch checkmarks --------------------------------------------

def test_regenerating_all_prompts_keeps_batch_checkmarks(client, temp_db, monkeypatch):
    pid = project_with_beats(temp_db, 30)
    monkeypatch.setattr("app.routes.prompts.claude", lambda: FakeClaude())
    _wait(client, client.post(f"/api/projects/{pid}/prompts/generate", json={}).json())
    client.put(f"/api/projects/{pid}/prompts/batch/1/done", json={"done": True})
    _wait(client, client.post(f"/api/projects/{pid}/prompts/generate", json={"only_missing": False}).json())
    assert client.get(f"/api/projects/{pid}/prompts").json()["done_batches"] == [1]
    page = (ROOT / "frontend" / "src" / "steps" / "Images.tsx").read_text(encoding="utf-8")
    assert "batch checkmarks are cleared" not in page


# --- 12: Home shows images as done only when every slot has one ------------------------------

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


# --- 7: clicking a suggested edit finds it in the script (frontend helper) -------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_find_passage_in_the_script():
    test = ROOT / "frontend" / "src" / "textarea.test.ts"
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--test", str(test)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


# --- idea suggestions: 3 at a time -------------------------------------------------------------

def test_claude_suggests_three_ideas_by_default():
    from pipeline import ideas

    class FakeClaude:
        def json(self, system, messages, schema, **kw):
            self.prompt = messages[0]["content"]
            return {"ideas": []}

    fake = FakeClaude()
    ideas.suggest(fake)
    assert fake.prompt.startswith("Suggest 3 video topics.")
    assert "at most one can be a topic explainer or a countdown list" in fake.prompt
    from app.routes.ideas import SuggestBody
    assert SuggestBody().count == 3


# --- own ideas are kept: saved straight away, listed until they become a project ---------------

def test_own_idea_is_saved_and_listed_until_used(client, temp_db):
    idea = client.post("/api/ideas/own", json={"text": "The Great Molasses Flood", "refine": False}).json()
    assert idea["saved"] == 1 and idea["source"] == "user"
    temp_db.add_ideas([{"title": "A suggestion"}], "suggested")
    unused = client.get("/api/ideas?unused=true").json()
    assert [i["title"] for i in unused] == ["A suggestion", "The Great Molasses Flood"]  # newest first
    assert [i["title"] for i in client.get("/api/ideas?saved=true&unused=true").json()] == ["The Great Molasses Flood"]
    client.post(f"/api/ideas/{idea['id']}/use")
    assert client.get("/api/ideas?saved=true&unused=true").json() == []  # now it's a project
    assert client.get("/api/ideas?saved=true").json()[0]["id"] == idea["id"]  # still on record


def test_suggested_ideas_are_not_saved_until_asked(client, temp_db):
    new = temp_db.add_ideas([{"title": "One"}, {"title": "Two"}], "suggested")
    assert all(i["saved"] == 0 for i in new)
    client.put(f"/api/ideas/{new[0]['id']}/saved", json={"saved": True})
    assert [i["title"] for i in client.get("/api/ideas?saved=true&unused=true").json()] == ["One"]
