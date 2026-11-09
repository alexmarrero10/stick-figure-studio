"""Vercel entry point. The site's FastAPI app lives in server/ (not api/: Vercel would turn every file in
an api/ folder into its own function). vercel.json runs this as the "server" service and sends
/api/... here; the pages are the separate "web" service."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "server"))

from app import app  # noqa: E402,F401
