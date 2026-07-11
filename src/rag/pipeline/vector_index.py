from __future__ import annotations

from clients.milvus_client import MilvusClient
from raglog import get_logger
from models import Chunk

log = get_logger("vector_index")

_WRITE_BATCH = 1000


class VectorIndexBuilder:
    """Writes embedded chunks into a Shadow Milvus Collection (task 3.4)."""

    def __init__(self, milvus: MilvusClient | None = None) -> None:
        self._milvus = milvus or MilvusClient()

    def build_shadow(self, shadow_collection: str, chunks: list[Chunk]) -> int:
        self._milvus.create_shadow(shadow_collection)
        rows: list[dict] = []
        written = 0
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"chunk {chunk.chunk_id} missing embedding")
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "tenant_id": chunk.tenant_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text[:8192],
                    "embedding": chunk.embedding,
                }
            )
            if len(rows) >= _WRITE_BATCH:
                self._milvus.insert(shadow_collection, rows)
                written += len(rows)
                rows = []
        if rows:
            self._milvus.insert(shadow_collection, rows)
            written += len(rows)
        self._milvus.flush_and_load(shadow_collection)
        log.info("vector_shadow_built", collection=shadow_collection, chunks=written)
        return written
