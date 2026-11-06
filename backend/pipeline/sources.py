"""Gather 10-15 source documents for a video: Wikipedia articles plus pages from archives, museums,
universities and news sites.

Claude only *picks* the sources (one quick call with a few web searches, no page reading). Python then
downloads the pages itself, in parallel, and pulls out the article text. That is much faster and uses
far less of the Claude plan than having Claude open every page.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from pipeline import procs
from pipeline.claude_client import Claude

WIKI_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia blocks clients whose User-Agent has no contact point. The project page serves as one
# (never a personal email).
WIKI_UA = "StickFigureStudio/1.0 (https://github.com/alexmarrero10/stick-figure-studio) httpx"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
MIN_WORDS = 300
MAX_WORDS = 20000  # very long pages (whole books) are cut to keep embedding cheap

# Wikipedia sections that hold no facts about the story.
_WIKI_TAIL = re.compile(r"^==\s*(See also|References|External links|Notes|Further reading|Bibliography|"
                        r"Sources|Citations|Footnotes|Works cited)\s*==\s*$", re.M | re.I)

PICK_SYSTEM = """You find sources for a true-story history YouTube channel. You do not write the \
research yourself; you only choose the pages a researcher should read.

Run at most 3 web searches. Do not open pages; search results are enough to choose.
Reply in exactly this Markdown format and nothing else:

## Wikipedia
- Exact English Wikipedia article title
(3-6 articles: the main subject first, then the key people, places and events)

## Other sources
1. [Page title - Publisher](https://full-url)
(6-10 pages. Prefer museums, archives, universities, government records, reputable newspapers and \
history publications. Pages must be ordinary web articles, not PDFs, videos, social media, forums, \
paywalled news or shops. Never guess a URL: only list URLs that appeared in your search results.)"""


def normalize_url(url: str) -> str:
    """Same page, same key: drop fragments, tracking query strings and trailing slashes."""
    parts = urlsplit(url.strip())
    query = "&".join(q for q in parts.query.split("&") if q and not q.lower().startswith(("utm_", "fbclid", "gclid")))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, query, ""))


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()',-")


def parse_picks(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Read Claude's reply: Wikipedia titles and other source links."""
    wiki: list[str] = []
    other: list[dict[str, str]] = []
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            low = s.lower()
            section = "wiki" if "wikipedia" in low else ("other" if "other" in low or "source" in low else section)
            continue
        m = re.search(r"\[([^\]]+)\]\((https?://(?:[^()\s]|\([^()\s]*\))+)\)", s)
        if m:
            url = m.group(2)
            if "wikipedia.org/wiki/" in url:
                wiki.append(unquote(url.split("/wiki/", 1)[1]).replace("_", " "))
            else:
                other.append({"title": m.group(1).strip(), "url": url})
            continue
        if section == "wiki" and s.startswith(("-", "*")):
            title = s.lstrip("-* ").strip().strip('"')
            if title:
                wiki.append(title)
    return list(dict.fromkeys(wiki)), other


def pick_sources(claude: Claude, idea: dict[str, Any], format: str, exclude: list[str] | None = None,
                 web_search: bool = True) -> tuple[list[str], list[dict[str, str]]]:
    msg = (f"Find sources for this video.\n\nTitle: {idea.get('title', '')}\nHook: {idea.get('hook', '')}\n"
           f"Notes: {idea.get('documentation', '')}\nVideo format: {format}")
    if exclude:
        msg += "\n\nWe already have these pages, so suggest different ones:\n" + "\n".join(exclude[:40])
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}] if web_search else None
    final = claude.complete(PICK_SYSTEM, [{"role": "user", "content": msg}], max_tokens=4000, tools=tools,
                            effort="low")
    return parse_picks(Claude.text_of(final))


# --- Wikipedia --------------------------------------------------------------

def wiki_search(query: str, limit: int, client: httpx.Client) -> list[str]:
    r = client.get(WIKI_API, params={"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                                     "format": "json", "formatversion": 2})
    r.raise_for_status()
    return [h["title"] for h in r.json().get("query", {}).get("search", [])]


def wiki_article(title: str, client: httpx.Client) -> dict[str, Any] | None:
    """Plain text of a Wikipedia article (follows redirects), without the reference sections."""
    r = client.get(WIKI_API, params={"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                                     "titles": title, "format": "json", "formatversion": 2})
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or not pages[0].get("extract"):
        return None
    page = pages[0]
    text = page["extract"]
    m = _WIKI_TAIL.search(text)
    if m:
        text = text[:m.start()]
    return {"url": wiki_url(page["title"]), "title": f"{page['title']} - Wikipedia", "source_type": "wikipedia",
            "text": text.strip()}


# --- other web pages --------------------------------------------------------

def extract_page(html: str, url: str) -> tuple[str, str]:
    """Main article text and title of a web page (menus, ads and footers dropped)."""
    import trafilatura
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_precision=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "") or ""
    return text.strip(), title.strip()


def fetch_page(src: dict[str, str], client: httpx.Client) -> dict[str, Any]:
    url = src["url"]
    base = {"url": url, "title": src.get("title") or url, "source_type": "web", "text": ""}
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        return {**base, "status": "skipped", "reason": f"could not download ({type(e).__name__})"}
    if r.status_code != 200:
        return {**base, "status": "skipped", "reason": f"site answered {r.status_code}"}
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype:
        return {**base, "status": "skipped", "reason": f"not a web page ({ctype.split(';')[0] or 'unknown'})"}
    text, title = extract_page(r.text, url)
    return {**base, "url": str(r.url), "title": src.get("title") or title or url, "text": text}


def _finish(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("status") == "skipped":
        doc["words"] = 0
        return doc
    words = doc["text"].split()
    if len(words) > MAX_WORDS:
        doc["text"] = " ".join(words[:MAX_WORDS])
    doc["words"] = min(len(words), MAX_WORDS)
    if doc["words"] < MIN_WORDS:
        return {**doc, "status": "skipped", "reason": f"too little text ({doc['words']} words)"}
    return {**doc, "status": "ok", "reason": ""}


def gather(claude: Claude, idea: dict[str, Any], format: str = "story", docs_min: int = 10, docs_max: int = 15,
           exclude: list[str] | None = None, web_search: bool = True,
           progress: Callable[[str, float], None] | None = None,
           client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Return documents (ok and skipped), each {url, title, source_type, text, words, status, reason}.
    Aims for `docs_min`-`docs_max` usable ones. `exclude` holds URLs the project already has."""
    say = progress or (lambda m, f: None)
    seen = {normalize_url(u) for u in (exclude or [])}
    say("Choosing sources (Claude runs a few quick searches)", 0.05)
    wiki_titles, others = pick_sources(claude, idea, format, exclude, web_search)
    procs.check()

    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    docs: list[dict[str, Any]] = []

    def new(url: str) -> bool:
        key = normalize_url(url)
        if key in seen:
            return False
        seen.add(key)
        return True

    def ok_count() -> int:
        return sum(d["status"] == "ok" for d in docs)

    try:
        wiki_headers = {"User-Agent": WIKI_UA}
        if len(wiki_titles) < 3 and idea.get("title"):
            client.headers.update(wiki_headers)
            wiki_titles += [t for t in wiki_search(idea["title"], 5, client) if t not in wiki_titles]
        say(f"Downloading {min(len(wiki_titles), 6)} Wikipedia articles", 0.15)
        client.headers.update(wiki_headers)
        with ThreadPoolExecutor(max_workers=6) as pool:
            for art in pool.map(lambda t: _safe(wiki_article, t, client), wiki_titles[:6]):
                if art and new(art["url"]):
                    docs.append(_finish(art))
        procs.check()

        room = max(docs_max - ok_count(), 0)
        picks = [o for o in others if new(o["url"])][:room + 4]  # a few spare, some sites block downloads
        say(f"Downloading {len(picks)} pages from other sites", 0.3)
        client.headers.update({"User-Agent": BROWSER_UA})
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = [_finish(d) for d in pool.map(lambda s: fetch_page(s, client), picks)]
        for d in fetched:
            if d["status"] == "ok" and ok_count() >= docs_max:
                d = {**d, "status": "skipped", "reason": "already have enough sources"}
            docs.append(d)
        procs.check()

        # Not enough? Top up with more Wikipedia articles found by search.
        if ok_count() < docs_min and idea.get("title"):
            client.headers.update(wiki_headers)
            extra = [t for t in wiki_search(idea["title"], 10, client) if t not in wiki_titles]
            say("Finding a few more Wikipedia articles", 0.4)
            for t in extra:
                if ok_count() >= docs_min:
                    break
                art = _safe(wiki_article, t, client)
                if art and new(art["url"]):
                    docs.append(_finish(art))
    finally:
        if own:
            client.close()
    return docs


def _safe(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except httpx.HTTPError:
        return None
