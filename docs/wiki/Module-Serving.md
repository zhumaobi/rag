# LLM Serving (`serving/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Turns a retrieval context + query into a generated answer via a tiered vLLM cluster, with tenant-affinity load balancing, prefix-cache optimization, and a four-level degradation chain.

## Entry point

`Dispatcher.generate(req, context, fallback_chunks_text, cached_answer)` — `serving/dispatcher.py:63`. Returns a `GenResult`.

Responsibilities (`serving/dispatcher.py:26`):
- **Tiered routing (7.4):** select the pool tier by intent.
- **Queue-timeout degradation (7.5):** intent-specific action when the queue budget is exceeded.
- **L1→L4 circuit-breaker chain (7.6):** progressive fallback on instance failure.

## Tiered routing

`tier_for_intent()` (`serving/degradation.py:40`):
- **Intent-1 → `PoolTier.SMALL` (7B)**
- **Intent-2 / Intent-3 → `PoolTier.LARGE` (14B)**

`_select_tier()` (`dispatcher.py:51`) additionally applies **L2 downgrade**: if the LARGE pool has no healthy instances, or the least-loaded instance's `pending_tokens > 12288` (`_LARGE_POOL_SATURATION_TOKENS`), it downgrades to the SMALL pool.

## Degradation chain

| Level | Trigger | Action |
|-------|---------|--------|
| **L1** | Instance error / breaker tripped | Mark `UNHEALTHY`, drop from routing, retry another instance (`_pick_allowed`, dispatcher.py:116) |
| **L2** | LARGE pool saturated | Downgrade Intent-2/3 to the 7B pool |
| **L3** | Queue/inference timeout or no capacity | Skip LLM, return retrieved chunks (Intent-1) or pure-vector context (Intent-3) |
| **L4** | Total failure | Return a cached approximate answer (or empty) |

**Queue budgets** (`serving/degradation.py:9`): Intent-1 = 2s, Intent-2 = 5s, Intent-3 = 8s. On timeout, `on_queue_timeout()` maps intent → action:
- Intent-1 → `return_chunks` (top-3 retrieval)
- Intent-3 → `skip_graph` (pure-vector context to LLM)
- Intent-2 → `downgrade_tier` (14B → 7B)

The generation flow: pick instance → `build_prompt` → `asyncio.wait_for(client.generate, timeout=budget)`; on success record breaker success + prefix lookup; on `TimeoutError` apply the timeout action; on other exceptions trip the breaker and mark the instance unhealthy (`dispatcher.py:86-114`).

## Model pool & load balancing

- `serving/model_pool.py` — `ModelPool` manages `Instance`s per tier; `healthy()`, `mark()`, `select()`, plus `DEFAULT_POOL_CONFIGS`.
- `serving/router.py` — `LoadBalancer` with a consistent-hash ring for **tenant affinity** (maximizes prefix cache reuse) and `pending_tokens` balancing.
- `serving/circuit_breaker.py` — per-instance `CircuitBreaker` (`allow()`, `record_success()`, `record_failure()`).
- `serving/vllm_client.py` — `VLLMClient`, async HTTP to the vLLM OpenAI-compatible API.
- `serving/autoscaler.py` — predictive pre-warm + reactive scale-up (GPU mem > 85% for 60s), graceful drain scale-down (util < 30% for 10min).
- `serving/loadtest.py` — `run_load(qps, duration_s, small_n, large_n)` harness.

## Prefix KV cache — `serving/prefix.py`

- `build_prompt(system_prefix, context, query)` — stable shared prefix + reference docs + query, so vLLM reuses the KV cache for the prefix.
- `_SYSTEM_PROMPT` — Chinese instruction ("answer only from documents, don't infer").
- `default_system_prefix(tenant_instruction)` — global prompt + optional tenant instruction.
- `record_prefix_lookup(instance, hit)` — tracks per-instance prefix hit rate (target ≥ 80%).

## Types — `serving/types.py`

- `PoolTier` = `SMALL("7B")` | `LARGE("14B")`.
- `InstanceState` = `STARTING|HEALTHY|DRAINING|UNHEALTHY|STOPPED`.
- `Instance(instance_id, tier, endpoint, state, pending_tokens, inflight, gpu_mem_util, prefix_hits, prefix_lookups)` with `healthy` and `prefix_hit_rate` properties.
- `GenRequest(tenant_id, intent, prompt, system_prefix, max_tokens, est_prompt_tokens)`.
- `GenResult(text, tier, instance_id, downgraded, degraded_level, prefix_cache_hit, meta)`.

## Files

| File | Purpose |
|------|---------|
| `serving/dispatcher.py` | `Dispatcher` — routing, timeout & degradation orchestration |
| `serving/degradation.py` | Queue budgets, `on_queue_timeout()`, `tier_for_intent()` |
| `serving/model_pool.py` | `ModelPool`, `DEFAULT_POOL_CONFIGS` |
| `serving/router.py` | `LoadBalancer` — consistent-hash tenant affinity |
| `serving/circuit_breaker.py` | Per-instance circuit breaker |
| `serving/vllm_client.py` | Async vLLM HTTP client |
| `serving/autoscaler.py` | Predictive + reactive autoscaling |
| `serving/prefix.py` | Prompt assembly + prefix cache tracking |
| `serving/loadtest.py` | Load-test harness |
| `serving/types.py` | Serving domain types |
