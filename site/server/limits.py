"""Protection against abuse: per-visitor and site-wide limits, and a cache for repeated questions.

Kept in memory, which is fine for one small server. A restart resets the counters.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class RateLimiter:
    """Allows `per_hour` and `per_day` events per visitor, and `global_per_day` in total."""

    def __init__(self, per_hour: int, per_day: int, global_per_day: int, clock=time.time):
        self.per_hour, self.per_day, self.global_per_day = per_hour, per_day, global_per_day
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, visitor: str) -> str | None:
        """Record one event. Returns None if allowed, else a short reason ('hour', 'day' or 'site')."""
        now = self.clock()
        with self._lock:
            while self._global and now - self._global[0] > 86400:
                self._global.popleft()
            hits = self._hits.setdefault(visitor, deque())
            while hits and now - hits[0] > 86400:
                hits.popleft()
            if len(self._global) >= self.global_per_day:
                return "site"
            if len(hits) >= self.per_day:
                return "day"
            if sum(1 for t in hits if now - t <= 3600) >= self.per_hour:
                return "hour"
            hits.append(now)
            self._global.append(now)
            if len(self._hits) > 50000:  # forget the oldest visitors so memory stays small
                for k in list(self._hits)[:10000]:
                    del self._hits[k]
            return None


class AnswerCache:
    """Answers to first questions (no chat history), keyed by video and the normalized question."""

    def __init__(self, size: int = 1000, ttl_s: float = 7 * 86400, clock=time.time):
        self.size, self.ttl, self.clock = size, ttl_s, clock
        self._items: OrderedDict[tuple[int, str], tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(video_id: int, question: str) -> tuple[int, str]:
        return video_id, " ".join("".join(ch for ch in question.lower() if ch.isalnum() or ch.isspace()).split())

    def get(self, video_id: int, question: str) -> str | None:
        k = self.key(video_id, question)
        with self._lock:
            item = self._items.get(k)
            if not item or self.clock() - item[0] > self.ttl:
                return None
            self._items.move_to_end(k)
            return item[1]

    def put(self, video_id: int, question: str, answer: str) -> None:
        with self._lock:
            self._items[self.key(video_id, question)] = (self.clock(), answer)
            self._items.move_to_end(self.key(video_id, question))
            while len(self._items) > self.size:
                self._items.popitem(last=False)
