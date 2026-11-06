"""The app's version, read from the VERSION file at the repo root (one place to change it)."""
from app.config import ROOT

VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
