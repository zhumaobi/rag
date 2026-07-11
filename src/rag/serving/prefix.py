from __future__ import annotations

from serving.types import Instance

# Shared system prompt is placed first and kept byte-identical across a tenant's requests
# so vLLM's automatic prefix caching reuses its KV blocks. The tenant instruction follows,
# then the per-request query. Only the tail (query + context) differs between requests.
_SYSTEM_PROMPT = (
    "你是企业内部知识库助手。仅基于提供的文档内容回答，"
    "文档中没有的信息不要推断，不要编造。回答简洁准确，"
    "涉及多个产品时分别标注来源。"
)


def build_prompt(system_prefix: str, context: str, query: str) -> str:
    """Assemble a prompt with a stable shared prefix for maximal Prefix KV Cache reuse.

    `system_prefix` = global system prompt + tenant instruction (~300 tokens), constant
    per tenant. Keeping it verbatim and leading is what lets same-tenant requests share
    prefill KV blocks (task 7.2).
    """
    prefix = system_prefix or _SYSTEM_PROMPT
    return f"{prefix}\n\n[参考文档]\n{context}\n\n[问题]\n{query}\n\n[回答]\n"


def default_system_prefix(tenant_instruction: str = "") -> str:
    if tenant_instruction:
        return f"{_SYSTEM_PROMPT}\n[租户须知]{tenant_instruction}"
    return _SYSTEM_PROMPT


def record_prefix_lookup(instance: Instance, hit: bool) -> None:
    """Track per-instance prefix cache hit rate (spec target >= 80% for same-tenant)."""
    instance.prefix_lookups += 1
    if hit:
        instance.prefix_hits += 1
