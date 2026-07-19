from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # Elasticsearch
    es_hosts: str = "http://localhost:9200"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "your_password123"

    # Redis
    redis_url: str = "redis://:your_redis_password@localhost:6379/0"

    # PostgreSQL
    pg_dsn: str = "postgresql://postgres:your_pg_password@localhost:5432/mydb"

    # Object storage
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin123"
    s3_raw_bucket: str = "rag-raw-docs"
    s3_snapshot_bucket: str = "rag-index-snapshots"

    # Embedding
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 64

    # Chunking
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # LLM (relation extraction)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "Qwen2.5-14B-Instruct"
    llm_api_key: str = "EMPTY"

    # vLLM serving pools (comma-separated base URLs, one per replica; no /v1 suffix).
    # Provider = OpenAI/ChatGPT: both tiers hit the same hosted API host.
    vllm_small_endpoints: str = "https://api.openai.com"
    vllm_large_endpoints: str = "https://api.openai.com"

    # Tracing: OTLP exporter endpoint (blank = tracing stays a no-op).
    # Set RAG_OTLP_ENDPOINT to a running collector (e.g. http://localhost:4317) to enable export.
    otlp_endpoint: str = ""

    # Knowledge graph
    kg_confidence_threshold: float = 0.85

    # Small-tenant shared collection threshold
    small_tenant_doc_threshold: int = 1000

    # Shadow retention
    shadow_retention_hours: int = 24

    # Agentic RAG loop (opt-in). Empty tenant/intent lists = disabled everywhere.
    # Comma-separated; intents use the "Intent-1|2|3" string form.
    agentic_enabled_tenants: str = ""
    agentic_enabled_intents: str = ""
    agentic_deadline_s: float = 20.0
    agentic_max_iters: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
