from __future__ import annotations

import threading
from collections import OrderedDict

from cache.types import CacheEntry, CacheHit
from cache.similarity import cosine


class L1Cache:
    """Per-instance in-memory LRU semantic cache (task 6.1).

    Holds up to `capacity` recent entries (default ~1000). Lookup does a linear cosine
    scan over cached embeddings — cheap at this size (<1ms) and avoids a Redis round-trip.
    Namespaced by tenant_id so entries never cross tenants. Thread-safe for the async
    server's worker threads.
    """

    def __init__(self, capacity: int = 1000, threshold: float = 0.92) -> None:
        self._capacity = capacity
        self._threshold = threshold
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, tenant_id: str, embedding: list[float]) -> CacheHit | None:
        best: CacheEntry | None = None
        best_sim = 0.0
        with self._lock:
            for entry in self._entries.values():
                if entry.tenant_id != tenant_id:
                    continue
                sim = cosine(embedding, entry.embedding)
                if sim > best_sim:
                    best_sim, best = sim, entry
            if best is not None and best_sim > self._threshold:
                self._entries.move_to_end(best.cache_key)  # mark most-recently-used
                return CacheHit(answer=best.answer, similarity=best_sim, level="L1", cache_key=best.cache_key)
        return None

    def put(self, entry: CacheEntry) -> None:
        with self._lock:
            self._entries[entry.cache_key] = entry
            self._entries.move_to_end(entry.cache_key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)  # evict least-recently-used

    def evict_keys(self, keys: list[str]) -> None:
        with self._lock:
            for k in keys:
                self._entries.pop(k, None)

    def __len__(self) -> int:
        return len(self._entries)
