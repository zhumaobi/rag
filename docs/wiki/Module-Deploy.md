# Deployment & Rollout (`deploy/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Canary → ramp → full rollout with automatic health-gated rollback. Implemented in `deploy/rollout.py`.

## RolloutController — `deploy/rollout.py:40`

Progressive traffic shifting with fast rollback. Traffic is split by routing a `percent` of requests to the new version; each observation window re-checks the health gate.

### Phases (`RolloutPhase`)

```
IDLE → CANARY (10%) → RAMPING (25% → 50%) → FULL (100%)
   └──────────────── any breach ────────────────► ROLLED_BACK (0%)
```

Default ramp steps: `(10, 25, 50, 100)`.

### Key methods

| Method | Behavior |
|--------|----------|
| `start_canary()` | Enter CANARY at 10% |
| `route_to_new(request_hash)` | Deterministic split: `request_hash % 100 < percent` → new version |
| `observe(metrics)` | Evaluate gate; returns `advanced` / `full` / `hold` / `rolled_back` |
| `rollback(reason)` | Phase → ROLLED_BACK, percent → 0 |

`observe()` first checks for breaches; any breach triggers immediate rollback to 0%. Otherwise it advances to the next ramp step (or holds at FULL).

## Health gate — `HealthGate` (rollout.py:20)

Any breach rolls the release back to the previous version:

| Metric key | Threshold | Breach label |
|------------|-----------|--------------|
| `p99_latency_s` | > 3.0s | `p99>3s` |
| `semantic_cache_hit_rate` | < 0.40 | `cache<40%` |
| `negative_feedback_rate` | > 0.05 | `negative>5%` |
| `error_rate` | > 0.01 | `error>1%` |

## Testing

`tests/test_rollout.py` verifies the canary ramp 10%→25%→50%→100% under healthy metrics, immediate rollback to 0% on breach, and deterministic traffic splitting.

## Deployment infrastructure

`docker-compose.yml` (repo root) provisions the **Milvus stack** only — `etcd`, `minio`, and `milvus standalone` (v2.4.15). Elasticsearch, Neo4j, Redis, PostgreSQL, and the vLLM cluster are expected to be deployed separately in a real environment.
