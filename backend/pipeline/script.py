"""Step 2: research brief, script generation and chat-based revisions."""
from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import httpx

from pipeline.claude_client import STR, Claude, arr, cached, obj

# --- research ---------------------------------------------------------------

RESEARCH_SYSTEM = """You are the researcher for a true-story and history YouTube channel. Before a \
script is written, you produce a fact sheet the writer can rely on. Accuracy matters more than \
drama: the channel's credibility and monetization depend on not spreading false claims.

SOURCES
- Prefer primary sources, museums and archives, academic and university pages, government \
records, reputable newspapers and established history publications. An encyclopedia can point you \
to sources but should not be the only source for a fact.
{depth}
- List every source you used under ## Sources as a numbered Markdown link with its real URL: \
1. [Title of the page - Publisher](https://...). Never make up or guess a URL.

Write the brief in Markdown. Use the sections for the video's format, then always end with:
## Uncertain or disputed (claims that are legends, contested, or poorly sourced; say what is known vs. rumored)
## Things to avoid (sensitive details, living private individuals, anything that would breach YouTube ad guidelines)
## Sources

Never present a rumor as fact. If you are unsure of a detail, put it under "Uncertain"."""

# How hard research works. Quick leans on what Claude already knows and only searches to check it.
RESEARCH_DEPTH = {
    "quick": """- Work fast. Start from what you already know about the subject, then run 2-4 web searches \
to confirm the key facts (dates, numbers, names, quotes) and find 4-6 good sources. Search results \
usually hold enough to confirm a detail; open a page only when they don't, and open no more than 3.
- Mark facts with the number of the source that confirms them, like [3]. A key fact (date, number, \
quote) that no search confirmed goes under "Uncertain or disputed", not in the main sections.
- Keep the source list short: only the 4-8 best sources the brief actually cites.""",
    "thorough": """- Use web search and open the pages you rely on. Run about 5-8 searches and open about \
8-12 of the most useful pages, then write the brief.
- Mark every fact in the brief with the number of its source, like [3]. A fact with no source you \
actually read does not go in the brief.""",
}

RESEARCH_SECTIONS = {
    "story": """FORMAT: one true story, told start to finish.
## Summary (3-4 sentences)
## Why it mattered (the background a newcomer needs: who the main people were, what they had done or \
were trying to do, what was at stake and why anyone cared; e.g. for a manhunt, what the hunted person \
had done that made them wanted)
## Timeline (dated bullet points, in order)
## People (name, role, one memorable concrete detail each)
## Key facts and numbers (the specific details that make the story vivid: amounts, distances, objects, places)
## Turning points (the 4-6 moments where the story changes direction; these become the script's beats)""",
    "topic": """FORMAT: a historical topic or question explained, not a single story.
## Summary (3-4 sentences answering the central question)
## The central question (what the viewer wants to know, and the short true answer)
## Background (where, when and why it started)
## How it worked (the mechanics, step by step, with concrete examples)
## Real cases and people (3-5 documented events or people that show the topic in action, each with a vivid detail and date)
## Key facts and numbers
## Myths vs. evidence (popular beliefs about the topic and what the evidence actually shows)
## Turning points (the 4-6 ideas or events the explanation builds through; these become the script's beats)""",
    "list": """FORMAT: a countdown of several separate true cases that share a theme.
## Summary (the theme, and why these cases were chosen)
## Entries (3-5 cases; research each one on its own with its own sources. For each entry:
### N. Name of the case (date, place)
- What happened (4-8 bullets in order)
- Why it mattered (who was involved, what was at stake and why anyone cared)
- People involved (roles, one concrete detail each)
- The strongest evidence and the official or best-supported explanation
- What remains unexplained or disputed)
## Ranking (the order from the least to the most remarkable, and why; the strongest case comes last)""",
}


def research(claude: Claude, idea: dict[str, Any], web_search: bool = True,
             format: str = "story", depth: str = "quick") -> tuple[str, list[dict[str, str]]]:
    msg = (
        f"Research this for a narrated video.\n\nTitle: {idea.get('title', '')}\n"
        f"Hook: {idea.get('hook', '')}\nNotes: {idea.get('documentation', '')}\n\n"
        f"{RESEARCH_SECTIONS.get(format, RESEARCH_SECTIONS['story'])}"
    )
    quick = depth != "thorough"
    system = RESEARCH_SYSTEM.replace("{depth}", RESEARCH_DEPTH["quick" if quick else "thorough"])
    tools = ([{"type": "web_search_20260209", "name": "web_search", "max_uses": 4 if quick else 8}]
             if web_search else None)
    # Lower effort than the rest of the app: xhigh spends ages on extra searches and page reads.
    final = claude.complete(system, [{"role": "user", "content": msg}], max_tokens=32000, tools=tools,
                            effort="medium" if quick else "high")
    sources: dict[str, str] = {}
    for block in final.content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                url = getattr(r, "url", None)
                if url and url not in sources:
                    sources[url] = getattr(r, "title", url) or url
    # Only the final text blocks after the last tool result form the brief.
    text = Claude.text_of(final).strip()
    i = text.find("## Summary")
    if i > 0:
        text = text[i:]
    # The sources the brief cites come first: they are the ones the facts were checked against.
    cited = sources_from_text(text)
    merged = {**cited, **{u: t for u, t in sources.items() if u not in cited}}
    return text, [{"title": t, "url": u} for u, t in merged.items()]


def sources_from_text(text: str) -> dict[str, str]:
    """Pull links out of the brief (used when search results aren't available as structured blocks)."""
    found: dict[str, str] = {}
    for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        found.setdefault(url, title)
    for url in re.findall(r"(?<!\()https?://[^\s)>\]]+", text):
        found.setdefault(url.rstrip(".,;"), url.rstrip(".,;"))
    return found


def check_sources(sources: list[dict[str, str]], client: httpx.Client | None = None) -> list[dict[str, str]]:
    """Drop links that don't exist (404/410 or no such site), so the description never cites a dead or
    made-up page. Sites that block automated checks (403, 429, timeouts) are kept."""
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=True,
                                    headers={"User-Agent": "Mozilla/5.0 (source check)"})

    def alive(url: str) -> bool:
        try:
            r = client.head(url)
            if r.status_code in (405, 501):  # HEAD not allowed: ask for the page instead
                r = client.get(url)
            return r.status_code not in (404, 410)
        except httpx.ConnectError:
            return False
        except httpx.HTTPError:
            return True

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            ok = list(pool.map(lambda s: alive(s["url"]), sources))
    finally:
        if own:
            client.close()
    return [s for s, good in zip(sources, ok) if good]


# --- script -----------------------------------------------------------------

SCRIPT_SYSTEM = """You write narration scripts for a faceless YouTube channel that tells true \
stories and explains real history as stick-figure animations. A video is one story, a topic \
explained, or a countdown of several true cases (the format is given with each request). A single narrator (an American male voice) reads your script \
word for word with an AI voice, and every 1-3 seconds of narration gets its own simple illustration.

OUTPUT FORMAT
- Output ONLY the words the narrator will speak. No title, headings, scene directions, speaker labels, \
timestamps, brackets, emojis or Markdown.
- Separate paragraphs with a blank line. One paragraph = one movement of the story (40-120 words).
- Write numbers, dates and units the way they should be spoken when it could be ambiguous \
("nineteen sixty-three", "two point four million dollars") so the voice reads them naturally.
- Plain ASCII characters only: straight quotes (' and "), no curly quotes, dashes, ellipsis \
characters, accented letters (write "Jose", not "José") or symbols like £, € or °. Spell those out \
in words ("pounds", "degrees").

NAMES THE VOICE CAN SAY
- The AI voice stumbles on rare, foreign or hard-to-pronounce names, and viewers forget them anyway.
- Name only the few people the story really follows (usually 2-4). Everyone else gets a role: \
"the ship's doctor", "a local hunter", "the captain's wife".
- For a main person with a hard name, use the easiest true form: a first name, a surname, a \
nickname or a title ("the Admiral"). Say the full name once at most, then the short form.
- Skip hard place names unless the place matters to the story; describe it instead ("a tiny \
frozen island in the Arctic"). Same for ships, organizations and other proper nouns.
- Never change or invent a real name to make it easier. If no easy true form exists, use the role.

THE OPENING (the first 50-70 seconds, about 150-210 words, is ALSO cut out and posted on its own as a \
YouTube Short, Instagram Reel and TikTok, so it must grab a scrolling viewer and work by itself)
- No intro. No "welcome back", no channel name, no "in this video", no "let's dive in".
- The very first sentence is the hook, and it must stop a thumb mid-scroll: a shocking true fact, an \
impossible-sounding outcome or a vivid moment of danger, said in under 15 words \
("In 1845, 129 men sailed into the Arctic, and not one of them came back."). Never open with \
background, a date on its own or a slow scene-setter.
- Start inside the action with concrete, visual details: a person, a place, something happening.
- Within the first three sentences, open a question the viewer needs answered (a mystery, a \
contradiction, an impossible outcome) and hint at the payoff without giving it away.
- Raise the stakes every 2-3 sentences through the opening, so the Short never sags.
- Somewhere between word 150 and 210, wherever the story's best cliffhanger naturally falls (the \
Short ends right after that sentence), land on it: a reveal that is just starting or a question left \
hanging ("And then the search party found something no one expected."), so Short viewers want the \
full video. Never pad or rush the opening to hit an exact length. The full video carries straight on from it.

RETENTION STRUCTURE
- Escalate: every 60-90 seconds (about 150-230 words) something changes: a new obstacle, a \
revelation, a mistake, a twist. Never let the story plateau.
- Open loops: plant small questions and pay them off later. Close the biggest loop near the end.
- Re-hooks: before natural drop-off points (around 30%, 50% and 75%), add a line that pulls the \
viewer forward ("But that wasn't the strangest part." / "And that's when everything went wrong.").
- Pattern interrupts: occasionally address the viewer directly ("Now you might be wondering...") \
and save a short punchy line for the biggest moments only.
- Stakes: make clear what each person stands to win or lose, in human terms.
- Payoff: the ending must resolve the opening question and land an insight, irony or consequence.
- Close with at most two short sentences that tease another story or invite a subscribe. Nothing longer.

THE BASICS A NEWCOMER NEEDS (who, what, when, where and why)
- Assume the viewer knows nothing about the subject. Soon after the opening, make sure they know \
who the main people are, what happened, when and where, and above all WHY it mattered: why people \
acted as they did, what was at stake and why anyone cared.
- Use common sense about what a curious viewer would ask. A story about hunting a man must say who \
he was and what he had done that made him wanted (the crimes, wars or abuses, and who was hurt). A \
rescue must say how the people got trapped. A discovery must say why it had been lost and why \
finding it mattered.
- Spend the time on what the viewer needs to understand the story, not on side details. A \
background section answers "why should I care about this person or event?", so give the facts that \
explain the story (what someone did, the power they held, the conflict they were in) before or \
instead of trivia such as a childhood, family tree or logistics, unless those drive the story.
- Keep context proportional: a few clear sentences woven into the story, not a history lecture.
- Before you finish, reread the script as someone who has never heard of the subject. Wherever they \
would ask "wait, who is that?" or "why does that matter?", answer it.

SIMPLE, CAPTIVATING LANGUAGE
- Write so a 13-year-old can follow every sentence the first time they hear it. Use everyday words; \
if a hard word or term is needed, explain it in a few plain words right away.
- Simple grammar: one main idea per sentence, active voice, no stacked clauses, no fancy or \
literary phrasing, no long lists of names or dates in one sentence.
- Keep it gripping through the story itself (stakes, mystery, surprise), not through elaborate wording.
- Tone: an upbeat, enthusiastic storyteller who can't wait to tell you what happened next. \
Energetic and curious, never sarcastic or flat. Stay respectful during sad or serious moments.

SMOOTH NARRATION (the voice is an AI, and punctuation controls its pauses)
- Every comma, period and dash makes the voice pause, and too many pauses sound choppy. \
Write sentences that flow in one breath, usually 10-20 words.
- Use commas sparingly: only where a speaker truly needs to breathe. Link ideas with words like \
"and", "so", "but", "because" and "then" instead of chains of commas.
- Avoid strings of very short sentences and one-word fragments ("Gone. Just gone."). At most one \
short dramatic line per paragraph.
- No em dashes, semicolons, ellipses or parentheses.

WRITING FOR THE EAR AND THE EYE
- Plain spoken English. Avoid lists and tongue-twisters.
- Be concrete and visual: name objects, places, actions and gestures. Each sentence should suggest \
an image a stick figure can act out (a man counting cash, a car skidding, two people shaking hands).
- Use real names, dates and numbers from the research. Do not invent quotes; if you paraphrase \
someone, say so ("he later said something like...").
- Never state disputed claims as fact. Treat sensitive events with respect. Keep it advertiser-friendly: \
no graphic violence or gore, no sexual content, no profanity.

SOUND LIKE A REAL PERSON TELLING IT
- Tell it the way a friend tells a crazy true story over dinner: in order, with the small human \
details that make it real (what someone ate, said, carried or was afraid of), and with the \
storyteller's own reactions now and then ("which, honestly, is a terrible plan", "and this is the \
part I can't get over").
- Use contractions (it's, didn't, they'd) and everyday spoken links: "so", "anyway", "here's the \
thing", "turns out", "meanwhile", "a few weeks later". Mix sentence lengths naturally.
- Say what happened plainly instead of describing how dramatic it was. Let the facts be the drama.
- Never use these phrases that make narration sound machine-written: "little did they know", \
"in a world where", "a testament to", "delve", "tapestry", "it's worth noting", "buckle up", \
"fast forward to", "the rest is history", "sent shockwaves", "forever changed", "a chilling \
reminder", "stood the test of time", "against all odds", "what happened next will shock you", \
"but here's the kicker", "plot twist".
- Avoid the patterns that give it away: "It wasn't X. It was Y." contrasts, lists of three \
adjectives, a rhetorical question at the end of every paragraph, and the same re-hook line twice. \
Each re-hook must be written for that exact moment of this story.

LENGTH
- Aim for the target word count you are given. It is read at about 180 words per minute."""


FORMAT_RULES = {
    "story": """VIDEO FORMAT: ONE TRUE STORY
Follow the story from the hook to the payoff, using the turning points in the research brief.""",
    "topic": """VIDEO FORMAT: A TOPIC EXPLAINED
- The video answers one central question (from the research brief). The hook poses it through a \
vivid real moment, then the script builds the answer step by step.
- Teach through real, documented people and events from the brief, never through vague \
generalities: every idea gets a concrete case the viewer can picture.
- Keep a story-like arc: each section reveals something that changes how the viewer sees the \
question, and the ending delivers the full answer with an insight or irony.
- Where popular myths exist, say what people believe and then what the evidence actually shows.""",
    "list": """VIDEO FORMAT: A COUNTDOWN OF SEVERAL TRUE CASES
- Count down the entries from the research brief, ending with the strongest one ("Number three...", \
"And number one..."). Announce each number clearly so viewers always know where they are.
- The hook teases the most remarkable case without naming it, then the first entry starts quickly.
- Each entry is a mini-story with its own hook, stakes, key evidence and payoff, about 250-450 \
words. Give the top entry the most time.
- Link entries with a short re-hook ("But that one has an explanation. The next one does not.").
- Never blend facts from different entries; each case keeps its own people, dates and evidence.
- Close by tying the cases together in one or two sentences.""",
}


def build_script_messages(idea: dict[str, Any], brief: str, target: tuple[int, int], notes: str = "",
                          wpm: float = 180, format: str = "story") -> list[dict[str, Any]]:
    minutes = (target[0] + target[1]) / 2 / wpm
    content = (
        f"Write the full narration script.\n\nTOPIC\nTitle: {idea.get('title', '')}\n"
        f"Hook idea: {idea.get('hook', '')}\nWhy it works: {idea.get('why_it_works', '')}\n\n"
        f"{FORMAT_RULES.get(format, FORMAT_RULES['story'])}\n\n"
        "ACCURACY: every fact, name, date and number must come from the research brief. If the brief "
        "doesn't support a detail, leave it out or say plainly that it is uncertain.\n\n"
        f"RESEARCH BRIEF\n{brief}\n\n"
        f"TARGET LENGTH: {target[0]}-{target[1]} words (about {minutes:.1f} minutes). "
        "Never go under the minimum: the video must run at least 8 minutes."
    )
    if notes.strip():
        content += f"\n\nEXTRA NOTES FROM THE CHANNEL OWNER\n{notes.strip()}"
    return [{"role": "user", "content": content}]


def generate(claude: Claude, idea: dict[str, Any], brief: str, target: tuple[int, int], notes: str = "",
             wpm: float = 180, format: str = "story") -> Iterator[str]:
    yield from claude.stream_text(SCRIPT_SYSTEM, build_script_messages(idea, brief, target, notes, wpm, format),
                                  max_tokens=32000)


def clean_script(text: str) -> str:
    """Strip anything the narrator shouldn't read: headings, markdown, bracketed directions."""
    lines = []
    for line in text.strip().splitlines():
        s = line.strip()
        if re.match(r"^#{1,6}\s", s) or re.match(r"^(\*\*)?(title|scene|narrator|hook|intro|outro)\b.*:", s, re.I):
            continue
        s = re.sub(r"\[[^\]]*\]", "", s)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"^[-*]\s+", "", s)
        lines.append(s)
    text = to_ascii("\n".join(lines))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


ASCII_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"', "«": '"', "»": '"',
    "…": "...", " ": " ", " ": " ", "​": "",
    "£": " pounds ", "€": " euros ", "°": " degrees ", "½": " and a half",
    "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ß": "ss", "ø": "o", "Ø": "O",
    "ł": "l", "Ł": "L", "ð": "d", "þ": "th",
}


def to_ascii(text: str) -> str:
    """Make text plain ASCII: straight quotes, no dashes or accents, symbols spelled out."""
    for k, v in ASCII_MAP.items():
        text = text.replace(k, v)
    # Dashes between words become a comma pause (a lone "-" would be read as a word).
    text = re.sub(r"[ \t]*[—–―‒][ \t]*", ", ", text)
    text = re.sub(r"[ \t]+--?[ \t]+", ", ", text)
    text = re.sub(r",\s*([.!?,;:])", r"\1", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[ \t]{2,}", " ", text)


# --- revisions --------------------------------------------------------------

REVISE_SYSTEM = SCRIPT_SYSTEM + """

YOU ARE NOW EDITING AN EXISTING SCRIPT
The channel owner chats with you to change parts of the script. Reply with:
- reply: a short message explaining what you changed (or answering their question).
- edits: a list of find/replace edits. `find` must be copied EXACTLY from the current script \
(same punctuation and spacing) and must be long enough to appear only once. `replace` is the new text. \
To delete, use an empty `replace`. To insert, include the neighbouring sentence in `find` and \
repeat it in `replace` with the new text added.
Keep edits minimal: change only what was asked, and keep the rules above. If they only ask a \
question, return no edits."""

REVISE_SCHEMA = obj({
    "reply": STR,
    "edits": arr(obj({"find": STR, "replace": STR, "reason": STR})),
})


def revise(claude: Claude, script: str, history: list[dict[str, Any]], instruction: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for h in history[-12:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({
        "role": "user",
        "content": f"CURRENT SCRIPT\n<script>\n{script}\n</script>\n\nREQUEST\n{instruction}",
    })
    result = claude.json(cached(REVISE_SYSTEM), messages, REVISE_SCHEMA, effort="medium")
    result["edits"] = [check_edit(script, {**e, "replace": to_ascii(e["replace"])}) for e in result["edits"]]
    return result


def check_edit(script: str, edit: dict[str, Any]) -> dict[str, Any]:
    n = script.count(edit["find"]) if edit["find"] else 0
    ok = n == 1
    error = None if ok else ("text not found in script" if n == 0 else f"text appears {n} times")
    return {**edit, "ok": ok, "error": error}


def apply_edits(script: str, edits: list[dict[str, Any]]) -> tuple[str, list[str]]:
    errors = []
    for e in edits:
        n = script.count(e["find"]) if e["find"] else 0
        if n != 1:
            errors.append(f"Skipped edit: '{e['find'][:60]}' ({'not found' if n == 0 else 'ambiguous'})")
            continue
        script = script.replace(e["find"], e["replace"], 1)
    script = re.sub(r"[ \t]+", " ", script)
    script = re.sub(r"\n{3,}", "\n\n", script)
    return script.strip(), errors
