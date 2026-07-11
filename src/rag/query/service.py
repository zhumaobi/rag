from __future__ import annotations

import asyncio
import time

from cache.service import SemanticCache
from intent.service import IntentService
from observability.metrics import get_metrics
from observability.tracing import get_tracer
from query.types import Answer, QueryTrace, intent_to_request_str
from raglog import bind_request_id, clear_request_id, get_logger, get_request_id
from retrieval.router import RetrievalRouter
from retrieval.types import RetrievalResult
from serving.dispatcher import Dispatcher
from serving.types import GenRequest

log = get_logger("query_service")


class QueryService:
    """Online query orchestration facade: embed -> intent -> cache -> retrieve -> generate.

    Constructs nothing itself; every collaborator is injected so the identical code path
    runs against fakes (build_mock) and real clients (build_production).
    """

    def __init__(
        self,
        embedder,
        intent: IntentService,
        cache: SemanticCache,
        router: RetrievalRouter,
        dispatcher: Dispatcher,
        system_prefix: str = "",
        max_tokens: int = 512,
    ) -> None:
        self._embedder = embedder
        self._intent = intent
        self._cache = cache
        self._router = router
        self._dispatcher = dispatcher
        self._system_prefix = system_prefix
        self._max_tokens = max_tokens

    async def query(self, tenant_id: str, text: str, bypass_cache: bool = False) -> Answer:
        request_id = bind_request_id()
        trace = QueryTrace(request_id=request_id)
        tracer = get_tracer()
        metrics = get_metrics()
        started = time.perf_counter()
        intent_str = "unknown"
        try:
            # 1. Embed once; reuse for both cache lookup and retrieval.
            with tracer.span("embed", request_id=request_id), trace.hop("embed"):
                embedding = self._embedder.embed_texts([text])[0]

            # 2. Intent recognition (rules path is model-free for COMPARE/RELATION).
            with tracer.span("intent", request_id=request_id), trace.hop("intent"):
                ir = self._intent.recognize(tenant_id, text)
            trace.intent = ir
            intent_str = intent_to_request_str(ir.intent)

            # 3. Cache lookup (skipped when bypass_cache or time_sensitive).
            if not bypass_cache:
                with tracer.span("cache_lookup", request_id=request_id), trace.hop("cache_lookup"):
                    hit = self._cache.lookup(tenant_id, text, embedding, ir.time_sensitive)
                if hit is not None:
                    log.info("cache_hit", tenant_id=tenant_id, level=hit.level, sim=round(hit.similarity, 4))
                    trace.cache_level = hit.level
                    metrics.observe_request(intent_str, time.perf_counter() - started, "cache_hit")
                    return Answer(
                        text=hit.answer, intent=ir, cached=True,
                        meta={"cache_level": hit.level}, trace=trace,
                    )

            # 4. Retrieval routed by intent.
            with tracer.span("retrieve", request_id=request_id, intent=intent_str), trace.hop("retrieve"):
                retrieval: RetrievalResult = await self._router.route(tenant_id, text, ir)
            context = "\n".join(c.text for c in retrieval.chunks)
            fallback_text = context
            trace.retrieved_doc_ids = list(dict.fromkeys(c.doc_id for c in retrieval.chunks))
            trace.contexts = [c.text for c in retrieval.chunks]
            trace.retrieval_degraded = retrieval.degraded

            # 5. Build the generation request and dispatch.
            req = GenRequest(
                tenant_id=tenant_id,
                intent=intent_str,
                prompt=text,
                system_prefix=self._system_prefix,
                max_tokens=self._max_tokens,
                est_prompt_tokens=len(context) // 4,
            )
            with tracer.span("generate", request_id=request_id, intent=intent_str), trace.hop("generate"):
                gen = await self._dispatcher.generate(req, context, fallback_chunks_text=fallback_text)
            trace.tier = gen.tier
            trace.degraded_level = gen.degraded_level
            trace.prompt = gen.prompt

            # 6. Fire-and-forget cache store; do not await it on the response path.
            #    Runs even on a bypassed miss so eval passes still warm the cache.
            doc_ids = list({c.doc_id for c in retrieval.chunks})
            with tracer.span("cache_store", request_id=request_id):
                asyncio.create_task(
                    self._cache.store_async(tenant_id, text, gen.text, embedding, doc_ids)
                )

            metrics.observe_request(intent_str, time.perf_counter() - started, "ok")
            metrics.observe_degradation(gen.degraded_level)
            metrics.observe_stages(trace.hop_latency_ms)

            return Answer(
                text=gen.text,
                intent=ir,
                cached=False,
                degraded_level=gen.degraded_level,
                tier=gen.tier,
                meta={"downgraded": gen.downgraded, "degraded": retrieval.degraded, **gen.meta},
                trace=trace,
            )
        except Exception:
            metrics.observe_request(intent_str, time.perf_counter() - started, "error")
            log.error("query_failed", tenant_id=tenant_id, request_id=get_request_id())
            raise
        finally:
            clear_request_id()
