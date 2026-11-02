"""Claude's visual sanity pass over beat boundaries. It may only merge or split beats, never change words."""
from __future__ import annotations

from typing import Any

from pipeline.claude_client import INT, STR, Claude, arr, obj

SYSTEM = """You storyboard narrated stick-figure videos. The narration has been cut into beats; \
each beat (0.5-3 seconds of speech, about 2-8 words) becomes ONE still illustration shown while those \
words are spoken. The pictures change quickly on purpose to keep viewers watching, so keep beats short.

Review the beat boundaries and propose only the changes that clearly help the pictures:
- merge: only when a beat cannot be illustrated on its own at all (e.g. "and then," or a dangling \
half-phrase) and belongs with the NEXT beat. Never create a beat longer than about 10 words.
- split: when a beat crams two different images together (e.g. a location change mid-beat). Give the \
global word index `at` that should start the new beat; it must be inside the beat and leave at least 2 \
words on each side.
Most beats are fine. Return an empty list if nothing needs to change. Do not rewrite any words."""

SCHEMA = obj({"ops": arr(obj({"op": {"type": "string", "enum": ["merge", "split"]}, "beat": INT, "at": INT, "reason": STR}))})


def review(claude: Claude, beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = [f"{b['idx']} [words {b['word_start']}-{b['word_end']}]: {b['text']}" for b in beats]
    msg = ("Beats (index [global word range]: text). For merge ops set `at` to -1.\n\n" + "\n".join(lines))
    ops = claude.json(SYSTEM, [{"role": "user", "content": msg}], SCHEMA, effort="medium")["ops"]
    for op in ops:
        if op["op"] == "merge":
            op.pop("at", None)
    return ops
