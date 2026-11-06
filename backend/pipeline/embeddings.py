"""Turn text into vectors with Google's Gemini embedding model (free tier, GEMINI_API_KEY).

Kept behind a tiny interface (`embed(texts, task)`) so another provider can be swapped in by config.
The public site must use the same model and dimension, or its searches won't match the stored vectors.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from pipeline import procs

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
DEFAULT_MODEL = "gemini-embedding-001"
DIMENSIONS = 768
BATCH = 100  # the API's limit per batch request


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
        for i in range(0, len(texts), BATCH):
            procs.check()
            batch = texts[i:i + BATCH]
            body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                                  "taskType": task, "outputDimensionality": dims} for t in batch]}
            out.extend(_post(client, model, api_key, body, retries))
    finally:
        if own:
            client.close()
    return out


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
