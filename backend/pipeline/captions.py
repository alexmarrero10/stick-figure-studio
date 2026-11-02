"""SRT captions from word timings."""
from __future__ import annotations

from typing import Any

from pipeline.scenes import ends_sentence, soft_break


def _ts(t: float) -> str:
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[dict[str, Any]], max_words: int = 7, max_seconds: float = 2.5) -> str:
    cues: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        cur.append(w)
        long = len(cur) >= max_words or w["end"] - cur[0]["start"] >= max_seconds
        if ends_sentence(w["text"]) or long or (soft_break(w["text"]) and len(cur) >= 3):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    lines = []
    for n, cue in enumerate(cues, 1):
        end = cue[-1]["end"]
        if n < len(cues):
            end = min(end + 0.25, cues[n][0]["start"])  # linger briefly, never overlap
        lines.append(f"{n}\n{_ts(cue[0]['start'])} --> {_ts(end)}\n{' '.join(w['text'] for w in cue)}\n")
    return "\n".join(lines)
