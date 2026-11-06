"""Publish a finished video to the public site's database.

The site plays the video from YouTube, so what gets stored is the text around it: title, summary,
description, and the narration cut into 30-45 second windows, each with its start and end time.
Those windows are embedded so visitors can search by meaning and the chatbot can answer with
timestamps. The video's audio is the voiceover from second 0, so word times are video times.
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

EmbedFn = Callable[[list[str], str], list[list[float]]]

_SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")


def youtube_id(url: str) -> str | None:
    """The 11-character video id from any usual YouTube link (watch, youtu.be, shorts, embed, live)."""
    url = (url or "").strip()
    if re.fullmatch(r"[\w-]{11}", url):
        return url
    try:
        parts = urlsplit(url if "://" in url else "https://" + url)
    except ValueError:
        return None
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            vid = parse_qs(parts.query).get("v", [None])[0]
        else:
            m = re.match(r"/(?:shorts|embed|live|v)/([\w-]+)", parts.path)
            vid = m.group(1) if m else None
    return vid if vid and re.fullmatch(r"[\w-]{11}", vid) else None


def thumbnail_url(video_id: str) -> str:
    """YouTube's own thumbnail (the custom one once uploaded). hqdefault always exists."""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def narration_chunks(words: list[dict[str, Any]], min_s: float = 30, max_s: float = 45) -> list[dict[str, Any]]:
    """Group timed words into windows of about min_s-max_s seconds, ending on a sentence end when
    possible (or a comma, if a sentence runs past max_s)."""
    chunks: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if cur:
            chunks.append({"ord": len(chunks), "start_s": round(cur[0]["start"], 2),
                           "end_s": round(cur[-1]["end"], 2), "text": " ".join(w["text"] for w in cur)})
            cur.clear()

    for w in words:
        cur.append(w)
        length = w["end"] - cur[0]["start"]
        if length >= min_s and _SENTENCE_END.search(w["text"]):
            flush()
        elif length >= max_s and w["text"].endswith((",", ";", ":")):
            flush()
        elif length >= max_s + 15:  # a very long run with no punctuation at all
            flush()
    # A short tail joins the previous window rather than standing alone.
    if cur and chunks and cur[-1]["end"] - cur[0]["start"] < min_s / 3:
        last = chunks.pop()
        cur[:0] = [{"text": last["text"], "start": last["start_s"], "end": last["end_s"]}]
    flush()
    for i, c in enumerate(chunks):
        c["ord"] = i
    return chunks


def default_summary(description: str, max_chars: int = 300) -> str:
    """The first paragraph of the YouTube description (before chapters and sources)."""
    first = (description or "").strip().split("\n\n")[0].strip()
    if len(first) <= max_chars:
        return first
    cut = first[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def build_video(site: dict[str, Any], meta: dict[str, Any] | None, duration_s: float) -> dict[str, Any]:
    vid = youtube_id(site.get("youtube_url", ""))
    if not vid:
        raise ValueError("Add the video's YouTube link first (e.g. https://youtu.be/...).")
    description = (meta or {}).get("description", "")
    title = site.get("title", "").strip()
    if not title:
        raise ValueError("Add a title first.")
    return {"title": title, "summary": site.get("summary", "").strip() or default_summary(description),
            "description": description, "youtube_id": vid, "thumbnail_url": thumbnail_url(vid),
            "duration_s": round(duration_s, 2)}


def publish(store: Any, embed: EmbedFn, project_key: str, owner: str, video: dict[str, Any],
            words: list[dict[str, Any]]) -> tuple[int, int]:
    """Store (or replace) the video and its narration windows. Returns (video id, number of windows)."""
    if not words:
        raise ValueError("This video has no voiceover timings yet. Record the voice first.")
    chunks = narration_chunks(words)
    vecs = embed([f"{video['title']}\n{c['text']}" for c in chunks], "RETRIEVAL_DOCUMENT")
    for c, v in zip(chunks, vecs):
        c["embedding"] = v
    return store.publish_video(project_key, owner, video, chunks), len(chunks)
