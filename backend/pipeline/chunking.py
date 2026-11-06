"""Split source documents into overlapping chunks for the vector database.

Chunks break on paragraph ends first, then sentence ends, so a chunk rarely cuts a sentence in half.
Each chunk keeps the nearest heading above it, which helps retrieval and shows where a fact came from.
"""
from __future__ import annotations

import re
from typing import Any

_SENTENCE = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
_HEADING = re.compile(r"^\s*(={2,}\s*(.+?)\s*={2,}|#{1,6}\s+(.+?))\s*$")


def _units(text: str) -> list[tuple[str, str]]:
    """Return (heading, sentence) pairs in order. Wikipedia '== Heading ==' and Markdown '# Heading'
    lines become headings, not text."""
    heading = ""
    out: list[tuple[str, str]] = []
    for para in re.split(r"\n\s*\n|\n(?=\s*(?:={2,}|#{1,6}\s))", text):
        lines = para.strip().splitlines()
        body: list[str] = []
        for line in lines:
            m = _HEADING.match(line)
            if m:
                heading = (m.group(2) or m.group(3) or "").strip()
            else:
                body.append(line.strip())
        joined = " ".join(b for b in body if b)
        for s in _SENTENCE.split(joined):
            s = s.strip()
            if s:
                out.append((heading, s))
        if joined:
            out.append((heading, "\n"))  # paragraph end marker: a good place to break
    return out


def chunk_text(text: str, chunk_words: int = 300, overlap_words: int = 50) -> list[dict[str, Any]]:
    """Group sentences into chunks of about `chunk_words` words. The next chunk starts with the last
    sentences of the previous one, about `overlap_words` words, so a fact on a boundary stays whole."""
    units = _units(text)
    chunks: list[dict[str, Any]] = []
    cur: list[tuple[str, str]] = []
    words = 0

    def flush() -> None:
        sents = [s for _, s in cur if s != "\n"]
        if sents:
            heading = next((h for h, s in cur if s != "\n"), "")
            chunks.append({"ord": len(chunks), "heading": heading, "text": " ".join(sents)})

    i = 0
    while i < len(units):
        h, s = units[i]
        if s == "\n":
            # Break at a paragraph end once the chunk is reasonably full.
            if words >= chunk_words * 0.7:
                flush()
                cur, words = _overlap(cur, overlap_words)
            i += 1
            continue
        n = len(s.split())
        if cur and words + n > chunk_words:
            flush()
            cur, words = _overlap(cur, overlap_words)
        cur.append((h, s))
        words += n
        i += 1
    # Only flush the tail if it adds something beyond the overlap already in the previous chunk.
    tail = [s for _, s in cur if s != "\n"]
    if tail and (not chunks or not chunks[-1]["text"].endswith(" ".join(tail))):
        flush()
    return chunks


def _overlap(cur: list[tuple[str, str]], overlap_words: int) -> tuple[list[tuple[str, str]], int]:
    kept: list[tuple[str, str]] = []
    words = 0
    for h, s in reversed(cur):
        if s == "\n":
            continue
        n = len(s.split())
        if words + n > overlap_words:
            break
        kept.insert(0, (h, s))
        words += n
    return kept, words
