from __future__ import annotations

from clients.postgres_client import PostgresClient
from raglog import get_logger
from models import ChangeSet, RawDocument

log = get_logger("change_detect")


def detect_changes(
    tenant_id: str, current_docs: list[RawDocument], pg: PostgresClient | None = None
) -> ChangeSet:
    """Compare freshly ingested docs against stored content_hash to build a changeset.

    - added:    doc_id present now, absent before
    - modified: doc_id present in both but content_hash differs
    - deleted:  doc_id stored before, absent now
    Unchanged docs are skipped so downstream index build only touches deltas.
    """
    pg = pg or PostgresClient()
    stored = pg.get_hashes(tenant_id)
    current = {d.doc_id: d.content_hash for d in current_docs}

    cs = ChangeSet()
    for doc_id, h in current.items():
        if doc_id not in stored:
            cs.added.append(doc_id)
        elif stored[doc_id] != h:
            cs.modified.append(doc_id)

    for doc_id in stored:
        if doc_id not in current:
            cs.deleted.append(doc_id)

    log.info(
        "changeset_built",
        tenant_id=tenant_id,
        added=len(cs.added),
        modified=len(cs.modified),
        deleted=len(cs.deleted),
        skipped=len(current) - len(cs.added) - len(cs.modified),
    )
    return cs
