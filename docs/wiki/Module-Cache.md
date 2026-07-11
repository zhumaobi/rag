# Semantic Cache (`cache/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

A two-level semantic cache that serves near-duplicate queries without a full RAG pass. Similarity is measured by cosine over query embeddings; a hit requires cosine > **0.92**.

## Orchestrator — `cache/service.py`

`SemanticCache` (`cache/service.py:18`) coordinates L1, L2, the Redis reverse index, and a hit-rate monitor. All collaborators are injected; threshold defaults to `_SIM_THRESHOLD = 0.92`.

### Read path — `lookup()` (`cache/service.py:45`)

```
time_sensitive? ──► record miss, return None (force full RAG)
   │ no
   ▼
L1.get(tenant, embedding)  ──hit──► record hit, return CacheHit(level="L1")
   │ miss
   ▼
L2.get(tenant, embedding, threshold)  ──hit──► promote into L1, return CacheHit(level="L2")
   │ miss
   ▼
record miss, return None
```

An L2 hit is **promoted into L1** so repeat asks are served sub-millisecond.

### Write path — `store_async()` (`cache/service.py:73`)

Non-blocking background write via `asyncio.to_thread`. Callers schedule it with `asyncio.create_task` **after** returning to the user (see `query/service.py:103`). `_store` writes to L2, L1, and — when doc_ids are present — maintains the **doc_id → cache_key reverse index** in Redis (`add_cache_ref`) for precise invalidation.

Cache key = `sha1(f"{tenant_id}:{query}")` (`cache/service.py:41`).

## L1 — in-process LRU (`cache/l1_cache.py`)

- Per-instance, in-memory, tenant-namespaced, ~1000 entries.
- `get()` does a linear cosine scan filtered by tenant, threshold 0.92.
- Thread-safe via `threading.Lock`.
- Methods: `get()`, `put(entry)`, `evict_keys(keys)`.

## L2 — Redis VSS (`cache/l2_cache.py`)

Redis (RedisSearch) vector similarity search over stored query embeddings, tenant-namespaced. Returns the best entry above threshold as a `CacheHit`.

## Invalidation

When the offline pipeline switches an index, `CacheInvalidator` (`pipeline/cache_invalidate.py`) uses the doc_id → cache_key reverse index to **precisely evict** only cache entries whose provenance includes a changed document — no blanket flush.

## Supporting files

| File | Purpose |
|------|---------|
| `cache/service.py` | `SemanticCache` — two-level orchestrator |
| `cache/l1_cache.py` | `L1Cache` — in-memory LRU cosine cache |
| `cache/l2_cache.py` | `L2Cache` — Redis VSS cache |
| `cache/similarity.py` | Pure-Python `cosine(a, b)` (0.0 for empty/zero/mismatched) |
| `cache/types.py` | `CacheEntry`, `CacheHit(answer, similarity, level, cache_key)` |
| `cache/metrics.py` | `HitRateMonitor` — `hit_rate()`, `check_alert()` (target ≥ 40%) |
