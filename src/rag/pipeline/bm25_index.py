from __future__ import annotations

from clients.es_client import ESClient
from raglog import get_logger
from models import Chunk

log = get_logger("bm25_index")

_BULK_BATCH = 2000


class BM25IndexBuilder:
    """Bulk-indexes chunks into a Shadow ES index for sparse retrieval (task 3.5)."""

    def __init__(self, es: ESClient | None = None) -> None:
        self._es = es or ESClient()

    def build_shadow(self, shadow_index: str, chunks: list[Chunk]) -> int:
        self._es.create_shadow(shadow_index)
        rows: list[dict] = []
        written = 0
        for chunk in chunks:
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "tenant_id": chunk.tenant_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                }
            )
            if len(rows) >= _BULK_BATCH:
                written += self._es.bulk_index(shadow_index, rows)
                rows = []
        if rows:
            written += self._es.bulk_index(shadow_index, rows)
        self._es.refresh(shadow_index)
        log.info("bm25_shadow_built", index=shadow_index, chunks=written)
        return written
