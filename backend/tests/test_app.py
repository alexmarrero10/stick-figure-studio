"""App-wide: settings saves and dropdowns, the health check, and serving the UI."""

import pytest
import yaml

from tests.helpers import ROOT


def test_page_is_never_cached(client):
    from app import main
    if not main.DIST.exists():
        pytest.skip("UI not built")
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_settings_show_rag_defaults_and_save_the_new_section(client, tmp_path):
    cfg = tmp_path / "config.yaml"  # the client's copy, never the real config.yaml
    s = client.get("/api/settings").json()
    assert s["config"]["rag"]["docs_min"] == 10
    assert "GEMINI_API_KEY" in s["keys"] and "SUPABASE_DB_URL" in s["keys"]
    assert "SITE_DATABASE_URL" in s["keys"]
    assert client.put("/api/settings/config", json={"rag": {"docs_max": 12}}).status_code == 200
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["rag"]["docs_max"] == 12
    assert client.put("/api/settings/config", json={"nonsense": {"a": 1}}).status_code == 200
    assert "nonsense" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))


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
