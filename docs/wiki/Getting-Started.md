# Getting Started

[← Home](./Home.md) · [Architecture](./Architecture.md)

How to install, run the system end-to-end without infrastructure, run the test suite, and configure real backends.

## Prerequisites

- Python 3.12
- (Optional, for real backends) Docker — to run the Milvus stack via `docker-compose.yml`

## Install

```bash
pip install -r requirements.txt
```

Key dependencies: `pymilvus`, `elasticsearch`, `neo4j`, `redis`, `psycopg[binary]`, `boto3`, `sentence-transformers`, `transformers`, `torch`, `spacy`, `tiktoken`, `pydantic`, `pydantic-settings`, `tenacity`, `structlog`.

## Run the query path (mock mode, no infra/GPU)

`build_mock()` wires the **real** intent/retrieval/serving logic with fakes for embedding, retrieval leaf clients, cache, and the LLM. Run from the source root so flat imports resolve:

```bash
cd src/rag
export PYTHONPATH=$PWD          # Git Bash on Windows; or set PYTHONPATH accordingly
python -m query "订单中心和支付网关有什么区别?" --tenant t1
```

Output includes the answer plus a diagnostics footer: `intent`, `source`, `tier`, degradation flags, `request_id`, per-hop latencies, and retrieved `doc_ids`. See [Query Facade](./Module-Query.md).

## Intent tooling

```bash
cd src/rag && export PYTHONPATH=$PWD
# Generate balanced 3-class training data
python -m intent.training_data --out ../../data/intent_train.jsonl --count 500
# Benchmark rule-layer latency (P99 target < 15ms)
python -m intent.benchmark --mode rule
```

## Run the tests

Tests import via the `rag.*` package path (e.g. `from rag.intent.types import ...`), so run them from the **repository root** with `src` on `PYTHONPATH`:

```bash
# from repo root
export PYTHONPATH=$PWD/src
pytest tests/
```

| Test file | Covers |
|-----------|--------|
| `tests/test_e2e_integration.py` | 3 intents × 50 cases; retrieval hit rate > 95% |
| `tests/test_multitenant_isolation.py` | No cross-tenant leakage; cache namespace isolation |
| `tests/test_fault_injection.py` | LLM failure → L3/L4 degradation, timeout → return-chunks |
| `tests/test_perf_smoke.py` | 1000 QPS burst, asserts P99 < 3s |
| `tests/test_rollout.py` | Canary ramp + rollback + deterministic split |
| `tests/conftest.py` | Shared fakes: `FakeEmbedder`, `FakeIntentService`, `FakeCorpus` |

> **Import-path note:** application source uses **flat** imports (`from intent.types import ...`, needs `src/rag` on `PYTHONPATH`), while the test suite uses **package** imports (`from rag.intent.types import ...`, needs `src` on `PYTHONPATH`). Set `PYTHONPATH` to match what you're running.

## Bring up real backends

```bash
# from repo root — starts etcd + MinIO + Milvus standalone (v2.4.15)
docker compose up -d
```

Elasticsearch, Neo4j, Redis, PostgreSQL, and the vLLM cluster must be provisioned separately. Point the app at them via `RAG_*` environment variables (see [Domain Model & Config](./Reference-Core.md)), e.g.:

```bash
export RAG_MILVUS_HOST=localhost
export RAG_ES_HOSTS=http://localhost:9200
export RAG_NEO4J_URI=bolt://localhost:7687
export RAG_REDIS_URL=redis://localhost:6379/0
export RAG_PG_DSN=postgresql://rag:rag@localhost:5432/rag
export RAG_LLM_BASE_URL=http://localhost:8000/v1
```

`build_production()` (`query/wiring.py:64`) documents the intended real wiring but currently raises `NotImplementedError` until live endpoints and instance discovery are connected.

## Where to go next

- Understand the flow → [Architecture](./Architecture.md)
- Online request lifecycle → [Query Facade](./Module-Query.md)
- Offline index builds → [Offline Index Pipeline](./Module-Pipeline.md)
- Spec-driven design docs → `openspec/specs/` and `openspec/changes/archive/`
