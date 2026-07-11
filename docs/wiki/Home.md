# Enterprise RAG System — Wiki

A multi-tenant, enterprise knowledge-base **Retrieval-Augmented Generation (RAG)** system designed for high throughput (target ~10k QPS) and large-scale document storage. The primary domain is Chinese-language internal product documentation (order centers, payment gateways, risk engines, etc.).

## What this system does

Given a user question scoped to a tenant, it:
1. Embeds the query once (`BAAI/bge-m3`, 1024-dim).
2. Recognizes **intent** (two-stage: rules → MiniLM classifier).
3. Checks a **two-level semantic cache** (in-memory L1 → Redis VSS L2).
4. Runs **intent-routed hybrid retrieval** (dense + sparse + knowledge graph).
5. Generates an answer via a **tiered vLLM cluster** (7B / 14B pools) with a multi-level degradation chain.
6. Stores the answer back into the cache (fire-and-forget).

Offline, a **state-machine-driven pipeline** ingests documents from object storage, detects changes, chunks/embeds, builds three indices (vector, BM25, knowledge graph) on shadow collections, validates, then performs an **atomic switch**.

## Wiki pages

| Page | Contents |
|------|----------|
| [Architecture](./Architecture.md) | End-to-end architecture, online query path, offline pipeline, key design decisions |
| [Getting Started](./Getting-Started.md) | Install, run the mock query CLI, run tests, config reference |
| [Intent Recognition](./Module-Intent.md) | `intent/` — two-stage classification, rules, entities |
| [Hybrid Retrieval](./Module-Retrieval.md) | `retrieval/` — intent routing, RRF fusion, rerank, graph |
| [LLM Serving](./Module-Serving.md) | `serving/` — dispatcher, model pools, degradation, prefix cache |
| [Semantic Cache](./Module-Cache.md) | `cache/` — L1/L2 cache, similarity, invalidation |
| [Offline Index Pipeline](./Module-Pipeline.md) | `pipeline/` — ingest → chunk → embed → index → switch |
| [Query Facade](./Module-Query.md) | `query/` — orchestration, wiring, CLI, fakes |
| [Infrastructure Clients](./Module-Clients.md) | `clients/` — Milvus, ES, Neo4j, Redis, Postgres, S3 |
| [Evaluation](./Module-Evaluation.md) | `evaluation/` — 4-level eval, release gate |
| [Observability](./Module-Observability.md) | `observability/` — metrics, tracing, alerts |
| [Deployment & Rollout](./Module-Deploy.md) | `deploy/` — canary rollout controller |
| [Domain Model & Config](./Reference-Core.md) | `models.py`, `config.py`, `naming.py`, `raglog.py` |

## Tech stack at a glance

- **Language:** Python 3.12
- **Vector DB:** Milvus 2.4.15 (HNSW, per-tenant collections, alias-based atomic switch)
- **Sparse search:** Elasticsearch 8.x (BM25)
- **Graph DB:** Neo4j 5.x (Cypher, tenant-label isolation)
- **Cache:** Redis (RedisSearch VSS) + in-process LRU
- **Metadata:** PostgreSQL (psycopg 3)
- **Object storage:** S3-compatible (MinIO)
- **LLM:** Qwen2.5-7B / Qwen2.5-14B via vLLM (OpenAI-compatible API)
- **Embeddings:** BAAI/bge-m3 via sentence-transformers
- **Config/validation:** pydantic 2.x + pydantic-settings
- **Logging:** structlog (JSON, contextvars) with stdlib fallback
- **Metrics/tracing:** prometheus_client + OpenTelemetry (both optional)
- **Spec management:** OpenSpec (`openspec/`)

## Repository layout

```
rag/
├── docker-compose.yml        # Milvus stack (etcd + MinIO + Milvus standalone)
├── requirements.txt
├── openspec/                 # Spec-driven dev artifacts (11 capability specs)
├── data/                     # Datasets (eval/, generated intent training data)
├── tests/                    # Integration, isolation, fault-injection, perf, rollout
└── src/rag/                  # Application source (flat root-relative imports)
    ├── config.py  models.py  naming.py  raglog.py
    ├── cache/  clients/  deploy/  evaluation/  intent/
    ├── observability/  pipeline/  query/  retrieval/  serving/
    └── docs/wiki/            # ← you are here
```

> **Import convention:** the package runs with `src/rag` on `PYTHONPATH` and uses flat imports (`from intent.types import ...`), not `rag.*`.
