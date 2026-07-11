from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CacheEntry:
    cache_key: str
    tenant_id: str
    query: str
    answer: str
    embedding: list[float]
    doc_ids: list[str] = field(default_factory=list)


@dataclass
class CacheHit:
    answer: str
    similarity: float
    level: str  # "L1" | "L2"
    cache_key: str
