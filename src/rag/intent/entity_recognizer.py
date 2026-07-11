from __future__ import annotations

from functools import lru_cache

from intent.entity_dict import EntityDictionary
from intent.types import EntityMatch
from raglog import get_logger

log = get_logger("entity_recognizer")


class EntityRecognizer:
    """Recognizes product/term entities in a query by matching against the tenant's
    Redis dictionary and resolving aliases to canonical names + collection_id (task 4.3).

    Unknown entities are simply omitted (no error), so downstream falls back to global
    retrieval per the spec's "unknown entity handling" scenario.
    """

    def __init__(self, dictionary: EntityDictionary | None = None, cache_ttl_calls: int = 1024) -> None:
        self._dict = dictionary or EntityDictionary()
        self._cache_ttl_calls = cache_ttl_calls

    def _aliases(self, tenant_id: str) -> dict[str, str]:
        # Alias table is small and changes only on offline dictionary updates; cache per tenant.
        return _cached_aliases(self._dict, tenant_id)

    def recognize(self, tenant_id: str, query: str) -> list[EntityMatch]:
        aliases = self._aliases(tenant_id)
        if not aliases:
            return []
        lowered = query.lower()
        seen: set[str] = set()
        matches: list[EntityMatch] = []
        # Match longer aliases first to prefer specific over generic surface forms.
        for alias in sorted(aliases, key=len, reverse=True):
            if alias and alias in lowered:
                canonical = aliases[alias]
                if canonical in seen:
                    continue
                seen.add(canonical)
                meta = self._dict.meta(tenant_id, canonical) or {}
                matches.append(EntityMatch(name=canonical, collection_id=meta.get("collection_id")))
        return matches

    @staticmethod
    def clear_cache() -> None:
        _cached_aliases.cache_clear()


@lru_cache(maxsize=256)
def _cached_aliases(dictionary: EntityDictionary, tenant_id: str) -> dict[str, str]:
    return dictionary.all_aliases(tenant_id)
