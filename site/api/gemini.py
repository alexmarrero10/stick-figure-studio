"""Gemini calls for the site: query embeddings (must match the studio's model and size) and streamed answers.

Use a Google key from a project with billing turned off: the free tier then can only refuse with
"too many requests", never charge money.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Any, Iterator

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
EMBED_MODEL = "gemini-embedding-001"  # same as backend/pipeline/embeddings.py
DIMENSIONS = 768
CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-flash-lite-latest")


class GeminiError(RuntimeError):
    pass


class Gemini:
    def __init__(self, api_key: str, client: httpx.Client | None = None, cache_size: int = 2000):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        self.key = api_key
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.key}

    def embed_query(self, text: str) -> list[float]:
        """Embedding for a search or question. Repeated searches come from a small cache."""
        key = " ".join(text.lower().split())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        r = self.client.post(f"{BASE}/{EMBED_MODEL}:embedContent", headers=self._headers(), json={
            "model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_QUERY", "outputDimensionality": DIMENSIONS})
        if r.status_code == 429:
            raise GeminiError("busy")
        if r.status_code != 200:
            raise GeminiError(f"embedding failed ({r.status_code})")
        v = r.json()["embedding"]["values"]
        n = sum(x * x for x in v) ** 0.5
        v = [x / n for x in v] if n else v
        self._cache[key] = v
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return v

    def stream_answer(self, system: str, contents: list[dict[str, Any]], max_tokens: int = 500) -> Iterator[str]:
        """Stream the answer's text pieces."""
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3}}
        with self.client.stream("POST", f"{BASE}/{CHAT_MODEL}:streamGenerateContent", params={"alt": "sse"},
                                headers=self._headers(), json=body) as r:
            if r.status_code == 429:
                raise GeminiError("busy")
            if r.status_code != 200:
                r.read()
                raise GeminiError(f"answer failed ({r.status_code})")
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if part.get("text") and not part.get("thought"):
                            yield part["text"]
