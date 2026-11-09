"""Vercel entry point. The site's FastAPI app lives in server/ (not api/: Vercel would turn every file in
an api/ folder into its own function). Vercel serves the built pages from public/ on its CDN and sends
everything else (/api/...) to this app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "server"))

from app import app  # noqa: E402,F401
