"""Speed and token test: the same four steps the old way (Claude searches the web itself) vs with RAG
(Python downloads the sources into the vector database; Claude works from the best passages):
research, write the script, check its facts, and one chat revision that asks for a new fact.

Both ways run on the same topic, with the same model and settings, one after the other. For every Claude
call it records the time and the token use the Claude CLI reports (plus the API-equivalent cost the CLI
prints, a fair single number for "how much usage"). Nothing is saved to your projects. The RAG run's sources
stay in the shared vector database (that is how RAG works), but are not linked to any project afterwards.

    .venv\\Scripts\\python evals\\speed.py                                 # default new topic
    .venv\\Scripts\\python evals\\speed.py --topic "The Great Molasses Flood of 1919"
    .venv\\Scripts\\python evals\\speed.py --research-only                 # only research (faster)
    .venv\\Scripts\\python evals\\speed.py --rag-first                     # run RAG before the old way

Pick a topic that isn't in the database yet to measure a first-time video. Run it twice with
--rag-first on the second run to check that the order doesn't decide the result.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from typing import Any

import common
import scoring as sc

DEFAULT_TOPIC = {
    "title": "The Great Molasses Flood of 1919",
    "hook": "A wave of molasses taller than a man swept through a Boston neighborhood at 35 miles an hour.",
    "documentation": "Boston's North End, January 15, 1919: a giant molasses tank burst. The court case that followed "
                     "changed how engineers and companies are held responsible.",
}


def totals(log: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    t = {k: sum(c[k] for c in log) for k in ("input_tokens", "cache_write_tokens", "cache_read_tokens",
                                            "output_tokens", "web_searches", "turns", "cost_usd")}
    t["all_input_tokens"] = t["input_tokens"] + t["cache_write_tokens"] + t["cache_read_tokens"]
    t["claude_calls"] = len(log)
    t["claude_seconds"] = round(sum(c["seconds"] for c in log), 1)
    t["seconds"] = round(seconds, 1)
    t["other_seconds"] = round(max(0.0, seconds - t["claude_seconds"]), 1)
    return t


REVISION = "Add one more specific, true detail to the opening scene that makes it more vivid."


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


def old_research(claude, idea, fmt, cfg) -> tuple[str, list, dict]:
    from pipeline import script
    print("  Old way: Claude researches with web search...")
    with Meter(claude) as m:
        brief, sources = script.research(claude, idea, cfg.get("web_search", True), fmt,
                                         cfg.get("research_depth", "quick"))
    return brief, sources, m.result


def rag_research(claude, idea, fmt, key) -> tuple[str, list, dict, dict]:
    from app.deps import embedder, rag_config
    from pipeline import rag
    cfg, store, embed = rag_config(), common.studio_store(), embedder()
    web = common_cfg().get("web_search", True)

    def say(msg, frac):
        print(f"    {msg}")

    print("  RAG: download sources, store them, write the brief from passages...")
    with Meter(claude) as m:
        docs = rag.find_sources(claude, store, embed, idea, fmt, key, cfg, None, web, say)
        brief, sources = rag.brief_from_store(claude, store, embed, idea, fmt, key, cfg, say)
    found = {"sources_ok": sum(d["status"] == "ok" for d in docs), "sources_tried": len(docs)}
    print("  RAG again (sources already stored, like re-researching a project)...")
    with Meter(claude) as again:
        rag.brief_from_store(claude, store, embed, idea, fmt, key, cfg, say)
    return brief, sources, m.result, {**found, "again": again.result}


def write_script(claude, idea, brief, fmt, excerpts_key: str | None) -> tuple[str, dict]:
    from app.config import load_config
    from app.deps import embedder, rag_config
    from pipeline import rag, script
    scfg = load_config()["script"]
    with Meter(claude) as m:
        excerpts = ""
        if excerpts_key:
            excerpts = rag.script_excerpts(common.studio_store(), embedder(), excerpts_key, brief, idea,
                                           rag_config()["script_chunks"])
        text = "".join(script.generate(claude, idea, brief, (scfg["target_words_min"], scfg["target_words_max"]),
                                       "", scfg["wpm_estimate"], fmt, excerpts))
    return text, m.result


def check_facts(claude, script_text, brief, key: str | None) -> tuple[dict, dict]:
    """The same fact check both ways: RAG checks against stored passages, the old way against the brief
    plus web search."""
    from app.deps import embedder
    from pipeline import fact_check, rag
    with Meter(claude) as m:
        passages = rag.fact_check_excerpts(common.studio_store(), embedder(), key, script_text) if key else ""
        result = fact_check.check(claude, script_text, brief, passages, common_cfg().get("web_search", True))
    return result, m.result


def revise(claude, script_text, key: str | None) -> tuple[dict, dict]:
    """One chat revision that asks for a new fact, the way the Script step's chat does it."""
    from app.deps import embedder
    from pipeline import rag, script
    with Meter(claude) as m:
        excerpts = rag.revise_excerpts(common.studio_store(), embedder(), key, REVISION) if key else ""
        result = script.revise(claude, script_text, [], REVISION, excerpts)
    return result, m.result


def common_cfg() -> dict[str, Any]:
    from app.config import load_config
    return load_config()["claude"]


def change(old: float, new: float) -> str:
    if not old:
        return "n/a"
    d = (new - old) / old * 100
    return f"{abs(d):.0f}% {'less' if d < 0 else 'more'}"


def row(name: str, t: dict[str, Any]) -> list[Any]:
    return [name, f"{t['seconds'] / 60:.1f} min", f"{t['claude_seconds'] / 60:.1f} / {t['other_seconds'] / 60:.1f} min",
            t["claude_calls"], t["turns"], f"{t['all_input_tokens']:,}", f"{t['output_tokens']:,}",
            f"${t['cost_usd']:.2f}"]


def add(*ts: dict[str, Any]) -> dict[str, Any]:
    return {k: sum(t[k] for t in ts) for k in ts[0]}


STEPS = [("research", "Research"), ("script", "Script"), ("facts", "Fact check"), ("revision", "Revision")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", help="video title to research (default: %s)" % DEFAULT_TOPIC["title"])
    ap.add_argument("--format", default="story", choices=["story", "topic", "list"])
    ap.add_argument("--research-only", action="store_true", help="only the research step")
    ap.add_argument("--rag-first", action="store_true", help="run the RAG way first")
    args = ap.parse_args()

    from app.deps import claude as make_claude, rag_ready
    if not rag_ready():
        sys.exit("RAG isn't set up: add GEMINI_API_KEY and SUPABASE_DB_URL on Settings (and keep RAG switched on).")
    claude = make_claude()
    if not hasattr(claude, "usage_log"):
        sys.exit("This test reads token use from the Claude Code CLI. Switch the Claude provider to Claude Code.")
    idea = {"title": args.topic, "hook": "", "documentation": ""} if args.topic else DEFAULT_TOPIC
    key = f"bench:{datetime.now():%Y%m%d%H%M%S}"
    cfg = common_cfg()
    print(f"Topic: {idea['title']}  (model {claude.model}, effort {claude.effort}, "
          f"old research depth: {cfg.get('research_depth', 'quick')})")

    res: dict[str, Any] = {}
    order = ["rag", "old"] if args.rag_first else ["old", "rag"]
    steps = STEPS[:1] if args.research_only else STEPS
    try:
        for way in order:
            if way == "old":
                res["old_brief"], old_src, res["old_research"] = old_research(claude, idea, args.format, cfg)
            else:
                res["rag_brief"], rag_src, res["rag_research"], extra = rag_research(claude, idea, args.format, key)
                res["rag_again"] = extra.pop("again")
                res["rag_sources"] = extra
        if not args.research_only:
            for way in order:
                k = key if way == "rag" else None
                label = "old way" if way == "old" else "RAG"
                print(f"  Writing the script ({label})...")
                text, res[f"{way}_script"] = write_script(claude, idea, res[f"{way}_brief"], args.format, k)
                res[f"{way}_script_text"] = text
                print(f"  Checking the facts ({label})...")
                res[f"{way}_facts_result"], res[f"{way}_facts"] = check_facts(claude, text, res[f"{way}_brief"], k)
                print(f"  One chat revision ({label})...")
                res[f"{way}_revision_result"], res[f"{way}_revision"] = revise(claude, text, k)
    finally:
        store = common.studio_store()
        for doc_id in store.project_documents(key):  # keep the sources in the shared corpus, unlinked
            store.unlink_project(key, doc_id)

    rows = []
    for step, name in steps:
        rows += [row(f"{name}, old way", res[f"old_{step}"]), row(f"{name}, RAG", res[f"rag_{step}"])]
    rows.append(row("Research again, RAG (sources already stored)", res["rag_again"]))
    ot = add(*(res[f"old_{s}"] for s, _ in steps))
    rt = add(*(res[f"rag_{s}"] for s, _ in steps))
    rows += [row("**Total, old way**", ot), row("**Total, RAG**", rt)]

    def cmp_row(name: str, o: dict, r: dict) -> list[str]:
        return [name, f"{o['seconds'] / 60:.1f} vs {r['seconds'] / 60:.1f} min", change(o["seconds"], r["seconds"]),
                change(o["all_input_tokens"], r["all_input_tokens"]), change(o["cost_usd"], r["cost_usd"])]

    compare = [cmp_row(name, res[f"old_{s}"], res[f"rag_{s}"]) for s, name in steps]
    compare.append(cmp_row("**All steps**", ot, rt))
    body = [
        f"Topic: **{idea['title']}** ({args.format}). Model {claude.model}, effort {claude.effort}, old research "
        f"depth {cfg.get('research_depth', 'quick')}. Order: {' then '.join(order)}. Both ways run the same steps: "
        "research, write the script, check its facts, then one chat revision that asks for a new fact.\n",
        "## RAG compared with the old way\n",
        sc.md_table(["Step", "Time (old vs RAG)", "Time", "Input tokens", "API-equivalent cost"], compare),
        "\n## Every step\n",
        sc.md_table(["Step", "Time", "Claude / other time", "Claude calls", "Turns", "Input tokens", "Output tokens",
                     "API-equivalent cost"], rows),
        "\nInput tokens include cached ones (cache reads are much cheaper, which the cost column accounts for). "
        "'Other time' is downloading, embedding and database work. Turns count Claude's tool steps (each web "
        "search or page read is another turn, and each turn re-reads the conversation).\n",
        "How each step differs:",
        "- Research: the old way has Claude search and read pages itself; RAG downloads the sources in code, "
        "stores them, and Claude writes the brief from the best passages.",
        "- Script: both write from the brief; RAG also gets source passages to check details against.",
        "- Fact check: the old way checks the script against the brief and searches the web for the rest; RAG "
        "checks it against the stored passages that match each paragraph, with no web search.",
        f"- Revision ('{REVISION}'): the old way sends only the script; RAG adds the 5 passages that match "
        "the request, so the new fact comes from a source.\n",
        f"Briefs: old {len(res['old_brief'].split())} words citing {len(old_src)} sources; RAG "
        f"{len(res['rag_brief'].split())} words citing {len(rag_src)} of {res['rag_sources']['sources_ok']} "
        "downloaded sources.",
    ]
    if not args.research_only:
        for way, label in (("old", "Old way"), ("rag", "RAG")):
            f = res[f"{way}_facts_result"]
            wrong = sum(i.get("verdict") == "wrong" for i in f["issues"])
            body.append(f"- {label}: script {len(res[f'{way}_script_text'].split())} words; the fact check found "
                        f"{wrong} wrong and {len(f['issues']) - wrong} unconfirmed claims ({f['reply']})")
    headline = {"topic": idea["title"], "order": order,
                "minutes": [round(ot["seconds"] / 60, 1), round(rt["seconds"] / 60, 1)],
                "input_tokens": [ot["all_input_tokens"], rt["all_input_tokens"]],
                "cost": [round(ot["cost_usd"], 3), round(rt["cost_usd"], 3)],
                **{f"{s}_minutes": [round(res[f"old_{s}"]["seconds"] / 60, 1),
                                    round(res[f"rag_{s}"]["seconds"] / 60, 1)] for s, _ in steps}}
    common.report("speed", "Speed and tokens: RAG vs the old way", "\n".join(body), headline,
                  {k: v for k, v in res.items()})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
