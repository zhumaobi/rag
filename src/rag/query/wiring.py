from __future__ import annotations

from config import get_settings
from intent.service import IntentService
from observability.metrics import start_metrics_server
from observability.tracing import setup_tracing
from query.fakes import (
    FakeCache,
    FakeClassifier,
    FakeEmbedder,
    FakeEntityRecognizer,
    FakeVLLM,
    fake_retriever_kwargs,
)
from query.service import QueryService
from retrieval.router import RetrievalRouter
from serving.dispatcher import Dispatcher
from serving.model_pool import DEFAULT_POOL_CONFIGS, ModelPool
from serving.prefix import default_system_prefix
from serving.types import Instance, InstanceState, PoolTier
from serving.vllm_client import VLLMClient


def _build_pools(small_n: int = 2, large_n: int = 2) -> dict[PoolTier, ModelPool]:
    """Real ModelPools seeded with healthy fake Instances (mirrors serving/loadtest.py)."""
    pools = {tier: ModelPool(cfg) for tier, cfg in DEFAULT_POOL_CONFIGS.items()}
    for i in range(small_n):
        pools[PoolTier.SMALL].add(
            Instance(f"s{i}", PoolTier.SMALL, f"http://fake-small-{i}", InstanceState.HEALTHY)
        )
    for i in range(large_n):
        pools[PoolTier.LARGE].add(
            Instance(f"l{i}", PoolTier.LARGE, f"http://fake-large-{i}", InstanceState.HEALTHY)
        )
    return pools


def build_mock() -> QueryService:
    """Assemble a QueryService that runs the full query path with no infra or GPU.

    Real code exercised: IntentService rules path, RetrievalRouter branch selection,
    Dispatcher tier-selection + degradation. Faked: embedding, retrieval leaf clients,
    cache backend, and the LLM.
    """
    start_metrics_server()
    embedder = FakeEmbedder()

    intent = IntentService(
        classifier=FakeClassifier(),
        entity_recognizer=FakeEntityRecognizer(),
    )

    router = RetrievalRouter(embed_fn=lambda q: embedder.embed_texts([q])[0], **fake_retriever_kwargs())

    dispatcher = Dispatcher(pools=_build_pools(), client=FakeVLLM())

    return QueryService(
        embedder=embedder,
        intent=intent,
        cache=FakeCache(),
        router=router,
        dispatcher=dispatcher,
        system_prefix=default_system_prefix(),
    )


def _pools_from_settings() -> dict[PoolTier, ModelPool]:
    """Populate real ModelPools from the comma-separated endpoint settings.

    Each URL becomes one HEALTHY Instance in its tier's pool. There is no live
    discovery backend in-tree (autoscaler.InstanceProvider is only a Protocol), so
    endpoints are declared via RAG_VLLM_SMALL_ENDPOINTS / RAG_VLLM_LARGE_ENDPOINTS.
    """
    s = get_settings()
    pools = {tier: ModelPool(cfg) for tier, cfg in DEFAULT_POOL_CONFIGS.items()}
    tier_endpoints = {
        PoolTier.SMALL: s.vllm_small_endpoints,
        PoolTier.LARGE: s.vllm_large_endpoints,
    }
    for tier, raw in tier_endpoints.items():
        endpoints = [e.strip() for e in raw.split(",") if e.strip()]
        if not endpoints:
            raise RuntimeError(
                f"no vLLM endpoints configured for {tier.value} pool; set "
                f"RAG_VLLM_{tier.name}_ENDPOINTS to a comma-separated list of base URLs"
            )
        for i, endpoint in enumerate(endpoints):
            pools[tier].add(
                Instance(f"{tier.name.lower()}-{i}", tier, endpoint, InstanceState.HEALTHY)
            )
    return pools


def build_production() -> QueryService:
    """Assemble a QueryService backed by real infra clients and a live vLLM cluster.

    Every collaborator default-constructs its own backend from config.get_settings()
    (Milvus/ES/Neo4j/Redis), so this factory only wires them together and populates the
    serving pools from the configured endpoints. Observability is activated here the same
    way build_mock() activates it, so metrics/tracing take effect and offline evaluation
    (run_offline --service production) exercises this identical path.
    """
    from cache.service import SemanticCache
    from pipeline.embed import Embedder

    settings = get_settings()

    # Observability: export traces (no-op unless OTLP configured) and serve metrics.
    setup_tracing(settings.otlp_endpoint)
    start_metrics_server()

    embedder = Embedder()  # bge-m3

    intent = IntentService()  # lazy MiniLM classifier + Redis-backed entity dict

    cache = SemanticCache()  # L1 + Redis VSS L2 + doc_id reverse index
    cache._l2.ensure_index()  # create the RediSearch HNSW index once at startup

    router = RetrievalRouter(embed_fn=lambda q: embedder.embed_texts([q])[0])

    dispatcher = Dispatcher(pools=_pools_from_settings(), client=VLLMClient())

    return QueryService(
        embedder=embedder,
        intent=intent,
        cache=cache,
        router=router,
        dispatcher=dispatcher,
        system_prefix=default_system_prefix(),
    )
