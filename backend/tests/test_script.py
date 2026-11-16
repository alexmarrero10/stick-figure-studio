"""Script: research, the script and its style rules, sources, and the grammar check."""
from types import SimpleNamespace

import httpx

from pipeline import script
from pipeline import script as script_mod


class RecordingClaude:
    def __init__(self, text="## Summary\nStuff [1]\n\n## Sources\n1. [Navy report - US Navy](https://navy.mil/r)"):
        self.text = text
        self.calls = []

    def complete(self, system, messages, max_tokens=0, tools=None, effort=None):
        self.calls.append((system, messages[-1]["content"]))
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


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


def test_script_opening_is_written_to_work_as_a_short():
    assert "posted on its own as a" in script.SCRIPT_SYSTEM and "cliffhanger" in script.SCRIPT_SYSTEM
    assert "stop a thumb mid-scroll" in script.SCRIPT_SYSTEM


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


def test_script_opening_keeps_the_answer_back_and_skips_detours():
    s = script.SCRIPT_SYSTEM
    assert "NEVER REVEAL THE ANSWER IN THE OPENING" in s
    assert "RIGHT AFTER THE OPENING" in s and "No detours" in s
    assert "but before we get to" in s  # banned phrase
    assert "NEVER REVEAL THE ANSWER IN THE OPENING" in script.REVISE_SYSTEM
    assert "not at anyone's birth" in script.FORMAT_RULES["story"]


def test_script_opening_is_clear_to_a_stranger_and_never_copies_examples():
    s = script.SCRIPT_SYSTEM
    for rule in ("CLEAR FROM THE FIRST WORD", "Never use he, she, they, his or her before saying who",
                 "ONE TIMELINE IN THE OPENING", "Tell each scene once",
                 "EXAMPLES IN THESE INSTRUCTIONS SHOW THE IDEA ONLY", "READ THE OPENING", "not \"in the world\""):
        assert rule in s, rule
    assert "CLEAR FROM THE FIRST WORD" in script.REVISE_SYSTEM


def test_script_retells_clumsy_quotes_in_plain_words():
    from pipeline import script
    assert "two persons" in script.SCRIPT_SYSTEM and "one by one" in script.SCRIPT_SYSTEM
    assert "sound natural said aloud" in script.REVISE_SYSTEM or "sound natural said aloud" in script.SCRIPT_SYSTEM


def test_edited_passages_finds_only_changed_sentences():
    before = "Saddam ran Iraq for decades. He hid near Tikrit. The soldiers searched the farm."
    after = "Saddam ran Iraq for decades. He hided near Tikrit in a hole. The soldiers searched the farm."
    assert script_mod.edited_passages(before, after) == ["He hided near Tikrit in a hole."]
    assert script_mod.edited_passages(after, after) == []


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
