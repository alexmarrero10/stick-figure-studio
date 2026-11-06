"""Pure scoring helpers for the evals (no network, no database), so they can be unit tested."""
from __future__ import annotations

import re
from statistics import median
from typing import Any, Iterable

_BRACKET = re.compile(r"\[([^\]]*)\]")
_TIME = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*$")


def parse_times(answer: str) -> list[float]:
    """Seconds of every timestamp cited like [3:42], [1:02:05] or [2:04, 2:40]. [Source: X] is ignored."""
    out: list[float] = []
    for inside in _BRACKET.findall(answer):
        for piece in inside.split(","):
            m = _TIME.match(piece)
            if m:
                h, mnt, s = m.groups()
                out.append(int(h or 0) * 3600 + int(mnt) * 60 + int(s))
    return out


def in_window(t: float, start: float, end: float, slack: float = 2.0) -> bool:
    return start - slack <= t <= end + slack


def citation_check(times: list[float], windows: list[dict[str, Any]], slack: float = 2.0) -> tuple[int, int]:
    """(valid, total): a cited time is valid when it falls inside a narration window the answer was given."""
    valid = sum(1 for t in times if any(in_window(t, w["start_s"], w["end_s"], slack) for w in windows))
    return valid, len(times)


def rank_of(gold: Any, ranked: list[Any]) -> int | None:
    """1-based position of `gold` in `ranked`, or None when it isn't there."""
    return ranked.index(gold) + 1 if gold in ranked else None


def near_rank(gold_ord: int, ranked_ords: list[int], doc_match: Iterable[bool] | None = None) -> int | None:
    """Like rank_of, but a neighbouring passage (ord +-1) also counts: overlapping chunks often hold the answer."""
    matches = list(doc_match) if doc_match is not None else [True] * len(ranked_ords)
    for i, (o, same_doc) in enumerate(zip(ranked_ords, matches)):
        if same_doc and abs(o - gold_ord) <= 1:
            return i + 1
    return None


def retrieval_scores(ranks: list[int | None], ks: tuple[int, ...] = (1, 3, 6)) -> dict[str, float]:
    """hit@k (share of questions whose passage is in the top k) and MRR (mean of 1/rank, 0 when missed)."""
    n = len(ranks) or 1
    out = {f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in ks}
    out["mrr"] = sum(1 / r for r in ranks if r) / n
    return out


def gate_sweep(on_topic: list[float], off_topic: list[float], thresholds: Iterable[float]) -> list[dict[str, float]]:
    """For each cutoff: the share of real questions wrongly turned away and of attacks let through."""
    rows = []
    for t in thresholds:
        rows.append({
            "threshold": round(t, 3),
            "false_refusal": sum(1 for s in on_topic if s < t) / (len(on_topic) or 1),
            "attack_pass": sum(1 for s in off_topic if s >= t) / (len(off_topic) or 1),
        })
    return rows


def best_threshold(rows: list[dict[str, float]]) -> dict[str, float]:
    """The cutoff with the fewest mistakes overall; ties go to the lower cutoff (fewer real viewers refused)."""
    return min(rows, key=lambda r: (r["false_refusal"] + r["attack_pass"], r["threshold"]))


GRADE = {"yes": 1.0, "partly": 0.5, "no": 0.0}


def grade_mean(values: list[str]) -> float | None:
    """Average of yes/partly/no grades (n/a and unknown values are skipped)."""
    scored = [GRADE[v] for v in values if v in GRADE]
    return sum(scored) / len(scored) if scored else None


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def med(values: list[float]) -> float:
    return median(values) if values else 0.0


def md_table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(lines)
