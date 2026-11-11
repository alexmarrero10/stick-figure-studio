"""Step 1: video topic ideas, suggested by Claude or refined from the user's own idea."""
from __future__ import annotations

import re
from typing import Any

from pipeline.claude_client import STR, Claude, arr, obj

IDEA = obj({
    "title": STR,
    "hook": STR,
    "why_it_works": STR,
    "category": STR,
    "era": STR,
    "documentation": STR,
    "format": {"type": "string", "enum": ["story", "topic", "list"]},
})

SYSTEM = """You develop topics for a faceless YouTube channel that tells true stories and real \
historical or recent events as narrated stick-figure videos, 8-9 minutes long. The audience is 13-25 years old: they love stories that feel unbelievable but are true, high stakes, clever or outrageous people, and moments that make them say "wait, that actually happened?". Skip dry textbook topics unless there is a wild human story inside them.

A video can take one of three formats:
- story: one true story followed from start to finish (e.g. "The Inuit knew where Franklin's lost ships were").
- topic: a historical subject or question explained, told through real events, people and evidence \
(e.g. "Blitzkrieg in World War 2", "How did Aztec sacrifices actually work?", "Why humans fear \
humanoid figures").
- list: a countdown of 3-5 separate true cases that share a theme (e.g. "Top 5 Navy pilot UFO \
encounters", "Top 3 unexplained ship disappearances"). Every entry must be documented on its own.

A good topic:
- Is REAL and well documented (court records, reputable journalism, books, archives, academic work). Never invent events.
- Has a built-in mystery, reversal, or "how did this happen?" question a viewer must have answered.
- Has clear characters, stakes that escalate, and a satisfying payoff that can be told in ~1,400 words.
- Is visual in a simple way: it can be shown with stick figures, props and simple settings.
- Is advertiser-friendly: no graphic gore, sexual content, or glorifying violence; tragedy is told respectfully.
- Is not something every big channel has already covered to death, or has a fresh angle if it is.

Field guide:
- title: a curiosity-driven YouTube title, under 70 characters, no clickbait lies.
- hook: the first sentence the narrator would say. Starts in the middle of the story.
- why_it_works: one or two sentences on what keeps viewers watching.
- category: e.g. heist, scam, survival, disaster, espionage, science, business, mystery, crime, exploration.
- era: when it happened.
- documentation: how well sourced it is and where the facts come from, in one sentence.
- format: story, topic or list (see above). For a list, name the entries in `documentation`."""


TRENDS_SYSTEM = """You scout trends for a faceless YouTube channel that tells true history and true-story videos to viewers aged 13-25. Use web search to find out what history and true-story content is getting a lot of views RIGHT NOW (roughly the last 1-3 months):
- History and true-story YouTube videos and channels with unusually high recent views (long-form and Shorts), and the topics, eras and angles they cover.
- History topics going viral on TikTok, Instagram Reels, X and Reddit (e.g. r/history, r/todayilearned, r/AskHistorians, r/UnresolvedMysteries).
- Anniversaries, new films, series, games, documentaries or news that are pulling attention to a historical event or person.

Report in Markdown:
## Hot topics (8-15 bullets: the topic or event, where it is trending, and evidence such as view counts, upload dates or channel names)
## Formats and angles that are working (what the successful titles, hooks and framings have in common)
## Underserved angles (related true stories viewers would also want that few big channels have covered)

Only report what your searches actually show. Do not invent view counts."""


def trends(claude: Claude, theme: str = "") -> str:
    """Search the web for history / true-story topics doing well on social media right now."""
    msg = "Find what history and true-story topics are trending right now."
    if theme.strip():
        msg += f" Focus on this theme or category: {theme.strip()}"
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 10}]
    final = claude.complete(TRENDS_SYSTEM, [{"role": "user", "content": msg}], max_tokens=16000, tools=tools)
    text = claude.text_of(final).strip()
    i = text.find("## Hot topics")
    return text[i:] if i > 0 else text


def suggest(claude: Claude, count: int = 3, theme: str = "", avoid: list[str] | None = None,
            trend_notes: str = "") -> list[dict[str, Any]]:
    parts = [f"Suggest {count} video topics."]
    if theme.strip():
        parts.append(f"Focus on this theme or category: {theme.strip()}")
    if trend_notes:
        parts.append(
            "Here is fresh research on what history and true-story content is doing well on YouTube and "
            "social media right now. Base most ideas on these trending topics, or on closely related true "
            "stories that ride the same wave. In `why_it_works`, say what is trending and where.\n\n" + trend_notes
        )
    if avoid:
        parts.append("These topics are already used or suggested, so do not repeat them:\n- " + "\n- ".join(avoid[:150]))
    if count <= 4:
        parts.append("Use different categories and eras unless a theme was given. Make most of them single "
                     "stories; at most one can be a topic explainer or a countdown list.")
    else:
        parts.append("Mix categories and eras unless a theme was given, and mix the formats: mostly stories, "
                     "plus a few topic explainers and countdown lists.")
    result = claude.json(SYSTEM, [{"role": "user", "content": "\n\n".join(parts)}],
                         obj({"ideas": arr(IDEA)}), effort="medium")
    return result["ideas"]


def refine(claude: Claude, user_idea: str) -> dict[str, Any]:
    msg = (
        "The channel owner has their own idea. Turn it into one topic in the standard format. "
        "Keep their subject and their format (a single story, a topic explained, or a countdown list); "
        "sharpen the angle, title and hook. If the idea is not real and documented, say so plainly in "
        "`documentation`.\n\nTheir idea:\n" + user_idea.strip()
    )
    return claude.json(SYSTEM, [{"role": "user", "content": msg}], IDEA, effort="medium")


def guess_format(text: str) -> str:
    """Best guess at the format of a typed idea when Claude doesn't refine it."""
    t = text.lower()
    if re.search(r"\b(top|best|worst)\s+(\d+|three|five|ten)\b", t):
        return "list"
    if re.match(r"\s*(how|why|what)\b", t):
        return "topic"
    return "story"
