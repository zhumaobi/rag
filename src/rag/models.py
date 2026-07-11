from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class ChangeType(str, enum.Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class DocStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class RawDocument:
    doc_id: str
    tenant_id: str
    key: str  # object storage key
    content: str
    content_hash: str
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    tenant_id: str
    ordinal: int
    text: str
    token_count: int
    embedding: Optional[list[float]] = None


@dataclass
class ChangeSet:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)

    @property
    def upserted(self) -> list[str]:
        return self.added + self.modified


class RelationType(str, enum.Enum):
    BELONGS_TO = "属于"
    DEPENDS_ON = "依赖"
    REPLACES = "替代"
    INTEGRATES = "集成"
    EXPLAINS = "概念解释"


@dataclass
class Entity:
    name: str
    entity_type: str
    doc_ids: set[str] = field(default_factory=set)
    embedding: Optional[list[float]] = None


@dataclass
class Relation:
    source: str
    target: str
    relation_type: RelationType
    confidence: float
    doc_id: str
