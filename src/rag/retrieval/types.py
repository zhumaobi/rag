from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    text: str
    score: float
    source: str = ""  # "dense" | "sparse" | "graph" | "rrf" | "rerank"

    def key(self) -> str:
        return self.chunk_id


@dataclass
class RetrievalResult:
    """Unified retrieval output consumed by the LLM layer.

    For Intent-2 the same chunk list is also grouped by product in `groups` so the LLM
    prompt can label each product's evidence; for Intent-3, `graph_paths` carries the
    traversed relationship chains for grounded relationship answers.
    """

    chunks: list[RetrievedChunk] = field(default_factory=list)
    groups: dict[str, list[RetrievedChunk]] = field(default_factory=dict)
    graph_paths: list[list[str]] = field(default_factory=list)
    degraded: bool = False  # True when a richer strategy fell back (e.g. graph -> vector)

    def to_dict(self) -> dict:
        return {
            "chunks": [c.__dict__ for c in self.chunks],
            "groups": {k: [c.__dict__ for c in v] for k, v in self.groups.items()},
            "graph_paths": self.graph_paths,
            "degraded": self.degraded,
        }
