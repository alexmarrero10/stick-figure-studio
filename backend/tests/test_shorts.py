"""General tags, video formats and sources, eye-catching openings, the vertical Short (made by Assemble),
and archiving projects."""
import json
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pipeline import ffmpeg, ideas, prompts, publish, script, shorts
from tests.test_voice import make_wav


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    from app.routes import projects as projects_route
    monkeypatch.setattr(projects_route, "PROJECTS_DIR", tmp_path / "projects")
    from app.main import app
    with TestClient(app) as c:
        yield c


# --- 1. tags --------------------------------------------------------------------

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


# --- 2. formats and sources -------------------------------------------------------

def test_guess_format():
    assert ideas.guess_format("Top 5 navy pilot UFO encounters") == "list"
    assert ideas.guess_format("top 3 unexplained ship disappearances") == "list"
    assert ideas.guess_format("How did ancient Aztec sacrifices work?") == "topic"
    assert ideas.guess_format("Why humans have a fear of humanoid figures") == "topic"
    assert ideas.guess_format("The D.B. Cooper hijacking") == "story"


class RecordingClaude:
    def __init__(self, text="## Summary\nStuff [1]\n\n## Sources\n1. [Navy report - US Navy](https://navy.mil/r)"):
        self.text = text
        self.calls = []

    def complete(self, system, messages, max_tokens=0, tools=None, effort=None):
        from types import SimpleNamespace
        self.calls.append((system, messages[-1]["content"]))
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_research_asks_for_the_format_and_cited_sources():
    c = RecordingClaude()
    brief, sources = script.research(c, {"title": "Top 5 Navy pilot UFO encounters"}, True, "list")
    system, ask = c.calls[0]
    assert "Mark facts with the number" in system and "Never make up or guess a URL" in system
    assert "{depth}" not in system and "Start from what you already know" in system  # quick by default
    assert "countdown of several separate true cases" in ask and "research each one on its own" in ask
    assert sources == [{"title": "Navy report - US Navy", "url": "https://navy.mil/r"}]
    script.research(c, {"title": "Blitzkrieg"}, True, "topic")
    assert "Myths vs. evidence" in c.calls[1][1]
    script.research(c, {"title": "Blitzkrieg"}, True, "topic", depth="thorough")
    assert "Mark every fact" in c.calls[2][0] and "already know" not in c.calls[2][0]


def test_dead_source_links_are_dropped():
    def handler(req: httpx.Request) -> httpx.Response:
        if "dead" in req.url.path:
            return httpx.Response(404)
        if "blocked" in req.url.path:
            return httpx.Response(403)
        if "nohead" in req.url.path:
            return httpx.Response(405) if req.method == "HEAD" else httpx.Response(200)
        if "nosite" in req.url.host:
            raise httpx.ConnectError("no such host", request=req)
        return httpx.Response(200)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    src = [{"title": n, "url": f"https://{'nosite' if n == 'nosite' else 'ok'}.org/{n}"}
           for n in ("good", "dead", "blocked", "nohead", "nosite")]
    assert [s["title"] for s in script.check_sources(src, c)] == ["good", "blocked", "nohead"]


def test_script_prompt_has_format_rules_and_accuracy():
    msg = script.build_script_messages({"title": "Top 3 ship disappearances"}, "brief", (1550, 1650), format="list")
    text = msg[0]["content"]
    assert "COUNTDOWN OF SEVERAL TRUE CASES" in text and "Never blend facts from different entries" in text
    assert "every fact, name, date and number must come from the research brief" in text
    topic = script.build_script_messages({"title": "Blitzkrieg"}, "brief", (1550, 1650), format="topic")[0]["content"]
    assert "A TOPIC EXPLAINED" in topic


def test_publish_description_keeps_the_research_sources():
    class C:
        def json(self, *a, **k):
            return {"titles": ["T"], "description": "Hook.", "tags": ["navy"], "chapters": [{"beat": 0, "title": "Start"}],
                    "thumbnails": [{"scene": "A shocked stick figure holds a huge silver fork.", "background": "deep navy blue"}]}
    beats = [{"idx": 0, "word_start": 0, "text": "w"}]
    meta_ = publish.generate(C(), "T", "w", beats, [], [{"title": "Navy report", "url": "https://navy.mil/r"}],
                             ["animation", "history", "education"])
    assert "Sources\n- Navy report: https://navy.mil/r" in meta_["description"]
    assert meta_["tags"] == ["navy", "animation", "history", "education"]
    thumb = meta_["thumbnail_prompts"][0]
    assert thumb.startswith("A shocked stick figure holds a huge silver fork. Background: deep navy blue. YouTube thumbnail")
    assert prompts.BODY in thumb  # no style guide yet: the default video style
    # With a style guide, the thumbnail ends with the video's own style text, like every image prompt.
    guide = {"style_prefix": "Minimalist stick figure illustration, thin black stick limbs, flat colors (sand beige).",
             "characters": [], "props": [], "locations": []}
    meta_ = publish.generate(C(), "T", "w", beats, [], [], [], guide)
    assert meta_["thumbnail_prompts"][0].endswith(prompts.with_body_rule(guide["style_prefix"]))


def test_projects_store_their_format(client, temp_db):
    p = client.post("/api/projects", json={"title": "Top 5 UFO encounters", "format": "list"}).json()
    assert p["format"] == "list"
    assert client.patch(f"/api/projects/{p['id']}", json={"format": "topic"}).json()["format"] == "topic"
    assert client.patch(f"/api/projects/{p['id']}", json={"format": "nonsense"}).status_code == 400
    idea = temp_db.add_ideas([{"title": "How Blitzkrieg worked", "format": "topic"}])[0]
    assert idea["format"] == "topic"
    assert client.post(f"/api/ideas/{idea['id']}/use").json()["format"] == "topic"


# --- 3. eye-catching openings -----------------------------------------------------

def test_script_opening_is_written_to_work_as_a_short():
    assert "posted on its own as a" in script.SCRIPT_SYSTEM and "cliffhanger" in script.SCRIPT_SYSTEM
    assert "stop a thumb mid-scroll" in script.SCRIPT_SYSTEM


def test_opening_beats_from_timings_or_estimate():
    beats = [{"idx": i, "word_start": i * 10, "text": "w"} for i in range(40)]
    words = [{"start": i * 0.5} for i in range(400)]  # 5 s per beat
    assert shorts.opening_beats(beats, words, 59) == set(range(12))
    assert shorts.opening_beats(beats, [], 59, wpm=180) == set(range(18))  # 3.33 s per beat


def test_opening_images_are_marked_for_claude():
    from tests.test_images_prompts_api import FakeClaude
    fake = FakeClaude()
    guide = {"characters": [], "props": [], "locations": [], "setting_notes": ""}
    beats = [{"idx": i, "text": f"w{i}."} for i in range(60)]
    prompts.write_scenes(fake, "s", guide, beats, group=40, opening={0, 1, 2, 3, 4, 5})
    assert "Beats 0-5 are OPENING IMAGES" in fake.calls[0][1]
    assert "OPENING IMAGES" not in fake.calls[1][1]
    assert "OPENING IMAGES: the beats marked as the opening" in fake.calls[0][0]


# --- 4. the Short -------------------------------------------------------------------

def test_cut_shots_stops_at_59_seconds():
    shots_ = [{"image": f"{i}.png", "start_frame": i * 300, "end_frame": (i + 1) * 300, "scale": 1.0, "beat_ids": [i]}
              for i in range(10)]
    cut = shorts.cut_shots(shots_, 30, 59)
    assert len(cut) == 6 and cut[-1]["end_frame"] == 1770


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")
def test_short_render_is_vertical_and_cuts_at_59_seconds(tmp_path):
    wav = tmp_path / "voice.wav"
    make_wav(wav, 64.0)
    imgs = []
    for i in range(4):
        p = tmp_path / f"{i}.png"
        im = Image.new("RGB", (1376, 768), (247, 244, 236))
        ImageDraw.Draw(im).rectangle((0, 0, 1375, 767), outline=(200, 30, 30), width=40)  # red edge to see trimming
        ImageDraw.Draw(im).ellipse((588, 284, 788, 484), fill=(20, 60, 160))
        im.save(p)
        imgs.append(str(p))
    shots_ = [{"image": imgs[i % 4], "start_frame": i * 480, "end_frame": (i + 1) * 480, "scale": 1.0, "beat_ids": [i]}
              for i in range(4)]  # 64 s of shots
    out = tmp_path / "short.mp4"
    cfg = {"max_seconds": 59, "channel_name": "Stick Figure History", "width": 1080, "height": 1920,
           "image_aspect": 1.5, "margin": 24}
    res = shorts.render(shots_, wav, out, {"fps": 30, "crf": 28, "background": "#F7F4EC"}, cfg, tmp_path / "_w")
    assert abs(res["duration"] - 59.0) < 0.1
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,nb_frames,duration", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)["streams"]
    v = next(s for s in probe if s["codec_type"] == "video")
    a = next(s for s in probe if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1080, 1920) and int(v["nb_frames"]) == 59 * 30
    assert abs(float(a["duration"]) - 59.0) < 0.1

    frame = next((tmp_path / "_w" / "frames").glob("*.png"))
    with Image.open(frame) as f:
        L = shorts.layout(cfg)
        assert f.size == (1080, 1920)
        # The picture fills the width between the margins and is trimmed at the sides (no red side edge).
        mid = L["img_top"] + L["img_h"] // 2
        assert f.getpixel((L["img_x"] + 2, mid)) != (200, 30, 30)
        assert f.getpixel((540, mid))[2] > 120  # the blue circle is centred
        # The channel name is drawn just under the picture, on the left half.
        assert L["text_y"] > L["img_top"] + L["img_h"]
        left = f.crop((0, L["text_y"] - 30, 540, L["text_y"] + 30)).convert("L")
        right = f.crop((900, L["text_y"] - 30, 1080, L["text_y"] + 30)).convert("L")
        assert left.getextrema()[1] > 200 and right.getextrema()[1] < 60  # white name on black
        assert f.getpixel((540, 40)) == (0, 0, 0)  # the rest is black background


# --- 4b. Assemble makes the Short too ------------------------------------------------

def _assemble(client, temp_db, monkeypatch, channel="NextDoorHistorian", short_fails=False):
    """Run the Assemble job with the slow parts faked; returns the finished job."""
    import time as _time
    from app.routes import assemble as route
    p = temp_db.create_project("Franklin")
    words = [{"text": "w", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(200)]
    plan = {"shots": [{"image": "a.png", "start_frame": 0, "end_frame": 30, "scale": 1.0, "beat_ids": [0]}],
            "missing_images": [], "unused_images": [], "total_frames": 30}
    monkeypatch.setattr(route, "_plan", lambda pid: plan)
    monkeypatch.setattr(route.db, "get_voiceover", lambda pid: {"audio_path": "voice.wav", "duration_s": 100.0, "script_version_id": None})
    monkeypatch.setattr(route.db, "list_words", lambda pid: words)
    monkeypatch.setattr(route.fcpxml, "build", lambda *a, **k: "<fcpxml/>")
    monkeypatch.setattr(route, "short_cfg", lambda: {"min_seconds": 50, "max_seconds": 70, "channel_name": channel})
    monkeypatch.setattr(route.assemble, "render", lambda *a, **k: {"duration": 100.0, "expected": 100.0})
    monkeypatch.setattr(route.shorts, "choose_cut", lambda claude, w, lo, hi: 61.5)
    monkeypatch.setattr(route, "claude", lambda: None)
    made = []

    def fake_short(shots, audio, out, vcfg, scfg, work, progress, seconds=None):
        if short_fails:
            raise RuntimeError("ffmpeg broke")
        made.append(seconds)
        return {"duration": seconds}

    monkeypatch.setattr(route.shorts, "render", fake_short)
    job = client.post(f"/api/projects/{p['id']}/assemble").json()
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        _time.sleep(0.02)
    return p, job, made


def test_assemble_makes_the_full_video_and_the_short(client, temp_db, monkeypatch):
    p, job, made = _assemble(client, temp_db, monkeypatch)
    assert job["status"] == "done" and job["result"]["short"] == {"duration": 61.5}
    assert made == [61.5] and job["result"]["short_error"] is None
    assert temp_db.get_short(p["id"])["cut_s"] == 61.5 and temp_db.project_status(p["id"])["short"]


def test_assemble_keeps_the_full_video_when_the_short_cant_be_made(client, temp_db, monkeypatch):
    _, job, made = _assemble(client, temp_db, monkeypatch, channel="")
    assert job["status"] == "done" and made == [] and "channel name" in job["result"]["short_error"]
    _, job, _ = _assemble(client, temp_db, monkeypatch, short_fails=True)
    assert job["status"] == "done" and "ffmpeg broke" in job["result"]["short_error"]


# --- 5. archive -------------------------------------------------------------------------

def test_archive_then_delete(client, temp_db, tmp_path):
    from app.storage import project_dir
    p = client.post("/api/projects", json={"title": "Old idea"}).json()
    keep = client.post("/api/projects", json={"title": "Keep me"}).json()
    folder = project_dir(p["slug"])
    assert folder.exists()
    assert client.delete(f"/api/projects/{p['id']}?delete_files=true").status_code == 400  # must archive first
    assert client.patch(f"/api/projects/{p['id']}", json={"archived": True}).json()["archived"] == 1
    listed = {x["title"]: x["archived"] for x in client.get("/api/projects").json()}
    assert listed == {"Old idea": 1, "Keep me": 0}
    assert client.patch(f"/api/projects/{p['id']}", json={"archived": False}).json()["archived"] == 0
    client.patch(f"/api/projects/{p['id']}", json={"archived": True})
    assert client.delete(f"/api/projects/{p['id']}?delete_files=true").json() == {"ok": True}
    assert not folder.exists() and project_dir(keep["slug"]).exists()
    assert [x["title"] for x in client.get("/api/projects").json()] == ["Keep me"]


def test_running_jobs_can_be_found_again_after_leaving_the_page(temp_db):
    import threading

    from fastapi.testclient import TestClient

    from app import jobs
    from app.main import app

    release = threading.Event()
    j = jobs.start("research", 4242, lambda progress: release.wait(5))
    try:
        c = TestClient(app)
        assert [x["id"] for x in c.get("/api/jobs", params={"project_id": 4242, "kind": "research"}).json()] == [j["id"]]
        assert c.get("/api/jobs", params={"project_id": 4242, "kind": "voice"}).json() == []
        assert c.get("/api/jobs", params={"project_id": 9999}).json() == []
    finally:
        release.set()


def _words(text_at: list[tuple[str, float]]) -> list[dict]:
    """One word per (text, start) with a 0.3 s duration."""
    return [{"idx": n, "text": t, "start": s, "end": s + 0.3} for n, (t, s) in enumerate(text_at)]


class CutFake:
    def __init__(self, pick):
        self.pick, self.asks = pick, []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        self.asks.append(messages[-1]["content"])
        return {"sentence": self.pick}


def test_short_ends_on_the_cliffhanger_sentence_claude_picks_between_50_and_70_seconds():
    words = _words([("It", 0), ("began.", 1), ("Soldiers", 48), ("waited.", 49), ("Then", 55), ("silence.", 56),
                    ("Someone", 62), ("screamed.", 63), ("Answer", 71), ("given.", 72)])
    fake = CutFake(pick=2)
    assert shorts.choose_cut(fake, words, 50, 70) == pytest.approx(56.7)
    assert "2 (possible ending) [57s]: Then silence." in fake.asks[0]
    assert "(possible ending) [50s]" not in fake.asks[0] and "Answer given" not in fake.asks[0]
    assert shorts.choose_cut(CutFake(pick=1), words, 50, 70) == pytest.approx(56.7)  # not a possible ending


def test_short_cuts_at_the_longest_length_when_no_sentence_ends_in_the_window():
    words = _words([("A", 0), ("very", 40), ("long", 60), ("sentence.", 75)])
    assert shorts.choose_cut(CutFake(pick=0), words, 50, 70) == 70.0
    one = _words([("Hello.", 0), ("Then", 52), ("silence.", 53)])
    fake = CutFake(pick=0)
    assert shorts.choose_cut(fake, one, 50, 70) == pytest.approx(53.7) and not fake.asks  # one choice: no need to ask


def test_script_and_research_cover_who_what_when_where_and_why():
    assert "THE BASICS A NEWCOMER NEEDS (who, what, when, where and why)" in script.SCRIPT_SYSTEM
    assert "what he had done that made him wanted" in script.SCRIPT_SYSTEM
    assert "## Why it mattered" in script.RESEARCH_SECTIONS["story"]
    assert "- Why it mattered" in script.RESEARCH_SECTIONS["list"]


def test_script_prompt_follows_the_channel_style():
    s = script.SCRIPT_SYSTEM
    assert "CHANNEL STYLE" in s
    for idea in ("Put the viewer inside it", "Then vs now", "Name the belief, then break it", "Plant callbacks",
                 "So here's the full", "question for them to answer in the comments"):
        assert idea in s, idea
    assert "invite a subscribe" not in s  # the ending is a bookend or a question now, not a subscribe plea
    assert "CHANNEL STYLE" in script.REVISE_SYSTEM  # revisions keep the same style


def test_script_retells_clumsy_quotes_in_plain_words():
    from pipeline import script
    assert "two persons" in script.SCRIPT_SYSTEM and "one by one" in script.SCRIPT_SYSTEM
    assert "sound natural said aloud" in script.REVISE_SYSTEM or "sound natural said aloud" in script.SCRIPT_SYSTEM
