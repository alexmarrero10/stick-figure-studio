"""Turn text into vectors with Google's Gemini embedding model (free tier, GEMINI_API_KEY).

Kept behind a tiny interface (`embed(texts, task)`) so another provider can be swapped in by config.
The public site must use the same model and dimension, or its searches won't match the stored vectors.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from pipeline import procs

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
DEFAULT_MODEL = "gemini-embedding-001"
DIMENSIONS = 768
BATCH = 100  # the API's limit per batch request
# Free tier: 30K tokens and 100 requests a minute (each text in a batch may count as a request).
# Stay under both with room to spare, across every call in this process.
BATCH_TOKENS = 20_000
MINUTE_TOKENS = 24_000
MINUTE_TEXTS = 90
_sent: list[tuple[float, int, int]] = []  # (time, tokens, texts) sent in the last minute
_lock = threading.Lock()


class EmbeddingError(RuntimeError):
    pass


def embed(texts: list[str], api_key: str, task: str = "RETRIEVAL_DOCUMENT", model: str = DEFAULT_MODEL,
          dims: int = DIMENSIONS, client: httpx.Client | None = None, retries: int = 5) -> list[list[float]]:
    """Embed texts in batches. `task` is RETRIEVAL_DOCUMENT for stored chunks and RETRIEVAL_QUERY for
    searches. Waits and retries when the free tier says "too many requests"."""
    if not api_key:
        raise EmbeddingError("GEMINI_API_KEY is not set. Add it on the Settings page.")
    own = client is None
    client = client or httpx.Client(timeout=60)
    out: list[list[float]] = []
    try:
        for batch in batches(texts):
            procs.check()
            _wait_for_room(sum(map(tokens, batch)), len(batch))
            body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                                  "taskType": task, "outputDimensionality": dims} for t in batch]}
            out.extend(_post(client, model, api_key, body, retries))
    finally:
        if own:
            client.close()
    return out


def tokens(text: str) -> int:
    """Rough token count. English is about 4 characters per token; counting 3 overestimates to be safe."""
    return len(text) // 3 + 1


def batches(texts: list[str]) -> list[list[str]]:
    """Group texts into batches of at most BATCH texts and BATCH_TOKENS tokens."""
    out: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for t in texts:
        n = tokens(t)
        if cur and (len(cur) >= BATCH or size + n > BATCH_TOKENS):
            out.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += n
    if cur:
        out.append(cur)
    return out


def _wait_for_room(n_tokens: int, n_texts: int) -> None:
    """Sleep until sending this batch keeps the last minute under the free tier's limits."""
    while True:
        with _lock:
            now = time.monotonic()
            _sent[:] = [s for s in _sent if now - s[0] < 60]
            used_tokens = sum(s[1] for s in _sent)
            used_texts = sum(s[2] for s in _sent)
            if not _sent or (used_tokens + n_tokens <= MINUTE_TOKENS and used_texts + n_texts <= MINUTE_TEXTS):
                _sent.append((now, n_tokens, n_texts))
                return
            wait = 60 - (now - _sent[0][0]) + 0.1
        time.sleep(min(wait, 1.0))  # short naps so Stop still works
        procs.check()


def _post(client: httpx.Client, model: str, api_key: str, body: dict[str, Any], retries: int) -> list[list[float]]:
    wait = 2.0
    for attempt in range(retries + 1):
        r = client.post(API.format(model=model), json=body, headers={"x-goog-api-key": api_key})
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries:
                break
            time.sleep(wait)
            wait = min(wait * 2, 60)
            continue
        if r.status_code != 200:
            raise EmbeddingError(f"Gemini embeddings failed ({r.status_code}): {r.text[:300]}")
        return [_normalize(e["values"]) for e in r.json()["embeddings"]]
    raise EmbeddingError("Gemini embeddings kept saying 'too many requests'. Wait a minute and try again.")


def _normalize(v: list[float]) -> list[float]:
    """Gemini only normalizes full 3072-dim vectors; shorter ones must be scaled to length 1 for cosine."""
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v] if n else v
