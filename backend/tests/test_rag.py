"""RAG research: source gathering, chunking, embeddings, the vector store, retrieval and the routes.
No network: Wikipedia, web pages and Gemini are faked with httpx.MockTransport; the vector database is
the in-memory MemoryStore."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from pipeline import chunking, embeddings, rag, sources
from pipeline import script as script_mod
from pipeline.vector_store import MemoryStore, rrf


def fake_embed(texts, task):
    """Deterministic bag-of-words vectors: texts sharing words point the same way."""
    out = []
    for t in texts:
        v = [0.0] * 512
        for w in t.lower().split():
            w = w.strip(".,:;!?()[]\"'")
            if len(w) > 2:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 512] += 1.0
        out.append(v)
    return out


class FakeClaude:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, system, messages, max_tokens=0, tools=None, effort=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def para(word, n):
    return " ".join(f"{word}{i} is a fact about the ships." for i in range(n))


# --- chunking ---------------------------------------------------------------

def test_chunks_respect_size_overlap_and_headings():
    text = "Intro sentence one. Intro sentence two.\n\n== Search ==\n" + para("Erebus", 80)
    chunks = chunking.chunk_text(text, chunk_words=100, overlap_words=20)
    assert len(chunks) > 3
    assert all(len(c["text"].split()) <= 110 for c in chunks)
    assert chunks[0]["heading"] == ""
    assert chunks[-1]["heading"] == "Search"
    # The next chunk begins with the end of the previous one.
    last_sentence = chunks[1]["text"].split(". ")[-1]
    assert last_sentence in chunks[2]["text"]
    assert "==" not in " ".join(c["text"] for c in chunks)


def test_short_text_is_one_chunk():
    chunks = chunking.chunk_text("Just one short paragraph. Two sentences.", 300, 50)
    assert [c["text"] for c in chunks] == ["Just one short paragraph. Two sentences."]


# --- picking and downloading sources ----------------------------------------

PICKS = """## Wikipedia
- Franklin's lost expedition
- HMS Erebus (1826)

## Other sources
1. [Franklin search - Parks Canada](https://parks.canada.ca/franklin?utm_source=x)
2. [Inuit testimony - Museum](https://museum.example.org/inuit/)
3. [Wiki link](https://en.wikipedia.org/wiki/John_Rae_(explorer))
"""


def test_parse_picks_and_normalize():
    wiki, other = sources.parse_picks(PICKS)
    assert wiki == ["Franklin's lost expedition", "HMS Erebus (1826)", "John Rae (explorer)"]
    assert [o["url"] for o in other] == ["https://parks.canada.ca/franklin?utm_source=x",
                                         "https://museum.example.org/inuit/"]
    assert sources.normalize_url("https://Museum.example.org/inuit/#top") == "https://museum.example.org/inuit"
    assert sources.normalize_url("https://a.org/p?utm_source=x&id=3") == "https://a.org/p?id=3"


def wiki_text(title):
    return f"{title} opening.\n\n== History ==\n{para('History', 70)}\n\n== References ==\nRef 1. Ref 2."


def make_transport(pages):
    def handler(req: httpx.Request):
        if req.url.host == "en.wikipedia.org":
            p = dict(req.url.params)
            if p.get("list") == "search":
                return httpx.Response(200, json={"query": {"search": [{"title": f"Extra {i}"} for i in range(10)]}})
            title = p["titles"]
            return httpx.Response(200, json={"query": {"pages": [{"title": title, "extract": wiki_text(title)}]}})
        url = str(req.url)
        if url in pages:
            status, body, ctype = pages[url]
            return httpx.Response(status, text=body, headers={"content-type": ctype})
        return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
    return httpx.MockTransport(handler)


ARTICLE = ("<html><head><title>Inuit testimony</title></head><body><nav>Menu</nav><article><h1>Inuit testimony</h1>"
           + "".join(f"<p>{para(f'Testimony{j}x', 8)}</p>" for j in range(12)) + "</article></body></html>")


def test_gather_downloads_wikipedia_and_pages():
    pages = {"https://museum.example.org/inuit/": (200, ARTICLE, "text/html; charset=utf-8"),
             "https://parks.canada.ca/franklin?utm_source=x": (200, "%PDF", "application/pdf")}
    client = httpx.Client(transport=make_transport(pages), follow_redirects=True)
    docs = sources.gather(FakeClaude(PICKS), {"title": "Franklin's ships"}, "story", docs_min=4, docs_max=15,
                          client=client)
    ok = [d for d in docs if d["status"] == "ok"]
    wiki = [d for d in ok if d["source_type"] == "wikipedia"]
    assert len(wiki) >= 3
    assert all("Ref 1" not in d["text"] for d in wiki)  # reference sections dropped
    assert wiki[0]["url"] == "https://en.wikipedia.org/wiki/Franklin's_lost_expedition"
    museum = next(d for d in docs if "museum" in d["url"])
    assert museum["status"] == "ok" and "Menu" not in museum["text"] and museum["words"] >= 300
    pdf = next(d for d in docs if "parks" in d["url"])
    assert pdf["status"] == "skipped" and "not a web page" in pdf["reason"]


def test_gather_skips_urls_the_project_already_has():
    client = httpx.Client(transport=make_transport({}), follow_redirects=True)
    docs = sources.gather(FakeClaude(PICKS), {"title": "T"}, "story", docs_min=1, docs_max=15,
                          exclude=["https://en.wikipedia.org/wiki/Franklin's_lost_expedition"], client=client)
    assert all("Franklin's_lost" not in d["url"] for d in docs)


def test_pick_sources_limits_searches():
    c = FakeClaude(PICKS)
    sources.pick_sources(c, {"title": "T"}, "story", exclude=["https://a.org"])
    assert c.calls[0]["tools"][0]["max_uses"] == 3
    assert "https://a.org" in c.calls[0]["messages"][0]["content"]


# --- embeddings -------------------------------------------------------------

@pytest.fixture
def clock(monkeypatch):
    """Fake clock: sleeping moves time forward instantly."""
    now = {"t": 1000.0, "slept": 0.0}

    def sleep(s):
        now["t"] += s
        now["slept"] += s
    monkeypatch.setattr(embeddings.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(embeddings.time, "sleep", sleep)
    monkeypatch.setattr(embeddings, "_sent", [])
    return now


def test_embed_batches_normalizes_and_retries(clock):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        body = json.loads(req.content)
        assert req.headers["x-goog-api-key"] == "k"
        assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
        return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]} for _ in body["requests"]]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    vecs = embeddings.embed(["a"] * 150, "k", "RETRIEVAL_QUERY", client=client)
    assert len(vecs) == 150 and vecs[0] == [0.6, 0.8]
    assert calls["n"] == 3  # one 429, then two batches (100 + 50)


def test_batches_stay_under_token_limit():
    big = "x" * 3000  # about 1,000 tokens each
    groups = embeddings.batches([big] * 50)
    assert [len(g) for g in groups] == [19, 19, 12]
    assert all(sum(map(embeddings.tokens, g)) <= embeddings.BATCH_TOKENS for g in groups)
    assert [len(g) for g in embeddings.batches(["a"] * 150)] == [100, 50]


def test_embed_waits_to_stay_under_tokens_per_minute(clock):
    sent = []

    def handler(req):
        sent.append(clock["t"])
        body = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [{"values": [1.0]} for _ in body["requests"]]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    embeddings.embed(["x" * 3000] * 50, "k", client=client)  # ~50K tokens, 3 batches
    assert len(sent) == 3
    assert sent[1] - sent[0] >= 60  # 19K + 19K would go over 24K a minute, so it waits
    assert sent[2] - sent[1] >= 60


def test_embed_needs_key():
    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed(["a"], "")


# --- vector store and retrieval ---------------------------------------------

def test_rrf_rewards_items_in_both_lists():
    assert rrf([1, 2, 3], [3, 4])[0] == 3


def doc(url, title, text):
    return {"url": url, "title": title, "source_type": "web", "text": text, "status": "ok", "words": 999}


def test_index_reuses_unchanged_documents_and_links_project():
    store = MemoryStore()
    calls = []

    def counting_embed(texts, task):
        calls.append(len(texts))
        return fake_embed(texts, task)

    d1 = doc("https://a.org/1", "Erebus", para("Erebus", 60))
    rag.index_documents(store, counting_embed, "owner:1", [d1, {**doc("https://x", "x", ""), "status": "skipped"}],
                        chunk_words=100, overlap_words=10)
    assert d1["doc_id"] and d1["chunks"] > 1 and d1["reused"] is False
    n_calls = len(calls)
    d1b = doc("https://a.org/1", "Erebus", para("Erebus", 60))
    rag.index_documents(store, counting_embed, "owner:2", [d1b], chunk_words=100, overlap_words=10)
    assert d1b["reused"] is True and len(calls) == n_calls  # no new embedding
    assert store.project_documents("owner:2") == [d1["doc_id"]]


def test_retrieve_round_robins_queries_and_adds_close_shared_matches():
    store = MemoryStore()
    mine = doc("https://a.org/ice", "Ice", "The ships were trapped in pack ice near King William Island for two winters.")
    other = doc("https://b.org/sled", "Sled", "Inuit hunters saw men dragging boats on sledges near King William Island.")
    unrelated = doc("https://c.org/rome", "Rome", "Roman legions marched along paved roads across the empire.")
    rag.index_documents(store, fake_embed, "owner:1", [mine], chunk_words=50, overlap_words=5)
    rag.index_documents(store, fake_embed, "owner:9", [other, unrelated], chunk_words=50, overlap_words=5)
    hits = rag.retrieve(store, fake_embed, "owner:1", ["pack ice ships", "Inuit hunters sledges King William Island"],
                        k=5, shared_min_similarity=0.3)
    urls = [h["url"] for h in hits]
    assert urls[0] == "https://a.org/ice"
    assert "https://b.org/sled" in urls and "https://c.org/rome" not in urls
    assert next(h for h in hits if h["url"] == "https://b.org/sled")["shared"] is True
    no_shared = rag.retrieve(store, fake_embed, "owner:1", ["Inuit hunters"], shared=False)
    assert {h["url"] for h in no_shared} == {"https://a.org/ice"}


def test_format_excerpts_numbers_sources_and_caps_words():
    chunks = [{"id": 1, "document_id": 7, "ord": 0, "heading": "Search", "text": "A " * 50, "url": "u7", "title": "T7"},
              {"id": 2, "document_id": 8, "ord": 0, "heading": "", "text": "B " * 50, "url": "u8", "title": "T8"},
              {"id": 3, "document_id": 7, "ord": 1, "heading": "", "text": "C " * 50, "url": "u7", "title": "T7"}]
    text = rag.format_excerpts(chunks)
    assert text.startswith("[1] T7 <u7>\n(Search) A") and "[2] T8 <u8>" in text
    assert "C C" in text
    assert "C C" not in rag.format_excerpts(chunks, max_words=100)


def test_write_brief_uses_excerpts_only_and_keeps_cited_sources():
    chunks = [{"id": 1, "document_id": 7, "ord": 0, "heading": "", "text": "Erebus found 2014.", "url": "https://a", "title": "A"},
              {"id": 2, "document_id": 8, "ord": 0, "heading": "", "text": "Terror found 2016.", "url": "https://b", "title": "B"}]
    c = FakeClaude("Intro chatter\n## Summary\nErebus was found in 2014 [1].\n## Sources\n1. [A](https://a)")
    brief, used = rag.write_brief(c, {"title": "Ships"}, "story", chunks, script_mod.RESEARCH_SYSTEM,
                                  script_mod.RESEARCH_SECTIONS["story"])
    assert brief.startswith("## Summary")
    assert used == [{"title": "A", "url": "https://a"}]
    call = c.calls[0]
    assert call["tools"] is None
    assert "Use only these excerpts" in call["system"] and "Prefer primary sources" not in call["system"]
    assert "## Uncertain or disputed" in call["system"]
    assert "[2] B <https://b>" in call["messages"][0]["content"]


def test_section_and_brief_queries():
    qs = rag.section_queries({"title": "Ships", "hook": "Lost"}, script_mod.RESEARCH_SECTIONS["story"])
    assert qs[0] == "Ships. Lost" and any("Timeline" in q for q in qs)
    brief = "## Summary\nx\n## Turning points\n- Ships trapped in ice [2]\n- Crew leave the ships\n## People\n- Rae"
    assert rag.brief_queries(brief, {"title": "Ships"}) == ["Ships: Ships trapped in ice", "Ships: Crew leave the ships"]
    listing = "## Entries\n### 1. Roswell (1947, New Mexico)\n- stuff\n### 2. Phoenix Lights"
    assert rag.brief_queries(listing, {"title": "UFOs"}) == ["UFOs: 1. Roswell (1947, New Mexico)", "UFOs: 2. Phoenix Lights"]


def test_script_and_revise_messages_carry_excerpts():
    msgs = script_mod.build_script_messages({"title": "T"}, "brief", (1550, 1650), excerpts="[1] Source <u>\nfact")
    assert "SOURCE EXCERPTS" in msgs[0]["content"] and "[1] Source <u>" in msgs[0]["content"]
    assert "SOURCE EXCERPTS" not in script_mod.build_script_messages({"title": "T"}, "brief", (1550, 1650))[0]["content"]

    class J:
        def json(self, system, messages, schema, effort=None):
            self.messages = messages
            return {"reply": "ok", "edits": []}
    j = J()
    script_mod.revise(j, "Script text.", [], "Add the year", excerpts="[1] A <u>\n1845")
    assert "SOURCE EXCERPTS" in j.messages[-1]["content"] and "1845" in j.messages[-1]["content"]


# --- routes -----------------------------------------------------------------

@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import storage
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_sources_routes_and_rag_research(client, temp_db, monkeypatch):
    from app import deps
    from app.routes import script as script_routes
    store = MemoryStore()
    monkeypatch.setattr(script_routes, "rag_ready", lambda: True)
    monkeypatch.setattr(script_routes, "vector_store", lambda: store)
    monkeypatch.setattr(script_routes, "embedder", lambda: fake_embed)
    monkeypatch.setattr(script_routes, "rag_config", lambda: {**deps.RAG_DEFAULTS, "docs_min": 2})
    brief = "## Summary\nThe ships were trapped in pack ice [1].\n## Sources\n1. [Ice](https://a.org/ice)"
    monkeypatch.setattr(script_routes, "claude", lambda: FakeClaude(brief))
    monkeypatch.setattr(script_mod, "check_sources", lambda s: s)
    fetched = [doc("https://a.org/ice", "Ice", para("The ships trapped in pack ice", 40)),
               doc("https://b.org/sled", "Sled", para("Inuit sledges", 40)),
               {**doc("https://c.org/x", "X", ""), "status": "skipped", "reason": "site answered 403", "words": 0}]
    monkeypatch.setattr(sources, "gather", lambda *a, **k: [dict(d) for d in fetched])

    pid = temp_db.create_project("Franklin")["id"]
    job = client.post(f"/api/projects/{pid}/research").json()
    from app import jobs
    import time
    for _ in range(100):
        if jobs.get(job["id"])["status"] != "running":
            break
        time.sleep(0.02)
    assert jobs.get(job["id"])["status"] == "done", jobs.get(job["id"])["error"]
    r = client.get(f"/api/projects/{pid}/research").json()
    assert r["content"].startswith("## Summary") and len(r["sources"]) == 1  # only the cited source

    listed = client.get(f"/api/projects/{pid}/sources").json()
    assert listed["rag"] is True
    assert [s["status"] for s in listed["sources"]] == ["ok", "ok", "skipped"]
    assert store.project_documents(f"owner:{pid}") and listed["sources"][0]["chunks"] > 0

    sid = listed["sources"][0]["id"]
    assert client.delete(f"/api/projects/{pid}/sources/{sid}").json() == {"ok": True}
    assert len(store.project_documents(f"owner:{pid}")) == 1
    assert len(client.get(f"/api/projects/{pid}/sources").json()["sources"]) == 2


def test_settings_show_rag_defaults_and_save_the_new_section(temp_db, tmp_path, monkeypatch):
    import shutil
    import yaml
    from fastapi.testclient import TestClient
    from app import config
    cfg = tmp_path / "config.yaml"  # never the real config.yaml
    shutil.copy(config.CONFIG_PATH, cfg)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config, "_cache", None)
    from app.main import app
    try:
        with TestClient(app) as c:
            s = c.get("/api/settings").json()
            assert s["config"]["rag"]["docs_min"] == 10
            assert "GEMINI_API_KEY" in s["keys"] and "SUPABASE_DB_URL" in s["keys"]
            assert "SITE_DATABASE_URL" in s["keys"]
            assert c.put("/api/settings/config", json={"rag": {"docs_max": 12}}).status_code == 200
            assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["rag"]["docs_max"] == 12
            assert c.put("/api/settings/config", json={"nonsense": {"a": 1}}).status_code == 200
            assert "nonsense" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))
    finally:
        config._cache = None


def test_rag_check_reports_missing_keys(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    r = client.post("/api/settings/rag-check").json()
    assert r["gemini"]["ok"] is False and "GEMINI_API_KEY" in r["gemini"]["message"]
    assert r["database"]["ok"] is False and "SUPABASE_DB_URL" in r["database"]["message"]


def test_rag_off_without_keys(client, temp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    pid = temp_db.create_project("No keys")["id"]
    assert client.get(f"/api/projects/{pid}/sources").json() == {"rag": False, "sources": []}
    assert client.post(f"/api/projects/{pid}/sources/more").status_code == 400
