import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def temp_db(tmp_path):
    from app import db
    db.set_db_path(tmp_path / "test.db")
    db.migrate()
    yield db
    db.set_db_path(Path(__file__).resolve().parents[2] / "data" / "app.db")


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    """The API with its own database, projects folder, config.yaml copy and .env: never the real ones."""
    from fastapi.testclient import TestClient

    from app import config, storage
    from app.routes import projects as projects_route
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(projects_route, "PROJECTS_DIR", tmp_path / "projects")
    cfg = tmp_path / "config.yaml"
    shutil.copy(config.CONFIG_PATH, cfg)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(config, "_cache", None)
    from app.main import app
    with TestClient(app) as c:
        yield c
    config._cache = None
