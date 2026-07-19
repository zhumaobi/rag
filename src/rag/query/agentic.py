from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from evaluation.ragas_eval import (
    ANSWER_RELEVANCE_MIN,
    FAITHFULNESS_MIN,
    GenerationScore,
    RagasEvaluator,
)
from observability.tracing import get_tracer
from raglog import get_logger
from retrieval.fusion import reciprocal_rank_fusion
from retrieval.types import RetrievedChunk, RetrievalResult
from serving.dispatcher import Dispatcher
from serving.prefix import build_prompt
from serving.types import GenRequest, PoolTier

log = get_logger("agentic")


@dataclass
class AgenticConfig:
    """Static, env-derived opt-in configuration for the Agentic RAG loop."""

    enabled_tenants: frozenset[str] = frozenset()
    enabled_intents: frozenset[str] = frozenset()
    deadline_s: float = 20.0
    max_iters: int = 2

    def is_enabled(self, tenant_id: str, intent_str: str) -> bool:
        return tenant_id in self.enabled_tenants and intent_str in self.enabled_intents

    @classmethod
    def from_settings(cls, settings) -> "AgenticConfig":
        def _split(raw: str) -> frozenset[str]:
            return frozenset(x.strip() for x in raw.split(",") if x.strip())

        return cls(
            enabled_tenants=_split(settings.agentic_enabled_tenants),
            enabled_intents=_split(settings.agentic_enabled_intents),
            deadline_s=settings.agentic_deadline_s,
            max_iters=settings.agentic_max_iters,
        )


@dataclass
class IterationRecord:
    """Per-iteration provenance surfaced on the QueryTrace."""

    iteration: int
    rewritten: bool
    faithfulness: float
    answer_relevance: float
    passed: bool
    latency_ms: float = 0.0


@dataclass
class AgenticResult:
    """Outcome of an agentic run: the best answer plus loop provenance."""

    text: str
    contexts: list[str]
    doc_ids: list[str]
    tier: PoolTier | None
    degraded_level: str
    retrieval_degraded: bool
    prompt: str
    gen_meta: dict
    low_confidence: bool
    iterations: int
    iteration_records: list[IterationRecord] = field(default_factory=list)


class HyDERewriter:
    """HyDE query rewrite: generate a hypothetical answer passage, then embed it so the
    dense retrieval arm searches document space instead of question space. Generation runs
    on the SMALL (7B) pool so it never starves the LARGE pool used for answer generation.
    """

    _PROMPT = (
        "针对下面的问题，写一段假设性的、看起来像知识库文档的中文答案段落，"
        "用于检索匹配，不要说明这是假设，直接给出段落：\n\n问题：{query}\n\n段落："
    )

    def __init__(self, dispatcher: Dispatcher, embedder, max_tokens: int = 256) -> None:
        self._dispatcher = dispatcher
        self._embedder = embedder
        self._max_tokens = max_tokens

    async def rewrite(self, tenant_id: str, query: str) -> list[float]:
        """Return a dense-arm embedding override derived from the hypothetical passage.

        On any generation failure, falls back to embedding the original query so the
        caller always gets a usable override vector.
        """
        prompt = self._PROMPT.format(query=query)
        req = GenRequest(
            tenant_id=tenant_id,
            intent="Intent-1",  # force SMALL/7B pool
            prompt=prompt,
            max_tokens=self._max_tokens,
            est_prompt_tokens=len(prompt) // 4,
        )
        try:
            gen = await self._dispatcher.generate(req, context="")
            passage = (gen.text or "").strip()
        except Exception as exc:  # noqa: BLE001 - HyDE is best-effort
            log.warning("hyde_generation_failed", tenant_id=tenant_id, error=str(exc))
            passage = ""
        text = passage or query
        return self._embedder.embed_texts([text])[0]


class AgenticRetriever:
    """Dedicated hybrid retrieval path for the agentic loop.

    Calls the dense and sparse retrievers directly, fuses via RRF, and reranks. Accepts an
    optional precomputed dense-arm embedding (HyDE); the sparse arm always uses the original
    query terms. Deliberately does not touch the shared RetrievalRouter.
    """

    def __init__(self, dense, sparse, reranker, recall_k: int = 20, final_k: int = 5) -> None:
        self._dense = dense
        self._sparse = sparse
        self._reranker = reranker
        self._recall_k = recall_k
        self._final_k = final_k

    async def retrieve(
        self,
        tenant_id: str,
        query: str,
        query_embedding: list[float],
        collection_id: str | None = None,
    ) -> list[RetrievedChunk]:
        dense_task = asyncio.to_thread(
            self._dense.retrieve, tenant_id, query_embedding, self._recall_k, collection_id, None
        )
        sparse_task = asyncio.to_thread(
            self._sparse.retrieve, tenant_id, query, self._recall_k, collection_id
        )
        tracer = get_tracer()
        with tracer.span("agentic.dense_sparse", collection=collection_id or "global"):
            dense_hits, sparse_hits = await asyncio.gather(dense_task, sparse_task)
        fused = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=self._recall_k)
        with tracer.span("agentic.rerank", candidates=len(fused)):
            return await asyncio.to_thread(self._reranker.rerank, query, fused, self._final_k)


class AgenticController:
    """Opt-in self-correction loop: retrieve -> generate -> score, and on a failed gate
    with remaining budget, HyDE-rewrite + re-retrieve before regenerating.

    Guarantees best-so-far: the highest-scoring candidate is always returned, flagged
    low_confidence when no candidate cleared the Faithfulness/Answer-Relevance thresholds.
    """

    def __init__(
        self,
        retriever: AgenticRetriever,
        dispatcher: Dispatcher,
        evaluator: RagasEvaluator,
        hyde: HyDERewriter,
        embedder,
        config: AgenticConfig,
        system_prefix: str = "",
        max_tokens: int = 512,
        ragas_scorer=None,
    ) -> None:
        self._retriever = retriever
        self._dispatcher = dispatcher
        self._evaluator = evaluator
        self._hyde = hyde
        self._embedder = embedder
        self._config = config
        self._system_prefix = system_prefix
        self._max_tokens = max_tokens
        # Injected deterministic scorer for mock/offline; None => real RAGAs backend.
        self._ragas_scorer = ragas_scorer

    async def run(
        self,
        tenant_id: str,
        query: str,
        intent_str: str,
        query_embedding: list[float],
        collection_id: str | None = None,
    ) -> AgenticResult:
        deadline = time.perf_counter() + self._config.deadline_s
        best: dict | None = None
        records: list[IterationRecord] = []
        dense_emb = query_embedding

        for i in range(max(1, self._config.max_iters)):
            rewritten = i > 0
            # Deadline guard: don't start an iteration we can't plausibly finish.
            if rewritten and time.perf_counter() >= deadline:
                break

            iter_start = time.perf_counter()

            chunks = await self._retriever.retrieve(tenant_id, query, dense_emb, collection_id)
            context = "\n".join(c.text for c in chunks)

            req = GenRequest(
                tenant_id=tenant_id,
                intent=intent_str,
                prompt=query,
                system_prefix=self._system_prefix,
                max_tokens=self._max_tokens,
                est_prompt_tokens=len(context) // 4,
            )
            gen = await self._dispatcher.generate(req, context, fallback_chunks_text=context)

            contexts = [c.text for c in chunks]
            score = self._score(query, gen.text, contexts)
            passed = not score.below_threshold()

            records.append(
                IterationRecord(
                    iteration=i,
                    rewritten=rewritten,
                    faithfulness=score.faithfulness,
                    answer_relevance=score.answer_relevance,
                    passed=passed,
                    latency_ms=round((time.perf_counter() - iter_start) * 1000, 2),
                )
            )

            candidate = {
                "text": gen.text,
                "contexts": contexts,
                "doc_ids": list(dict.fromkeys(c.doc_id for c in chunks)),
                "tier": gen.tier,
                "degraded_level": gen.degraded_level,
                "prompt": gen.prompt,
                "gen_meta": gen.meta,
                "score": score,
            }
            if best is None or self._rank(score) > self._rank(best["score"]):
                best = candidate

            if passed:
                break

            # Failed gate: attempt a HyDE rewrite for the next iteration if budget remains.
            if i + 1 < max(1, self._config.max_iters) and time.perf_counter() < deadline:
                dense_emb = await self._hyde.rewrite(tenant_id, query)

        assert best is not None  # loop always runs at least once
        low_confidence = bool(best["score"].below_threshold())
        return AgenticResult(
            text=best["text"],
            contexts=best["contexts"],
            doc_ids=best["doc_ids"],
            tier=best["tier"],
            degraded_level=best["degraded_level"],
            retrieval_degraded=collection_id is None,
            prompt=best["prompt"],
            gen_meta=best["gen_meta"],
            low_confidence=low_confidence,
            iterations=len(records),
            iteration_records=records,
        )

    def _score(self, query: str, answer: str, contexts: list[str]) -> GenerationScore:
        """Score a candidate on Faithfulness + Answer Relevance (Context Utilization is
        offline-only, so it is neutralized here to never gate the online result)."""
        score = self._evaluator.score_one(query, answer, contexts, scorer=self._ragas_scorer)
        return GenerationScore(
            faithfulness=score.faithfulness,
            answer_relevance=score.answer_relevance,
            context_utilization=1.0,  # excluded from online gating
        )

    @staticmethod
    def _rank(score: GenerationScore) -> float:
        """Combined ordering key for best-so-far selection over the two gated metrics."""
        return score.faithfulness + score.answer_relevance
