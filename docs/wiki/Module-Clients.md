# Infrastructure Clients (`clients/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Thin wrappers around each backing service. Each reads its configuration from `config.get_settings()` and exposes a task-focused API used by the pipeline, retrieval, cache, and serving layers.

## Overview

| Client | Service | Role |
|--------|---------|------|
| `MilvusClient` (`clients/milvus_client.py`) | Milvus 2.4.15 | Vector store; per-tenant HNSW collections, alias switching |
| `EsClient` (`clients/es_client.py`) | Elasticsearch 8.x | BM25 sparse index; alias switching, tenant filter |
| `Neo4jClient` (`clients/neo4j_client.py`) | Neo4j 5.x | Knowledge graph; path/neighbor queries, active version |
| `RedisClient` (`clients/redis_client.py`) | Redis | Semantic cache backend, entity dictionary, cache reverse index, pipeline state |
| `PostgresClient` (`clients/postgres_client.py`) | PostgreSQL | Document metadata — source of truth for change detection |
| `S3Client` (`clients/s3_client.py`) | S3 / MinIO | Raw document storage + index snapshots |

## PostgresClient — `clients/postgres_client.py`

Document metadata store; **source of truth for content_hash change detection**. Uses `psycopg` with `dict_row`.

Schema (`documents` table): `doc_id` PK, `tenant_id`, `object_key`, `content_hash`, `version`, `status`, `updated_at`, plus `idx_documents_tenant`.

| Method | Purpose |
|--------|---------|
| `init_schema()` | Create table + index |
| `get_hashes(tenant_id)` | `{doc_id: content_hash}` for change detection |
| `upsert_document(doc_id, tenant_id, object_key, content_hash, status)` | Insert or bump `version` on conflict |
| `set_status(doc_id, status)` | Update `DocStatus` |
| `delete_documents(doc_ids)` | Bulk delete via `= ANY(%s)` |

## S3Client — `clients/s3_client.py`

Object storage access via `boto3`, configured from Settings (endpoint, keys, raw bucket). Key methods: `list_documents(tenant_id)` (paginated list under the `{tenant_id}/` prefix), `get_bytes(key)`.

## Neo4jClient — `clients/neo4j_client.py`

Backs Intent-3 retrieval. Used by `RetrievalRouter._intent3`:
- `active_version(tenant_id)` — current graph version for the tenant.
- `find_paths(tenant_id, entity_a, entity_b, version, max_hops)` → `(paths, doc_ids)`.
- `neighbor_doc_ids(tenant_id, entity, version, max_hops)` → doc_ids.

Tenant isolation is enforced by tenant labels + per-tenant active version.

## RedisClient — `clients/redis_client.py`

Multi-purpose:
- L2 semantic cache backend (with `L2Cache`).
- Entity dictionary lookups for `EntityRecognizer`.
- Cache reverse index: `add_cache_ref(tenant_id, doc_ids, cache_ref)` for precise invalidation.
- Pipeline run state: `set_pipeline_state(run_id, payload)` (see `pipeline/orchestrator.py:_persist`).

## MilvusClient / EsClient

Vector and sparse index backends. Both support the shadow/active naming convention (`naming.shadow_name` / `active_name`) and alias-based atomic switching driven by `pipeline/switch.py` (`AtomicSwitch`).

## Configuration

All hosts/credentials come from `Settings` (`config.py`) via the `RAG_` env prefix. See [Domain Model & Config](./Reference-Core.md).
