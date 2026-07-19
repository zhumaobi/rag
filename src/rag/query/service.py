from __future__ import annotations

import asyncio
import time

from cache.service import SemanticCache
from intent.service import IntentService
from observability.metrics import get_metrics
from observability.tracing import get_tracer
from query.agentic import AgenticConfig, AgenticController
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
        agentic: AgenticController | None = None,
        agentic_config: AgenticConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._intent = intent
        self._cache = cache
        self._router = router
        self._dispatcher = dispatcher
        self._system_prefix = system_prefix
        self._max_tokens = max_tokens
        self._agentic = agentic
        self._agentic_config = agentic_config or AgenticConfig()

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

            # 3b. Agentic self-correction loop (opt-in per tenant+intent). On any error
            #     (e.g. RAGAs unavailable) fall through to the single-pass linear path.
            if self._agentic is not None and self._agentic_config.is_enabled(tenant_id, intent_str):
                collection_id = next(
                    (e.collection_id for e in ir.entities if e.collection_id), None
                )
                try:
                    with tracer.span("agentic", request_id=request_id, intent=intent_str), trace.hop("agentic"):
                        ar = await self._agentic.run(
                            tenant_id, text, intent_str, embedding, collection_id
                        )
                except Exception as exc:  # noqa: BLE001 - degrade to single pass
                    log.warning("agentic_fallback_single_pass", tenant_id=tenant_id, error=str(exc))
                else:
                    trace.agentic = True
                    trace.agentic_iterations = ar.iterations
                    trace.agentic_scores = [
                        {
                            "iteration": r.iteration,
                            "rewritten": r.rewritten,
                            "faithfulness": round(r.faithfulness, 4),
                            "answer_relevance": round(r.answer_relevance, 4),
                            "passed": r.passed,
                        }
                        for r in ar.iteration_records
                    ]
                    trace.retrieved_doc_ids = ar.doc_ids
                    trace.contexts = ar.contexts
                    trace.retrieval_degraded = ar.retrieval_degraded
                    trace.tier = ar.tier
                    trace.degraded_level = ar.degraded_level
                    trace.prompt = ar.prompt
                    with tracer.span("cache_store", request_id=request_id):
                        asyncio.create_task(
                            self._cache.store_async(tenant_id, text, ar.text, embedding, ar.doc_ids)
                        )
                    metrics.observe_request(intent_str, time.perf_counter() - started, "ok")
                    metrics.observe_degradation(ar.degraded_level)
                    metrics.observe_stages(trace.hop_latency_ms)
                    metrics.observe_agentic(intent_str, ar.iterations, ar.low_confidence)
                    return Answer(
                        text=ar.text,
                        intent=ir,
                        cached=False,
                        degraded_level=ar.degraded_level,
                        tier=ar.tier,
                        meta={
                            "agentic": True,
                            "low_confidence": ar.low_confidence,
                            "iterations": ar.iterations,
                            **ar.gen_meta,
                        },
                        trace=trace,
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
