"""Publishing a video to the public site's database: YouTube links, timed narration windows, and the routes.
The database is the in-memory MemoryStore; embeddings are faked."""
import time

import pytest

from pipeline import site_publish
from pipeline.vector_store import MemoryStore
from tests.test_rag import fake_embed


@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://vimeo.com/123", None),
    ("https://www.youtube.com/watch?v=short", None),
    ("", None),
])
def test_youtube_id(url, vid):
    assert site_publish.youtube_id(url) == vid


def timed_words(n_sentences=40, words_per=10, sec_per_word=0.35):
    """Sentences of `words_per` words; every sentence ends with a period."""
    out, t = [], 0.0
    for s in range(n_sentences):
        for i in range(words_per):
            text = f"s{s}w{i}" + ("." if i == words_per - 1 else "")
            out.append({"idx": len(out), "text": text, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += sec_per_word
    return out


def test_narration_chunks_are_30_to_45_s_and_end_on_sentences():
    words = timed_words()  # 40 sentences x 3.5 s = 140 s
    chunks = site_publish.narration_chunks(words)
    assert len(chunks) >= 3
    for c in chunks[:-1]:
        assert 30 <= c["end_s"] - c["start_s"] <= 45
        assert c["text"].endswith(".")
    assert chunks[0]["start_s"] == 0.0 and chunks[-1]["end_s"] == words[-1]["end"]
    assert [c["ord"] for c in chunks] == list(range(len(chunks)))
    # Every word is in exactly one window, in order.
    assert " ".join(c["text"] for c in chunks).split() == [w["text"] for w in words]


def test_short_tail_joins_the_previous_window():
    words = timed_words(n_sentences=10)  # 35 s -> one window + a 0-3.5 s tail
    chunks = site_publish.narration_chunks(words)
    assert len(chunks) == 1 and chunks[0]["end_s"] == words[-1]["end"]


def test_long_sentence_breaks_at_a_comma():
    words = [{"idx": i, "text": f"w{i}" + ("," if i == 150 else ""), "start": i * 0.35, "end": i * 0.35 + 0.3}
             for i in range(200)]
    chunks = site_publish.narration_chunks(words)
    assert chunks[0]["text"].endswith("w150,")


def test_default_summary_takes_the_first_paragraph():
    desc = "First paragraph here.\n\nSecond.\n\nChapters\n0:00 Start"
    assert site_publish.default_summary(desc) == "First paragraph here."
    long = "word " * 200
    s = site_publish.default_summary(long, 50)
    assert len(s) <= 53 and s.endswith("...")


def test_publish_replaces_the_video_and_its_windows():
    store = MemoryStore()
    video = site_publish.build_video({"youtube_url": "https://youtu.be/dQw4w9WgXcQ", "title": "Tape", "summary": ""},
                                     {"description": "A guard found tape.\n\nMore."}, 140.0)
    assert video["summary"] == "A guard found tape." and video["thumbnail_url"].endswith("/dQw4w9WgXcQ/hqdefault.jpg")
    vid, n = site_publish.publish(store, fake_embed, "owner:3", "owner", video, timed_words())
    assert n == len(store.video_chunks[vid]) and "embedding" in store.video_chunks[vid][0]
    vid2, _ = site_publish.publish(store, fake_embed, "owner:3", "owner", {**video, "title": "New"}, timed_words(20))
    assert vid2 == vid and store.videos[vid]["title"] == "New" and len(store.videos) == 1
    store.unpublish_video("owner:3")
    assert store.videos == {} and store.video_chunks == {}


def test_build_video_needs_a_link_and_title():
    with pytest.raises(ValueError, match="YouTube link"):
        site_publish.build_video({"youtube_url": "nope", "title": "T"}, None, 1)
    with pytest.raises(ValueError, match="title"):
        site_publish.build_video({"youtube_url": "dQw4w9WgXcQ", "title": " "}, None, 1)


# --- routes -----------------------------------------------------------------

@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    from app.main import app
    with TestClient(app) as c:
        yield c


def _wait(job_id):
    from app import jobs
    for _ in range(200):
        j = jobs.get(job_id)
        if j["status"] != "running":
            return j
        time.sleep(0.02)
    return jobs.get(job_id)


def test_site_routes_publish_update_and_unpublish(client, temp_db, monkeypatch):
    from app.routes import site as site_routes
    store = MemoryStore()
    monkeypatch.setattr(site_routes, "rag_ready", lambda: True)
    monkeypatch.setattr(site_routes, "vector_store", lambda: store)
    monkeypatch.setattr(site_routes, "embedder", lambda: fake_embed)

    p = temp_db.create_project("The Piece of Tape")
    pid = p["id"]
    v = temp_db.save_script(pid, "x", "generated")
    temp_db.save_publish_meta(pid, {"titles": ["Tape Title A", "B"], "description": "A guard found tape.\n\nMore."})
    temp_db.save_short(pid, youtube_url="https://youtu.be/dQw4w9WgXcQ")

    view = client.get(f"/api/projects/{pid}/site").json()
    assert view["title"] == "The Piece of Tape" and view["summary"] == "A guard found tape."
    assert view["youtube_url"] == "https://youtu.be/dQw4w9WgXcQ"  # filled in from the Short step
    assert view["title_options"] == ["Tape Title A", "B"] and view["published"] is False and view["has_voice"] is False

    body = {"youtube_url": "https://youtu.be/dQw4w9WgXcQ", "title": "Tape Title A", "summary": "Short."}
    r = client.post(f"/api/projects/{pid}/site/publish", json=body)
    assert r.status_code == 400 and "voice" in r.json()["detail"].lower()

    temp_db.save_voiceover(pid, v["id"], "a.mp3", 140.0, timed_words(), [])
    job = client.post(f"/api/projects/{pid}/site/publish", json=body).json()
    assert _wait(job["id"])["status"] == "done"
    view = client.get(f"/api/projects/{pid}/site").json()
    assert view["published"] is True and view["chunks"] >= 3 and view["stale"] is False
    assert temp_db.project_status(pid)["site"] is True  # the home page chip
    assert view["youtube_id"] == "dQw4w9WgXcQ" and view["summary"] == "Short."
    (video,) = store.videos.values()
    assert video["project_key"] == f"owner:{pid}" and video["duration_s"] == 140.0 and video["title"] == "Tape Title A"

    # Re-recording the voice makes the published timestamps stale.
    with temp_db.tx() as conn:
        conn.execute("UPDATE voiceovers SET created_at = datetime('now', '+1 minute') WHERE project_id = ?", (pid,))
    assert client.get(f"/api/projects/{pid}/site").json()["stale"] is True

    view = client.delete(f"/api/projects/{pid}/site/publish").json()
    assert view["published"] is False and store.videos == {}
    assert temp_db.project_status(pid)["site"] is False
    assert view["title"] == "Tape Title A"  # the saved fields stay for next time


def test_site_publish_needs_rag_keys(client, temp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    pid = temp_db.create_project("X")["id"]
    r = client.post(f"/api/projects/{pid}/site/publish", json={"youtube_url": "dQw4w9WgXcQ", "title": "X"})
    assert r.status_code == 400 and "Settings" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/site").json()["youtube_url"] == "dQw4w9WgXcQ"  # still saved
