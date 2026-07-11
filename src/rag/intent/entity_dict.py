from __future__ import annotations

import json

from config import get_settings
from raglog import get_logger

log = get_logger("entity_dict")

# Redis layout (per tenant, so aliases can differ across tenants):
#   entitydict:{tenant}:alias -> HASH  alias(lower) -> canonical_name
#   entitydict:{tenant}:meta  -> HASH  canonical_name -> json{collection_id, entity_type}


class EntityDictionary:
    """Product entity dictionary backed by Redis Hash (task 4.2).

    Stores canonical names plus alias/abbreviation mappings and each canonical name's
    target collection_id, so entity recognition (4.3) can resolve an alias straight to
    the Milvus collection for Intent-1 targeted retrieval.
    """

    def __init__(self, client: "redis.Redis | None" = None) -> None:
        if client is None:
            import redis

            client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        self._r = client

    def _alias_key(self, tenant_id: str) -> str:
        return f"entitydict:{tenant_id}:alias"

    def _meta_key(self, tenant_id: str) -> str:
        return f"entitydict:{tenant_id}:meta"

    def register(
        self,
        tenant_id: str,
        canonical: str,
        collection_id: str | None,
        aliases: list[str] | None = None,
        entity_type: str = "product",
    ) -> None:
        pipe = self._r.pipeline()
        pipe.hset(
            self._meta_key(tenant_id),
            canonical,
            json.dumps({"collection_id": collection_id, "entity_type": entity_type}),
        )
        # Canonical name is its own alias for uniform lookup.
        for alias in {canonical, *(aliases or [])}:
            pipe.hset(self._alias_key(tenant_id), alias.lower(), canonical)
        pipe.execute()
        log.info("entity_registered", tenant_id=tenant_id, canonical=canonical)

    def bulk_register(self, tenant_id: str, entries: list[dict]) -> int:
        for e in entries:
            self.register(
                tenant_id,
                e["canonical"],
                e.get("collection_id"),
                e.get("aliases", []),
                e.get("entity_type", "product"),
            )
        return len(entries)

    def resolve_alias(self, tenant_id: str, alias: str) -> str | None:
        return self._r.hget(self._alias_key(tenant_id), alias.lower())

    def all_aliases(self, tenant_id: str) -> dict[str, str]:
        return self._r.hgetall(self._alias_key(tenant_id))

    def meta(self, tenant_id: str, canonical: str) -> dict | None:
        raw = self._r.hget(self._meta_key(tenant_id), canonical)
        return json.loads(raw) if raw else None
