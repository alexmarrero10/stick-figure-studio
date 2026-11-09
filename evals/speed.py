"""Speed and token test: the same four steps (research, write the script, check its facts, one chat
revision that asks for a new fact), done up to three ways on the same topic, model and settings:

- rag:  Python downloads the sources into the vector database; each step gets the best-matching passages.
- full: the same downloaded sources, but no RAG: each step gets the full text of every source instead of
        retrieved passages (same prompts and rules). This is the fair "no RAG" comparison.
- old:  no downloaded sources: Claude researches with web search itself, the script gets only the brief,
        and the fact check uses the brief plus web search.

rag and full share one download (same sources, same time counted for both). For every Claude call it
records the time and the token use the Claude CLI reports (plus the API-equivalent cost the CLI prints).
Nothing is saved to your projects. The sources stay in the shared vector database (that is how RAG works),
but are not linked to any project afterwards.

    .venv\\Scripts\\python evals\\speed.py                          # RAG vs full sources (fair comparison)
    .venv\\Scripts\\python evals\\speed.py --ways rag,full,old      # all three
    .venv\\Scripts\\python evals\\speed.py --ways old,rag           # the earlier test (old way first)
    .venv\\Scripts\\python evals\\speed.py --rag-first              # same as --ways rag,old
    .venv\\Scripts\\python evals\\speed.py --topic "The Halifax Explosion of 1917"
    .venv\\Scripts\\python evals\\speed.py --research-only          # only research (faster)

Pick a topic that isn't in the database yet to measure a first-time video (stored sources are reused,
so embedding time drops). Swap the order on a second run to check that order doesn't decide the result.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from typing import Any, Callable

import common
import scoring as sc

DEFAULT_TOPIC = {
    "title": "The Great Molasses Flood of 1919",
    "hook": "A wave of molasses taller than a man swept through a Boston neighborhood at 35 miles an hour.",
    "documentation": "Boston's North End, January 15, 1919: a giant molasses tank burst. The court case that followed "
                     "changed how engineers and companies are held responsible.",
}

REVISION = "Add one more specific, true detail to the opening scene that makes it more vivid."
FULL_MAX_WORDS = 100_000  # keeps the full-sources prompts inside Claude's context window
LABELS = {"old": "Old way (web search)", "rag": "RAG", "full": "Full sources, no RAG"}
SHORT = {"old": "old way", "rag": "RAG", "full": "full sources"}
STEPS = [("research", "Research"), ("script", "Script"), ("facts", "Fact check"), ("revision", "Revision")]
METRICS = ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens", "web_searches", "turns",
           "cost_usd")


def totals(log: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    t = {k: sum(c[k] for c in log) for k in METRICS}
    t["all_input_tokens"] = t["input_tokens"] + t["cache_write_tokens"] + t["cache_read_tokens"]
    t["claude_calls"] = len(log)
    t["claude_seconds"] = round(sum(c["seconds"] for c in log), 1)
    t["seconds"] = round(seconds, 1)
    t["other_seconds"] = round(max(0.0, seconds - t["claude_seconds"]), 1)
    return t


class Meter:
    """Times a block and collects the Claude calls made inside it."""

    def __init__(self, claude):
        self.claude = claude

    def __enter__(self):
        self.claude.usage_log = []
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.result = totals(self.claude.usage_log, time.monotonic() - self.t0)
        self.claude.usage_log = None


def add(*ts: dict[str, Any]) -> dict[str, Any]:
    return {k: round(sum(t[k] for t in ts), 3) for k in ts[0]}


def common_cfg() -> dict[str, Any]:
    from app.config import load_config
    return load_config()["claude"]


def say(msg: str, frac: float) -> None:
    print(f"    {msg}")


# --- full sources (no RAG) ----------------------------------------------------

def fit_words(lengths: list[int], budget: int) -> list[int]:
    """How many words of each source to keep so the total fits `budget`: short sources stay whole and the
    long ones share what is left equally."""
    keep = [0] * len(lengths)
    left, order = budget, sorted(range(len(lengths)), key=lambda i: lengths[i])
    for n, i in enumerate(order):
        keep[i] = min(lengths[i], left // (len(order) - n))
        left -= keep[i]
    return keep


def full_sources(docs: list[dict[str, Any]], max_words: int = FULL_MAX_WORDS) -> tuple[list[dict[str, Any]], dict]:
    """Every usable source as one whole 'passage' (the shape rag.format_excerpts and rag.write_brief take)."""
    ok = [d for d in docs if d.get("status") == "ok"]
    lengths = [len(d["text"].split()) for d in ok]
    keep = fit_words(lengths, max_words)
    chunks = [{"id": n, "document_id": n, "ord": 0, "heading": "", "title": d["title"], "url": d["url"],
               "text": " ".join(d["text"].split()[:k])} for n, (d, k) in enumerate(zip(ok, keep), 1)]
    info = {"sources": len(ok), "words": sum(lengths), "words_kept": sum(keep),
            "trimmed": sum(k < n for k, n in zip(keep, lengths))}
    return chunks, info


# --- research -------------------------------------------------------------------

def old_research(claude, idea, fmt, cfg) -> dict[str, Any]:
    from pipeline import script
    print("  Old way: Claude researches with web search...")
    with Meter(claude) as m:
        brief, sources = script.research(claude, idea, cfg.get("web_search", True), fmt,
                                         cfg.get("research_depth", "quick"))
    return {"brief": brief, "sources": sources, "research": m.result}


def download(claude, idea, fmt) -> tuple[list[dict[str, Any]], dict]:
    """One download shared by RAG and full sources (Claude picks sources, Python downloads them)."""
    from app.deps import rag_config
    from pipeline import sources
    cfg = rag_config()
    print("  Downloading sources (shared by RAG and full sources)...")
    with Meter(claude) as m:
        docs = sources.gather(claude, idea, fmt, cfg["docs_min"], cfg["docs_max"], None,
                              common_cfg().get("web_search", True), say)
    return docs, m.result


def rag_research(claude, idea, fmt, key, docs, dl) -> dict[str, Any]:
    from app.deps import embedder, rag_config
    from pipeline import rag
    cfg, store, embed = rag_config(), common.studio_store(), embedder()
    print("  RAG: store the sources, write the brief from the best passages...")
    with Meter(claude) as idx:
        rag.index_documents(store, embed, key, docs, cfg.get("owner", "owner"), cfg["chunk_words"],
                            cfg["overlap_words"], say)
    with Meter(claude) as b:
        brief, sources = rag.brief_from_store(claude, store, embed, idea, fmt, key, cfg, say)
    print("  RAG again (sources already stored, like re-researching a project)...")
    with Meter(claude) as again:
        rag.brief_from_store(claude, store, embed, idea, fmt, key, cfg, say)
    ok = [d for d in docs if d.get("status") == "ok"]
    return {"brief": brief, "sources": sources, "research": add(dl, idx.result, b.result), "again": again.result,
            "embed_seconds": idx.result["seconds"], "reused": sum(bool(d.get("reused")) for d in ok)}


def full_research(claude, idea, fmt, chunks, dl) -> dict[str, Any]:
    from pipeline import rag
    from pipeline.script import RESEARCH_SECTIONS, RESEARCH_SYSTEM
    print(f"  Full sources: write the brief from the whole text of all {len(chunks)} sources...")
    sections = RESEARCH_SECTIONS.get(fmt, RESEARCH_SECTIONS["story"])
    with Meter(claude) as b:
        brief, sources = rag.write_brief(claude, idea, fmt, chunks, RESEARCH_SYSTEM, sections, max_words=None)
    return {"brief": brief, "sources": sources, "research": add(dl, b.result)}


# --- script, fact check, revision ---------------------------------------------------
# Each takes `material(kind, text)`, which returns the source text that step gets: RAG looks it up,
# full sources returns everything, the old way returns nothing.

def write_script(claude, idea, brief, fmt, material: Callable[[str, str], str]) -> tuple[str, dict]:
    from app.config import load_config
    from pipeline import script
    scfg = load_config()["script"]
    with Meter(claude) as m:
        excerpts = material("script", brief)
        text = "".join(script.generate(claude, idea, brief, (scfg["target_words_min"], scfg["target_words_max"]),
                                       "", scfg["wpm_estimate"], fmt, excerpts))
    return text, m.result


def check_facts(claude, script_text, brief, material: Callable[[str, str], str]) -> tuple[dict, dict]:
    """With source text the check uses it and no web search; without, the brief plus web search."""
    from pipeline import fact_check
    with Meter(claude) as m:
        passages = material("facts", script_text)
        result = fact_check.check(claude, script_text, brief, passages, common_cfg().get("web_search", True))
    return result, m.result


def revise(claude, script_text, material: Callable[[str, str], str]) -> tuple[dict, dict]:
    """One chat revision that asks for a new fact, the way the Script step's chat does it."""
    from pipeline import script
    with Meter(claude) as m:
        excerpts = material("revision", REVISION)
        result = script.revise(claude, script_text, [], REVISION, excerpts)
    return result, m.result


def rag_material(key: str, idea: dict[str, Any]) -> Callable[[str, str], str]:
    from app.deps import embedder, rag_config
    from pipeline import rag

    def get(kind: str, text: str) -> str:
        store, embed = common.studio_store(), embedder()
        if kind == "script":
            return rag.script_excerpts(store, embed, key, text, idea, rag_config()["script_chunks"])
        if kind == "facts":
            return rag.fact_check_excerpts(store, embed, key, text)
        return rag.revise_excerpts(store, embed, key, text)
    return get


# --- report -----------------------------------------------------------------------

def change(old: float, new: float) -> str:
    if not old:
        return "n/a"
    d = (new - old) / old * 100
    return f"{abs(d):.0f}% {'less' if d < 0 else 'more'}"


def row(name: str, t: dict[str, Any]) -> list[Any]:
    return [name, f"{t['seconds'] / 60:.1f} min", f"{t['claude_seconds'] / 60:.1f} / {t['other_seconds'] / 60:.1f} min",
            t["claude_calls"], t["turns"], f"{t['all_input_tokens']:,}", f"{t['output_tokens']:,}",
            f"${t['cost_usd']:.2f}"]


HOW = {
    "old": ("Old way: Claude searches and reads pages itself for the brief; the script gets only the brief; the "
            "fact check uses the brief plus web search; the revision gets only the script."),
    "rag": ("RAG: the downloaded sources are stored in the vector database. The brief gets the best 30 passages, "
            "the script the best 10 (up to 2,500 words), the fact check the best 2 per paragraph (up to 5,000 "
            "words, no web search), the revision the best 5 (up to 1,200 words)."),
    "full": ("Full sources, no RAG: the same downloaded sources, but every step (brief, script, fact check, "
             "revision) gets the whole text of every source instead of retrieved passages. Same prompts and "
             "rules as RAG, no web search after the download."),
}


def build_report(args, idea, claude, cfg, ways, steps, res, extra) -> None:
    tot = {w: add(*(res[w][s] for s, _ in steps)) for w in ways}
    body = [f"Topic: **{idea['title']}** ({args.format}). Model {claude.model}, effort {claude.effort}. "
            f"Order: {' then '.join(SHORT[w] for w in ways)}. Every way runs the same steps: research, write the "
            "script, check its facts, then one chat revision that asks for a new fact.\n"]
    for b in [w for w in ways if w != "rag"] if "rag" in ways else []:
        cmp = []
        for s, name in steps + [(None, "**All steps**")]:
            o, r = (tot[b], tot["rag"]) if s is None else (res[b][s], res["rag"][s])
            cmp.append([name, f"{o['seconds'] / 60:.1f} vs {r['seconds'] / 60:.1f} min", change(o["seconds"], r["seconds"]),
                        change(o["all_input_tokens"], r["all_input_tokens"]), change(o["cost_usd"], r["cost_usd"])])
        body += [f"## RAG compared with {SHORT[b]}\n",
                 f"How much RAG changes each step compared with {SHORT[b]}.\n",
                 sc.md_table(["Step", f"Time ({SHORT[b]} vs RAG)", "Time with RAG", "Input tokens with RAG",
                              "Cost with RAG"], cmp), ""]
    rows = []
    for s, name in steps:
        rows += [row(f"{name}, {SHORT[w]}", res[w][s]) for w in ways]
    if "rag" in ways:
        rows.append(row("Research again, RAG (sources already stored)", res["rag"]["again"]))
    rows += [row(f"**Total, {SHORT[w]}**", tot[w]) for w in ways]
    body += ["## Every step\n",
             sc.md_table(["Step", "Time", "Claude / other time", "Claude calls", "Turns", "Input tokens",
                          "Output tokens", "API-equivalent cost"], rows),
             "\nInput tokens include cached ones (cache reads are much cheaper, which the cost column accounts for). "
             "'Other time' is downloading, embedding and database work. Turns count Claude's tool steps (each web "
             "search or page read is another turn, and each turn re-reads the conversation).\n",
             "How each way works:"]
    body += [f"- {HOW[w]}" for w in ways]
    if "download" in extra:
        d = extra["download"]
        body.append(f"\nSources: {d['ok']} of {d['tried']} downloads usable, {d['words']:,} words in all. RAG and full "
                    f"sources share this download ({d['metrics']['seconds'] / 60:.1f} min, counted in both).")
    if "full" in extra:
        f = extra["full"]
        body.append(f"Full sources sent {f['words_kept']:,} words per step"
                    + (f" ({f['trimmed']} long sources trimmed to fit the {args.full_max_words:,}-word limit)."
                       if f["trimmed"] else " (nothing trimmed)."))
    if "rag" in ways:
        r = res["rag"]
        body.append(f"RAG stored and embedded the sources in {r['embed_seconds'] / 60:.1f} min"
                    + (f" ({r['reused']} were already in the database and reused)." if r["reused"] else "."))
    body.append("")
    for w in ways:
        line = f"- {LABELS[w]}: brief {len(res[w]['brief'].split())} words citing {len(res[w]['sources'])} sources"
        if not args.research_only:
            f = res[w]["facts_result"]
            wrong = sum(i.get("verdict") == "wrong" for i in f["issues"])
            line += (f"; script {len(res[w]['script_text'].split())} words; the fact check found {wrong} wrong and "
                     f"{len(f['issues']) - wrong} unconfirmed claims ({f['reply']})")
        body.append(line)
    headline = {"topic": idea["title"], "order": ways,
                **{w: {"minutes": round(tot[w]["seconds"] / 60, 1), "input_tokens": tot[w]["all_input_tokens"],
                       "cost": round(tot[w]["cost_usd"], 3)} for w in ways}}
    common.report("speed", "Speed and tokens: RAG vs " + " vs ".join(SHORT[w] for w in ways if w != "rag"),
                  "\n".join(body), headline, {"results": res, **extra})


def parse_ways(text: str) -> list[str]:
    ways = [w.strip() for w in text.split(",") if w.strip()]
    bad = [w for w in ways if w not in LABELS]
    if bad or not ways or len(set(ways)) != len(ways):
        raise argparse.ArgumentTypeError(f"use a comma list of {', '.join(LABELS)} (each once)")
    return ways


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", help="video title to research (default: %s)" % DEFAULT_TOPIC["title"])
    ap.add_argument("--format", default="story", choices=["story", "topic", "list"])
    ap.add_argument("--ways", type=parse_ways, default=["rag", "full"],
                    help="which ways to run, in order: rag, full, old (default: rag,full)")
    ap.add_argument("--rag-first", action="store_true", help="same as --ways rag,old (the earlier test)")
    ap.add_argument("--research-only", action="store_true", help="only the research step")
    ap.add_argument("--full-max-words", type=int, default=FULL_MAX_WORDS,
                    help="most source words the full-sources way sends per step (default %(default)s)")
    args = ap.parse_args()
    ways = ["rag", "old"] if args.rag_first else args.ways

    from app.deps import claude as make_claude, rag_ready
    if ({"rag", "full"} & set(ways)) and not rag_ready():
        sys.exit("RAG isn't set up: add GEMINI_API_KEY and SUPABASE_DB_URL on Settings (and keep RAG switched on).")
    claude = make_claude()
    if not hasattr(claude, "usage_log"):
        sys.exit("This test reads token use from the Claude Code CLI. Switch the Claude provider to Claude Code.")
    idea = {"title": args.topic, "hook": "", "documentation": ""} if args.topic else DEFAULT_TOPIC
    key = f"bench:{datetime.now():%Y%m%d%H%M%S}"
    cfg = common_cfg()
    print(f"Topic: {idea['title']}  (model {claude.model}, effort {claude.effort}; ways: {', '.join(ways)})")

    res: dict[str, dict[str, Any]] = {}
    extra: dict[str, Any] = {}
    material: dict[str, Callable[[str, str], str]] = {"old": lambda kind, text: ""}
    steps = STEPS[:1] if args.research_only else STEPS
    docs: list[dict[str, Any]] | None = None
    try:
        for way in ways:
            if way == "old":
                res["old"] = old_research(claude, idea, args.format, cfg)
                continue
            if docs is None:
                docs, dl = download(claude, idea, args.format)
                ok = [d for d in docs if d.get("status") == "ok"]
                extra["download"] = {"ok": len(ok), "tried": len(docs), "metrics": dl,
                                     "words": sum(len(d["text"].split()) for d in ok)}
                if not ok:
                    sys.exit("No usable sources were downloaded for this topic.")
            if way == "rag":
                res["rag"] = rag_research(claude, idea, args.format, key, docs, dl)
                material["rag"] = rag_material(key, idea)
            else:
                chunks, extra["full"] = full_sources(docs, args.full_max_words)
                res["full"] = full_research(claude, idea, args.format, chunks, dl)
                from pipeline import rag
                everything = rag.format_excerpts(chunks)
                material["full"] = lambda kind, text, everything=everything: everything
        if not args.research_only:
            for way in ways:
                r, get = res[way], material[way]
                print(f"  Writing the script ({SHORT[way]})...")
                r["script_text"], r["script"] = write_script(claude, idea, r["brief"], args.format, get)
                print(f"  Checking the facts ({SHORT[way]})...")
                r["facts_result"], r["facts"] = check_facts(claude, r["script_text"], r["brief"], get)
                print(f"  One chat revision ({SHORT[way]})...")
                r["revision_result"], r["revision"] = revise(claude, r["script_text"], get)
    finally:
        if "rag" in ways:
            store = common.studio_store()
            for doc_id in store.project_documents(key):  # keep the sources in the shared corpus, unlinked
                store.unlink_project(key, doc_id)

    build_report(args, idea, claude, cfg, ways, steps, res, extra)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
