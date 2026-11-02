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
