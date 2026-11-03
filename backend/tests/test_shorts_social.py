"""General tags, video formats and sources, eye-catching openings, the vertical Short, posting to the
four apps (against fake APIs: nothing is ever posted), and archiving projects."""
import json
import subprocess
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from pipeline import ffmpeg, ideas, prompts, publish, script, shorts
from pipeline.social import SocialError, meta, tiktok, youtube
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


@pytest.fixture
def env(monkeypatch):
    """A fake .env for the social routes, so tests never touch the real one."""
    store: dict[str, str] = {}
    from app.routes import social
    monkeypatch.setattr(social, "get_key", lambda k: store.get(k) or None)
    monkeypatch.setattr(social, "set_api_key", lambda k, v: store.__setitem__(k, v))
    return store


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


def test_platform_text_has_the_link_everywhere():
    s = {"title": "They vanished in the ice", "caption": "129 men. Zero survivors.", "hashtags": ["history", "arctic"],
         "youtube_url": "https://youtu.be/abc"}
    yt = shorts.platform_text(s, "youtube")
    assert yt["title"] == "They vanished in the ice #Shorts"
    assert "Watch the full video: https://youtu.be/abc" in yt["text"] and "#Shorts #history #arctic" in yt["text"]
    for pl in ("instagram", "facebook", "tiktok"):
        t = shorts.platform_text(s, pl)["text"]
        assert "Full video on YouTube: https://youtu.be/abc" in t and "#history" in t


def test_hashtags_are_cleaned():
    assert shorts.clean_hashtags(["#History", "history", "true story", "#UFO!"]) == ["History", "truestory", "UFO"]


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
        assert left.getextrema()[0] < 80 and right.getextrema()[0] > 200
        assert f.getpixel((540, 40)) == (247, 244, 236)  # the rest is background


# --- 4b. posting, against fake APIs ------------------------------------------------

class FakeApi:
    """Answers requests from a list of (method, url substring, response) rules and records every call."""

    def __init__(self, rules):
        self.rules = rules
        self.calls: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        for method, part, resp in self.rules:
            if req.method == method and part in str(req.url):
                return resp(req) if callable(resp) else resp
        return httpx.Response(500, json={"error": {"message": f"unexpected {req.method} {req.url}"}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "short.mp4"
    p.write_bytes(b"\x00" * 1000)
    return p


def test_youtube_upload(video):
    api = FakeApi([
        ("POST", "upload/youtube/v3/videos", httpx.Response(200, headers={"location": "https://upload.example/session1"})),
        ("PUT", "upload.example/session1", httpx.Response(200, json={"id": "vid123"})),
    ])
    res = youtube.upload(api.client(), "tok", video, "Title #Shorts", "desc", ["history"], "public")
    assert res == {"post_id": "vid123", "url": "https://www.youtube.com/shorts/vid123"}
    start = json.loads(api.calls[0].content)
    assert start["snippet"]["title"] == "Title #Shorts" and start["status"]["privacyStatus"] == "public"
    assert api.calls[0].headers["authorization"] == "Bearer tok"
    assert len(api.calls[1].content) == 1000


def test_youtube_expired_login_says_reconnect():
    api = FakeApi([("POST", "oauth2.googleapis.com/token", httpx.Response(400, json={"error": "invalid_grant"}))])
    with pytest.raises(SocialError, match="Connect YouTube again"):
        youtube.access_token(api.client(), "id", "secret", "refresh")


def test_instagram_reel(video):
    polls = iter(["IN_PROGRESS", "FINISHED"])
    api = FakeApi([
        ("POST", "/ig1/media_publish", httpx.Response(200, json={"id": "media9"})),
        ("POST", "/ig1/media", httpx.Response(200, json={"id": "box1", "uri": "https://rupload.facebook.com/ig-api-upload/v24.0/box1"})),
        ("POST", "rupload.facebook.com/ig-api-upload", httpx.Response(200, json={"success": True})),
        ("GET", "/box1", lambda r: httpx.Response(200, json={"status_code": next(polls)})),
        ("GET", "/media9", httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/xyz/"})),
    ])
    res = meta.post_instagram(api.client(), "v24.0", "ig1", "ptok", video, "caption", sleep=lambda s: None)
    assert res == {"post_id": "media9", "url": "https://www.instagram.com/reel/xyz/"}
    create = parse_qs(api.calls[0].content.decode())
    assert create["media_type"] == ["REELS"] and create["upload_type"] == ["resumable"]
    up = api.calls[1]
    assert up.headers["authorization"] == "OAuth ptok" and up.headers["file_size"] == "1000" and up.headers["offset"] == "0"


def test_instagram_processing_error(video):
    api = FakeApi([
        ("POST", "/ig1/media", httpx.Response(200, json={"id": "box1"})),
        ("POST", "rupload.facebook.com", httpx.Response(200, json={"success": True})),
        ("GET", "/box1", httpx.Response(200, json={"status_code": "ERROR", "status": "Video too short"})),
    ])
    with pytest.raises(SocialError, match="Video too short"):
        meta.post_instagram(api.client(), "v24.0", "ig1", "ptok", video, "c", sleep=lambda s: None)


def test_facebook_reel(video):
    api = FakeApi([
        ("POST", "/page1/video_reels", lambda r: httpx.Response(200, json=(
            {"video_id": "v77", "upload_url": "https://rupload.facebook.com/video-upload/v24.0/v77"}
            if b"upload_phase=start" in r.content else {"success": True}))),
        ("POST", "rupload.facebook.com/video-upload", httpx.Response(200, json={"success": True})),
        ("GET", "/v77", httpx.Response(200, json={"status": {"video_status": "ready"}})),
    ])
    res = meta.post_facebook(api.client(), "v24.0", "page1", "ptok", video, "desc", sleep=lambda s: None)
    assert res == {"post_id": "v77", "url": "https://www.facebook.com/reel/v77"}
    finish = parse_qs(api.calls[2].content.decode())
    assert finish["upload_phase"] == ["finish"] and finish["video_state"] == ["PUBLISHED"] and finish["description"] == ["desc"]


def test_meta_connect_finds_page_and_instagram():
    api = FakeApi([
        ("GET", "fb_exchange_token", httpx.Response(200, json={"access_token": "long"})),
        ("GET", "oauth/access_token", httpx.Response(200, json={"access_token": "short"})),
        ("GET", "me/accounts", httpx.Response(200, json={"data": [
            {"id": "p1", "name": "Other page", "access_token": "t1"},
            {"id": "p2", "name": "History Page", "access_token": "t2",
             "instagram_business_account": {"id": "ig2", "username": "historyig"}}]})),
    ])
    acct = meta.connect(api.client(), "app", "secret", "code", "http://localhost:8765/cb", "v24.0")
    assert acct["page_id"] == "p2" and acct["page_token"] == "t2" and acct["ig_username"] == "historyig"


def test_tiktok_post(video):
    polls = iter([{"status": "PROCESSING_UPLOAD"}, {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [555]}])
    ok = {"error": {"code": "ok"}}
    api = FakeApi([
        ("POST", "creator_info/query", httpx.Response(200, json={**ok, "data": {
            "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"], "creator_username": "histtok"}})),
        ("POST", "video/init", httpx.Response(200, json={**ok, "data": {"publish_id": "pub1", "upload_url": "https://up.tiktok/x"}})),
        ("PUT", "up.tiktok/x", httpx.Response(201)),
        ("POST", "status/fetch", lambda r: httpx.Response(200, json={**ok, "data": next(polls)})),
    ])
    res = tiktok.post(api.client(), "tok", video, "caption", sleep=lambda s: None)
    assert res == {"post_id": "555", "url": "https://www.tiktok.com/@histtok/video/555"}
    init = json.loads(api.calls[1].content)
    assert init["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000, "total_chunk_count": 1}
    assert api.calls[2].headers["content-range"] == "bytes 0-999/1000"


def test_tiktok_refuses_a_privacy_the_account_cant_use(video):
    api = FakeApi([("POST", "creator_info/query", httpx.Response(200, json={
        "error": {"code": "ok"}, "data": {"privacy_level_options": ["SELF_ONLY"]}}))])
    with pytest.raises(SocialError, match="allowed: SELF_ONLY"):
        tiktok.post(api.client(), "tok", video, "c", "PUBLIC_TO_EVERYONE", sleep=lambda s: None)


def test_tiktok_api_error_is_readable(video):
    api = FakeApi([("POST", "creator_info/query", httpx.Response(401, json={
        "error": {"code": "access_token_invalid", "message": "The access token is invalid"}}))])
    with pytest.raises(SocialError, match="access token is invalid"):
        tiktok.post(api.client(), "tok", video, "c", sleep=lambda s: None)


# --- 4c. connect + publish routes -----------------------------------------------------

def test_connect_redirects_to_the_platform_login(client, env):
    assert client.get("/api/social/youtube/connect", follow_redirects=False).status_code == 400
    env.update(YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="sec")
    r = client.get("/api/social/youtube/connect", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.headers["location"].startswith("https://accounts.google.com/")
    assert q["redirect_uri"] == ["http://localhost:8765/api/social/youtube/callback"]
    assert q["access_type"] == ["offline"] and q["code_challenge_method"] == ["S256"]
    # A callback with a made-up state is refused and stores nothing.
    bad = client.get("/api/social/youtube/callback?state=forged&code=x")
    assert bad.status_code == 400 and "expired" in bad.text and "YOUTUBE_REFRESH_TOKEN" not in env


def test_callback_stores_the_login(client, env, monkeypatch):
    env.update(TIKTOK_CLIENT_KEY="ck", TIKTOK_CLIENT_SECRET="cs")
    r = client.get("/api/social/tiktok/connect", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    monkeypatch.setattr(tiktok, "exchange_code", lambda *a: {"access_token": "at", "refresh_token": "rt"})
    monkeypatch.setattr(tiktok, "user", lambda c, t: {"name": "History Tok"})
    page = client.get(f"/api/social/tiktok/callback?state={state}&code=abc")
    assert page.status_code == 200 and "History Tok" in page.text
    assert env["TIKTOK_REFRESH_TOKEN"] == "rt"
    st = client.get("/api/social").json()
    assert st["platforms"]["tiktok"] and st["tiktok"]["account"] == "History Tok"
    assert "rt" not in json.dumps(st) and "cs" not in json.dumps(st)  # secrets never go to the page
    client.post("/api/social/tiktok/disconnect")
    assert not client.get("/api/social").json()["platforms"]["tiktok"]


def _project_with_short(temp_db, tmp_path):
    from app.storage import output_dir
    p = temp_db.create_project("Franklin")
    (output_dir(p["slug"]) / "short.mp4").write_bytes(b"\x00" * 10)
    temp_db.save_short(p["id"], title="They vanished", caption="129 men.", hashtags=["history"],
                       rendered_at="2026-10-29 10:00:00", duration_s=59.0)
    return p


def _wait(client, job):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    return job


def test_publish_posts_everywhere_and_one_failure_doesnt_stop_the_rest(client, temp_db, tmp_path, monkeypatch):
    from app.routes import social
    p = _project_with_short(temp_db, tmp_path)
    monkeypatch.setattr(social, "connected", lambda pl: True)
    sent = []

    def fake_post(c, platform, path, title, text, tags=None):
        sent.append((platform, title, text))
        if platform == "facebook":
            raise SocialError("Facebook said no")
        return {"post_id": f"{platform}-1", "url": f"https://{platform}.example/1"}

    monkeypatch.setattr(social, "post_video", fake_post)
    body = {"platforms": ["youtube", "instagram", "facebook", "tiktok"]}
    r = client.post(f"/api/projects/{p['id']}/short/publish", json=body)
    assert r.status_code == 400 and "YouTube link" in r.json()["detail"]
    assert client.put(f"/api/projects/{p['id']}/short", json={"youtube_url": "not a link"}).status_code == 400
    client.put(f"/api/projects/{p['id']}/short", json={"youtube_url": "https://youtu.be/full1"})

    job = _wait(client, client.post(f"/api/projects/{p['id']}/short/publish", json=body).json())
    assert job["status"] == "done"
    assert [r["status"] for r in job["result"]] == ["posted", "posted", "error", "posted"]
    assert [s[0] for s in sent] == ["youtube", "instagram", "facebook", "tiktok"]
    assert sent[0][1] == "They vanished #Shorts" and "https://youtu.be/full1" in sent[0][2]
    assert all("https://youtu.be/full1" in s[2] for s in sent)
    assert temp_db.project_status(p["id"])["short_posts"] == 3

    # Pressing publish again only retries the app that failed.
    sent.clear()
    job = _wait(client, client.post(f"/api/projects/{p['id']}/short/publish", json=body).json())
    assert [s[0] for s in sent] == ["facebook"]
    assert [r["status"] for r in job["result"]] == ["skipped", "skipped", "error", "skipped"]


def test_publish_needs_connected_accounts(client, temp_db, tmp_path, env):
    p = _project_with_short(temp_db, tmp_path)
    client.put(f"/api/projects/{p['id']}/short", json={"youtube_url": "https://youtu.be/full1"})
    r = client.post(f"/api/projects/{p['id']}/short/publish", json={"platforms": ["youtube", "tiktok"]})
    assert r.status_code == 400 and "Connect Youtube, Tiktok" in r.json()["detail"]


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
