"""Ideas: Claude's suggestions, your own ideas, title rules and format guessing."""

from pipeline import ideas, publish


def test_guess_format():
    assert ideas.guess_format("Top 5 navy pilot UFO encounters") == "list"
    assert ideas.guess_format("top 3 unexplained ship disappearances") == "list"
    assert ideas.guess_format("How did ancient Aztec sacrifices work?") == "topic"
    assert ideas.guess_format("Why humans have a fear of humanoid figures") == "topic"
    assert ideas.guess_format("The D.B. Cooper hijacking") == "story"


def test_ideas_use_the_same_title_rules():
    from pipeline import ideas
    assert publish.TITLE_RULES in ideas.SYSTEM
    assert "never gives away the answer" in ideas.SYSTEM


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
