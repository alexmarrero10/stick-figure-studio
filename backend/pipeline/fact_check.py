"""Fact check: every checkable claim in the script is checked before it is recorded.

Two ways, same instructions and same output:
- with RAG: against the research brief plus the stored source passages that match each paragraph
  (one Claude call, no tools);
- without RAG: against the research brief, with Claude using web search for what the brief doesn't settle.

Wrong facts come back as find/replace edits the user accepts or rejects in the chat, like any other suggestion.
"""
from __future__ import annotations

import re
from typing import Any

from pipeline.claude_client import STR, Claude, arr, cached, obj
from pipeline.script import check_edit, to_ascii

SYSTEM = """You fact-check the narration script of a true-history YouTube video before it is recorded.
Check every checkable claim: names, dates, numbers, places, quotes, causes and events. {material}
- issues: only claims that are wrong or that nothing confirms. `claim` is the sentence copied from \
the script. `verdict` is "wrong" (the material says otherwise) or "unsupported" (nothing confirms it). \
`note` says what the material says, with its source number like [3] or the page you found. Skip claims \
that check out.
- edits: minimal find/replace fixes for the wrong claims. `find` must be copied EXACTLY from the script \
(same punctuation and spacing) and appear only once. `replace` keeps the script's style: plain ASCII, \
numbers written the way they are spoken, no em dashes, semicolons or ellipses. Give an unsupported claim \
an edit only when the fix is clear (for example softening it to "reportedly").
- reply: one or two sentences: roughly how many claims you checked and what you found."""

WITH_PASSAGES = ("Check them against the RESEARCH BRIEF and the SOURCE PASSAGES below. Don't rely on your own "
                 "memory: if neither confirms a claim, it is unsupported.")
WITH_WEB = ("Check them against the RESEARCH BRIEF below. Use web search to confirm the key claims the brief "
            "doesn't settle (dates, numbers, names, quotes), at most {n} searches. If nothing confirms a "
            "claim, it is unsupported.")
BRIEF_ONLY = "Check them against the RESEARCH BRIEF below. If it doesn't confirm a claim, it is unsupported."

SCHEMA = obj({
    "reply": STR,
    "issues": arr(obj({"claim": STR, "verdict": STR, "note": STR})),
    "edits": arr(obj({"find": STR, "replace": STR, "reason": STR})),
})


def paragraph_queries(script: str, limit: int = 20, max_chars: int = 400) -> list[str]:
    """One search question per paragraph (long paragraphs are split), so every part of the script
    gets the passages that match it."""
    parts: list[str] = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()):
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if cur and len(cur) + len(sent) > max_chars:
                parts.append(cur)
                cur = ""
            cur = f"{cur} {sent}".strip()
        if cur:
            parts.append(cur)
    if len(parts) > limit:  # spread the questions over the whole script
        step = len(parts) / limit
        parts = [parts[int(i * step)] for i in range(limit)]
    return parts


def check(claude: Claude, script: str, brief: str, passages: str = "", web_search: bool = True,
          max_searches: int = 6) -> dict[str, Any]:
    if passages.strip():
        material, tools = WITH_PASSAGES, None
    elif web_search:
        material = WITH_WEB.format(n=max_searches)
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
    else:
        material, tools = BRIEF_ONLY, None
    content = f"SCRIPT\n<script>\n{script}\n</script>\n\nRESEARCH BRIEF\n{brief.strip() or '(none)'}"
    if passages.strip():
        content += f"\n\nSOURCE PASSAGES\n{passages.strip()}"
    result = claude.json(cached(SYSTEM.format(material=material)), [{"role": "user", "content": content}],
                         SCHEMA, effort="medium", tools=tools)
    result["edits"] = [check_edit(script, {**e, "replace": to_ascii(e["replace"])}) for e in result["edits"]]
    result["issues"] = [i for i in result.get("issues", []) if i.get("claim", "").strip()]
    return result


def summary(result: dict[str, Any]) -> str:
    """The chat message: Claude's reply plus the claims it couldn't confirm (those have no edit)."""
    text = result["reply"].strip()
    unsupported = [i for i in result["issues"] if i.get("verdict") != "wrong"]
    if unsupported:
        text += "\n\nCouldn't confirm:\n" + "\n".join(f"- {i['claim']} ({i['note']})" for i in unsupported[:8])
    return text
