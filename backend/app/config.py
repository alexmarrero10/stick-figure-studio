"""Loads config.yaml and .env from the repository root."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
PROJECTS_DIR = ROOT / "projects"
DB_PATH = DATA_DIR / "app.db"

load_dotenv(ENV_PATH)

_cache: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    global _cache
    if _cache is None:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _cache = yaml.safe_load(f) or {}
    return copy.deepcopy(_cache)


def save_config(cfg: dict[str, Any]) -> None:
    global _cache
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    _cache = copy.deepcopy(cfg)


def read_config_file() -> dict[str, Any]:
    """What is actually on disk, skipping the cache (to confirm a save stuck)."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_key(name: str) -> str | None:
    return os.environ.get(name) or None


def set_api_key(name: str, value: str) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), name, value)
    os.environ[name] = value
