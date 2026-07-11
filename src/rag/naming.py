from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shadow_name(base: str) -> str:
    return f"{base}__shadow"


def active_name(base: str) -> str:
    return f"{base}__active"


def collection_for_tenant(tenant_id: str) -> str:
    return f"docs_{tenant_id}"


def shared_collection() -> str:
    return "docs_shared_small"
