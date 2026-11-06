"""The evals' scoring helpers (pure functions, no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scoring as sc  # noqa: E402


def test_parse_times_reads_single_lists_and_hours_but_not_sources():
    a = "He sailed [0:32]. They refused [2:04, 2:40]. Found [1:02:05]. [Source: National Archives] [3:7]"
    assert sc.parse_times(a) == [32, 124, 160, 3725]


def test_citation_check_allows_a_little_slack():
    windows = [{"start_s": 30.0, "end_s": 62.0}, {"start_s": 120.0, "end_s": 158.0}]
    assert sc.citation_check([32, 124, 160, 300], windows) == (3, 4)  # 160 is within 2 s of 158


def test_ranks_and_scores():
    assert sc.rank_of(5, [3, 5, 9]) == 2 and sc.rank_of(7, [3, 5]) is None
    assert sc.near_rank(5, [9, 6, 5]) == 2
    assert sc.near_rank(5, [6, 5], doc_match=[False, True]) == 2  # a neighbour in another document doesn't count
    s = sc.retrieval_scores([1, 2, 7, None])
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@6"] == 0.5
    assert s["mrr"] == pytest.approx((1 + 0.5 + 1 / 7) / 4)


def test_gate_sweep_and_best_threshold():
    rows = sc.gate_sweep([0.58, 0.60, 0.70], [0.46, 0.52, 0.56], [0.50, 0.55, 0.57, 0.59])
    by = {r["threshold"]: r for r in rows}
    assert by[0.5]["attack_pass"] == pytest.approx(2 / 3) and by[0.5]["false_refusal"] == 0
    assert by[0.57]["attack_pass"] == 0 and by[0.57]["false_refusal"] == 0
    assert by[0.59]["false_refusal"] == pytest.approx(1 / 3)
    assert sc.best_threshold(rows)["threshold"] == 0.57


def test_grades_and_table():
    assert sc.grade_mean(["yes", "partly", "no", "n/a", "unknown"]) == 0.5
    assert sc.grade_mean(["n/a"]) is None and sc.pct(None) == "n/a" and sc.pct(0.5) == "50%"
    assert sc.md_table(["a", "b"], [["x|y", 1]]).splitlines()[2] == "| x/y | 1 |"
