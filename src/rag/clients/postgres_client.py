from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from config import get_settings
from models import DocStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    object_key   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'pending',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);
"""


class PostgresClient:
    """Document metadata store: source of truth for content_hash change detection."""

    def __init__(self) -> None:
        self._dsn = get_settings().pg_dsn

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def init_schema(self) -> None:
        with self._conn() as c:
            c.execute(_SCHEMA)

    def get_hashes(self, tenant_id: str) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT doc_id, content_hash FROM documents WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        return {r["doc_id"]: r["content_hash"] for r in rows}

    def upsert_document(
        self, doc_id: str, tenant_id: str, object_key: str, content_hash: str,
        status: DocStatus = DocStatus.PENDING,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO documents (doc_id, tenant_id, object_key, content_hash, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (doc_id) DO UPDATE SET "
                "content_hash = EXCLUDED.content_hash, object_key = EXCLUDED.object_key, "
                "version = documents.version + 1, status = EXCLUDED.status, updated_at = now()",
                (doc_id, tenant_id, object_key, content_hash, status.value),
            )

    def set_status(self, doc_id: str, status: DocStatus) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE documents SET status = %s, updated_at = now() WHERE doc_id = %s",
                (status.value, doc_id),
            )

    def delete_documents(self, doc_ids: list[str]) -> None:
        if not doc_ids:
            return
        with self._conn() as c:
            c.execute("DELETE FROM documents WHERE doc_id = ANY(%s)", (doc_ids,))
