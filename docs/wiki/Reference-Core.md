# Domain Model & Core Utilities

[← Home](./Home.md) · [Architecture](./Architecture.md)

The shared foundation used by every module: domain dataclasses, central configuration, naming conventions, and structured logging.

## Domain model — `models.py`

Enums and dataclasses passed across the pipeline and query layers.

### Enums

| Enum | Values |
|------|--------|
| `ChangeType` | `added` · `modified` · `deleted` |
| `DocStatus` | `pending` · `processing` · `ready` · `failed` |
| `RelationType` | `属于` (belongs_to) · `依赖` (depends_on) · `替代` (replaces) · `集成` (integrates) · `概念解释` (explains) |

### Dataclasses

| Type | Key fields |
|------|-----------|
| `RawDocument` | `doc_id, tenant_id, key, content, content_hash, metadata` |
| `Chunk` | `chunk_id, doc_id, tenant_id, ordinal, text, token_count, embedding?` |
| `ChangeSet` | `added, modified, deleted`; props `is_empty`, `upserted` (added+modified) |
| `Entity` | `name, entity_type, doc_ids: set, embedding?` |
| `Relation` | `source, target, relation_type: RelationType, confidence, doc_id` |

## Configuration — `config.py`

`Settings(BaseSettings)` (pydantic-settings) with env prefix `RAG_` and `.env` support. Access the singleton via `get_settings()` (`@lru_cache`).

| Group | Keys (defaults) |
|-------|-----------------|  
| Milvus | `milvus_host=localhost`, `milvus_port=19530` |
| Elasticsearch | `es_hosts=http://localhost:9200` |
| Neo4j | `neo4j_uri=bolt://localhost:7687`, `neo4j_user=neo4j`, `neo4j_password=neo4j` |
| Redis | `redis_url=redis://localhost:6379/0` |
| PostgreSQL | `pg_dsn=postgresql://rag:rag@localhost:5432/rag` |
| Object storage | `s3_endpoint=http://localhost:9000`, `s3_access_key`, `s3_secret_key`, `s3_raw_bucket=rag-raw-docs`, `s3_snapshot_bucket=rag-index-snapshots` |
| Embedding | `embedding_model=BAAI/bge-m3`, `embedding_dim=1024`, `embedding_batch_size=64` |
| Chunking | `chunk_tokens=512`, `chunk_overlap_tokens=50` |
| LLM | `llm_base_url=http://localhost:8000/v1`, `llm_model=Qwen2.5-14B-Instruct`, `llm_api_key=EMPTY` |
| vLLM pools | `vllm_small_endpoints=https://api.openai.com`, `vllm_large_endpoints=https://api.openai.com` (comma-separated) |
| Tracing | `otlp_endpoint=""` (blank = no-op) |
| Knowledge graph | `kg_confidence_threshold=0.85` |
| Tenancy | `small_tenant_doc_threshold=1000` |
| Shadow | `shadow_retention_hours=24` |
| Agentic RAG | `agentic_enabled_tenants=""`, `agentic_enabled_intents=""`, `agentic_deadline_s=20.0`, `agentic_max_iters=2` |

Override any value with an env var, e.g. `RAG_MILVUS_HOST=milvus.internal`.

## Naming conventions — `naming.py`

| Function | Result |
|----------|--------|
| `content_hash(text)` | SHA-256 hex (change detection) |
| `shadow_name(base)` | `{base}__shadow` |
| `active_name(base)` | `{base}__active` |
| `collection_for_tenant(tenant_id)` | `docs_{tenant_id}` |
| `shared_collection()` | `docs_shared_small` (small-tenant pool) |

## Structured logging — `raglog.py`

Uses `structlog` (JSON, ISO timestamps, contextvar merge) when installed; falls back to a stdlib shim (`_StdlibLogger`) that accepts the same keyword-field call style (`log.info("event", key=val)`).

| Function | Purpose |
|----------|---------|
| `get_logger(name)` | Returns a structlog logger or the stdlib shim |
| `bind_request_id(id?)` | Generate/bind a correlation id to the context (and structlog contextvars); returns it |
| `get_request_id()` | Read the current id |
| `clear_request_id()` | Unbind (called in `QueryService.query`'s `finally`) |

The correlation id is merged into every log line and threaded through observability spans, so a full request can be traced end to end.
