"""Split narration into beats: short chunks of words (~1-3 s of speech), one picture each.

The script text is the single source of truth for word indices: word i is the i-th item of
`text.split()`. Every other step (voice timings, shots) refers to words by that index.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*$")
SOFT_BREAK = re.compile(r"[,;:—–]+[\"'”’)\]]*$|^[—–]$|--$")
# Words that start a new clause; a good place to cut when a chunk runs long.
CLAUSE_STARTERS = {
    "and", "but", "so", "because", "when", "while", "until", "then", "which", "who",
    "where", "after", "before", "as", "if", "or", "yet", "though", "although", "since",
}


@dataclass
class Word:
    text: str
    para_end: bool  # last word of a paragraph


def tokenize(text: str) -> list[Word]:
    words: list[Word] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        toks = para.split()
        for i, t in enumerate(toks):
            words.append(Word(t, i == len(toks) - 1))
    return words


def ends_sentence(w: str) -> bool:
    return bool(SENTENCE_END.search(w))


def soft_break(w: str) -> bool:
    return bool(SOFT_BREAK.search(w))


def _words_to_sentence_end(words: list[Word], i: int) -> int:
    """How many words remain after index i until the end of its sentence (inclusive of that end)."""
    n = 0
    for j in range(i + 1, len(words)):
        n += 1
        if ends_sentence(words[j].text) or words[j].para_end:
            break
    return n


def split_chunks(words: list[Word], min_words: int = 2, max_words: int = 8) -> list[tuple[int, int]]:
    """Greedy split into (start, end) word ranges, end inclusive."""
    chunks: list[tuple[int, int]] = []
    start = 0
    i = 0
    while i < len(words):
        w = words[i]
        length = i - start + 1
        hard = ends_sentence(w.text) or w.para_end or i == len(words) - 1
        soft = (
            soft_break(w.text)
            and length >= min_words
            and _words_to_sentence_end(words, i) >= min_words
        )
        if hard or soft:
            chunks.append((start, i))
            start = i + 1
        elif length >= max_words:
            # Prefer cutting before a clause starter inside the chunk, else cut here.
            def starter(k: int) -> bool:
                return words[k].text.lower().strip("\"'“‘(") in CLAUSE_STARTERS

            cut = None
            for j in range(i, start + min_words - 1, -1):
                if starter(j) and j - start >= min_words:
                    # "and then", "but when": cut before the first word of the run.
                    while j - 1 - start >= min_words and starter(j - 1):
                        j -= 1
                    cut = j - 1
                    break
            end = cut if cut is not None else i
            chunks.append((start, end))
            start = end + 1
            i = end
        i += 1
    return _merge_short(words, chunks, min_words, max_words)


def _merge_short(words: list[Word], chunks: list[tuple[int, int]], min_words: int, max_words: int) -> list[tuple[int, int]]:
    """Merge chunks under min_words into the neighbour that keeps the result smallest."""
    chunks = list(chunks)
    keep: set[tuple[int, int]] = set()  # short chunks with no neighbour that fits; left alone
    changed = True
    while changed and len(chunks) > 1:
        changed = False
        for k, (s, e) in enumerate(chunks):
            if e - s + 1 >= min_words or (s, e) in keep:
                continue
            prev_len = chunks[k - 1][1] - chunks[k - 1][0] + 1 if k > 0 else None
            next_len = chunks[k + 1][1] - chunks[k + 1][0] + 1 if k + 1 < len(chunks) else None
            # Don't merge across paragraphs when there is a choice.
            prev_ok = prev_len is not None and not words[chunks[k - 1][1]].para_end
            next_ok = next_len is not None and not words[e].para_end
            options = []
            if prev_ok:
                options.append((prev_len, "prev"))
            if next_ok:
                options.append((next_len, "next"))
            if not options:
                options = [(l, d) for l, d in ((prev_len, "prev"), (next_len, "next")) if l is not None]
            # Prefer a neighbour that stays within max_words after merging.
            n = e - s + 1
            fitting = [o for o in options if o[0] + n <= max_words]
            if not fitting and ends_sentence(words[e].text):
                keep.add((s, e))  # a complete short sentence ("No.") can stand as its own beat
                continue
            _, direction = min(fitting or options)
            if direction == "prev":
                chunks[k - 1] = (chunks[k - 1][0], e)
            else:
                chunks[k + 1] = (s, chunks[k + 1][1])
            del chunks[k]
            changed = True
            break
    return chunks


def build_beats(text: str, min_words: int = 2, max_words: int = 8, wpm: float = 160) -> list[dict[str, Any]]:
    words = tokenize(text)
    beats = []
    for idx, (s, e) in enumerate(split_chunks(words, min_words, max_words)):
        n = e - s + 1
        beats.append({
            "idx": idx,
            "word_start": s,
            "word_end": e,
            "text": " ".join(w.text for w in words[s:e + 1]),
            "est_seconds": round(n * 60 / wpm, 2),
        })
    return beats


def beats_from_ranges(text: str, ranges: list[tuple[int, int]], wpm: float = 160) -> list[dict[str, Any]]:
    words = text.split()
    return [
        {
            "idx": i,
            "word_start": s,
            "word_end": e,
            "text": " ".join(words[s:e + 1]),
            "est_seconds": round((e - s + 1) * 60 / wpm, 2),
        }
        for i, (s, e) in enumerate(ranges)
    ]


def replace_beat_text(text: str, ranges: list[tuple[int, int]], beat: int,
                      new_text: str) -> tuple[str, list[tuple[int, int]]]:
    """Rewrite one beat's words in the script. Returns (new script, new ranges).

    Paragraph breaks and spacing outside the beat are kept; later beats shift by the word-count change.
    """
    new_words = new_text.split()
    if not new_words:
        raise ValueError("A beat can't be empty. Merge it into a neighbour instead.")
    if not 0 <= beat < len(ranges):
        raise ValueError(f"no beat {beat}")
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    s, e = ranges[beat]
    new_script = text[:spans[s][0]] + " ".join(new_words) + text[spans[e][1]:]
    delta = len(new_words) - (e - s + 1)
    new_ranges = (ranges[:beat] + [(s, s + len(new_words) - 1)]
                  + [(a + delta, b + delta) for a, b in ranges[beat + 1:]])
    validate_ranges(new_ranges, len(new_script.split()))
    return new_script, new_ranges


def validate_ranges(ranges: list[tuple[int, int]], n_words: int) -> None:
    """Ranges must cover every word exactly once, in order."""
    expected = 0
    for s, e in ranges:
        if s != expected or e < s:
            raise ValueError(f"beat range {s}-{e} breaks coverage at word {expected}")
        expected = e + 1
    if expected != n_words:
        raise ValueError(f"beats cover {expected} words but script has {n_words}")


def apply_ops(ranges: list[tuple[int, int]], ops: list[dict[str, Any]], n_words: int,
              max_words: int = 8) -> tuple[list[tuple[int, int]], list[str]]:
    """Apply merge/split operations (from Claude or the UI). Invalid ops are skipped and reported.

    op = {"op": "merge", "beat": i}            merges beat i with beat i+1
    op = {"op": "split", "beat": i, "at": w}   splits beat i so word w starts a new beat
    Beat numbers refer to the ORIGINAL list; ops are applied from the end backwards so indices hold.
    """
    ranges = list(ranges)
    skipped: list[str] = []
    for op in sorted(ops, key=lambda o: o.get("beat", -1), reverse=True):
        i = op.get("beat")
        if not isinstance(i, int) or not 0 <= i < len(ranges):
            skipped.append(f"bad beat index in {op}")
            continue
        s, e = ranges[i]
        if op.get("op") == "merge":
            if i + 1 >= len(ranges):
                skipped.append(f"cannot merge last beat {i}")
                continue
            ns, ne = s, ranges[i + 1][1]
            if ne - ns + 1 > max_words + 2:
                skipped.append(f"merge of beat {i} would be too long")
                continue
            ranges[i:i + 2] = [(ns, ne)]
        elif op.get("op") == "split":
            at = op.get("at")
            if not isinstance(at, int) or not s < at <= e:
                skipped.append(f"split point {at} not inside beat {i} ({s}-{e})")
                continue
            ranges[i:i + 1] = [(s, at - 1), (at, e)]
        else:
            skipped.append(f"unknown op {op}")
    validate_ranges(ranges, n_words)
    return ranges, skipped
