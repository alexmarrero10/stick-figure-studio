"""Fact check: the same check with RAG (stored passages, no tools) or without (brief + web search)."""
import shutil

import pytest
from fastapi.testclient import TestClient

from pipeline import fact_check, rag
from pipeline.vector_store import MemoryStore
from tests.test_rag import doc, fake_embed

SCRIPT = ("The tank burst on January 15, 1919.\n\n"
          "A wave of molasses moved at 35 miles an hour. Twenty one people died.")


class FactFake:
    def __init__(self):
        self.calls: list[dict] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None, tools=None):
        self.calls.append({"system": system[0]["text"], "content": messages[-1]["content"], "tools": tools})
        return {"reply": "Checked 4 claims, 1 wrong.",
                "issues": [{"claim": "Twenty one people died.", "verdict": "wrong", "note": "21 died [1]"},
                           {"claim": "A wave of molasses moved at 35 miles an hour.", "verdict": "unsupported",
                            "note": "no source gives the speed"}],
                "edits": [{"find": "January 15, 1919", "replace": "January 15th, 1919", "reason": "date"},
                          {"find": "not in script", "replace": "x", "reason": "bad"}]}


def test_with_passages_uses_no_tools_and_says_not_to_use_memory():
    fake = FactFake()
    res = fact_check.check(fake, SCRIPT, "## Summary\nThe brief", passages="[1] Boston Globe\nText")
    call = fake.calls[0]
    assert call["tools"] is None and "SOURCE PASSAGES" in call["content"] and "own memory" in call["system"]
    assert [e["ok"] for e in res["edits"]] == [True, False]  # a find that isn't in the script is flagged


def test_without_rag_it_searches_the_web_and_can_skip_it():
    fake = FactFake()
    fact_check.check(fake, SCRIPT, "brief", max_searches=4)
    assert fake.calls[0]["tools"][0]["max_uses"] == 4 and "web search" in fake.calls[0]["system"]
    assert "SOURCE PASSAGES" not in fake.calls[0]["content"]
    fact_check.check(fake, SCRIPT, "brief", web_search=False)
    assert fake.calls[1]["tools"] is None and "BRIEF below. If it" in fake.calls[1]["system"]


def test_summary_lists_unconfirmed_claims():
    res = fact_check.check(FactFake(), SCRIPT, "brief")
    text = fact_check.summary(res)
    assert text.startswith("Checked 4 claims") and "35 miles an hour" in text and "Twenty one" not in text


def test_paragraph_queries_cover_the_whole_script():
    long = "\n\n".join(f"Paragraph {i} says one thing. And another thing." for i in range(50))
    qs = fact_check.paragraph_queries(long, limit=10)
    assert len(qs) == 10 and qs[0].startswith("Paragraph 0") and "Paragraph 45" in qs[-1]
    split = fact_check.paragraph_queries("A sentence here. " * 60, max_chars=100)
    assert all(len(q) <= 120 for q in split) and len(split) > 5


def test_fact_check_passages_come_from_the_project_sources():
    store = MemoryStore()
    mine = doc("https://a.org/m", "Molasses", "The molasses tank burst on January 15 1919 in the North End.")
    other = doc("https://b.org/r", "Rome", "Roman legions marched along paved roads.")
    rag.index_documents(store, fake_embed, "owner:1", [mine], chunk_words=50, overlap_words=5)
    rag.index_documents(store, fake_embed, "owner:2", [other], chunk_words=50, overlap_words=5)
    out = rag.fact_check_excerpts(store, fake_embed, "owner:1", SCRIPT)
    assert "North End" in out and "Roman" not in out


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from app import config, storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    cfg = tmp_path / "config.yaml"
    shutil.copy(config.CONFIG_PATH, cfg)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config, "_cache", None)
    from app.main import app
    with TestClient(app) as c:
        yield c
    config._cache = None


def test_route_puts_fixes_in_the_chat(client, temp_db, monkeypatch):
    p = temp_db.create_project("Molasses")
    temp_db.save_research(p["id"], "## Summary\nThe tank burst in 1919 [1].", [])
    temp_db.save_script(p["id"], SCRIPT, "generated")
    fake = FactFake()
    monkeypatch.setattr("app.routes.script.claude", lambda: fake)
    monkeypatch.setattr("app.routes.script.rag_ready", lambda: False)
    r = client.post(f"/api/projects/{p['id']}/script/factcheck").json()
    assert "The tank burst in 1919" in fake.calls[0]["content"] and fake.calls[0]["tools"]  # brief + web
    assert r["content"].startswith("Checked 4 claims") and r["edits"][0]["ok"]
    assert client.get(f"/api/projects/{p['id']}/script/chat").json()[-2]["content"] == "Check facts"
    assert client.post("/api/projects/999/script/factcheck").status_code == 404
