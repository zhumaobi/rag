from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Intent(str, enum.Enum):
    """Three intent classes driving downstream retrieval routing.

    PRECISE  (Intent-1): precise product/term Q&A -> single-doc targeted retrieval, 7B pool.
    COMPARE  (Intent-2): multi-product comparison -> parallel multi-path retrieval, 14B pool.
    RELATION (Intent-3): concept/relationship clarification -> knowledge-graph traversal, 14B pool.
    """

    PRECISE = "Intent-1"
    COMPARE = "Intent-2"
    RELATION = "Intent-3"


@dataclass
class EntityMatch:
    name: str  # canonical product / term name
    collection_id: str | None  # target Milvus collection, None -> global retrieval


@dataclass
class IntentResult:
    intent: Intent
    confidence: float
    entities: list[EntityMatch] = field(default_factory=list)
    routing_hint: str = ""
    source: str = "rule"  # "rule" | "model"
    time_sensitive: bool = False

    def to_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "confidence": round(self.confidence, 4),
            "entities": [{"name": e.name, "collection_id": e.collection_id} for e in self.entities],
            "routing_hint": self.routing_hint,
            "source": self.source,
            "time_sensitive": self.time_sensitive,
        }
