"""Projects: formats, archiving and deleting."""


def test_projects_store_their_format(client, temp_db):
    p = client.post("/api/projects", json={"title": "Top 5 UFO encounters", "format": "list"}).json()
    assert p["format"] == "list"
    assert client.patch(f"/api/projects/{p['id']}", json={"format": "topic"}).json()["format"] == "topic"
    assert client.patch(f"/api/projects/{p['id']}", json={"format": "nonsense"}).status_code == 400
    idea = temp_db.add_ideas([{"title": "How Blitzkrieg worked", "format": "topic"}])[0]
    assert idea["format"] == "topic"
    assert client.post(f"/api/ideas/{idea['id']}/use").json()["format"] == "topic"


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
