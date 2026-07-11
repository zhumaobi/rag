from __future__ import annotations

from raglog import get_logger
from retrieval.types import RetrievedChunk

log = get_logger("rerank")

_DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


class Reranker:
    """Cross-Encoder reranking of fused candidates (task 5.4).

    The Cross-Encoder jointly encodes (query, chunk) for a precise relevance score,
    correcting bi-encoder/BM25 ordering. Applied only to the fused Top-N candidates to
    bound cost, then truncated to the final Top-K returned to the LLM.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None

    def _lazy(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
        return self._model

    def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int = 5) -> list[RetrievedChunk]:
        if not candidates:
            return []
        model = self._lazy()
        pairs = [(query, c.text) for c in candidates]
        scores = model.predict(pairs)
        reranked = [
            RetrievedChunk(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                text=c.text,
                score=float(s),
                source="rerank",
            )
            for c, s in zip(candidates, scores)
        ]
        reranked.sort(key=lambda c: c.score, reverse=True)
        return reranked[:top_k]
