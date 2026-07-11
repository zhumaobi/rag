from __future__ import annotations

from retrieval.types import RetrievedChunk

# RRF constant; 60 is the canonical value from the original RRF paper. It damps the
# influence of very high ranks so no single retriever dominates the fused order.
_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]], k: int = _RRF_K, top_k: int | None = None
) -> list[RetrievedChunk]:
    """Fuse multiple ranked lists via Reciprocal Rank Fusion (task 5.3).

    Each chunk's fused score is sum over lists of 1/(k + rank). Rank is 0-based per list.
    Chunks are deduplicated by chunk_id; the first-seen text/doc_id is retained.
    """
    scores: dict[str, float] = {}
    representative: dict[str, RetrievedChunk] = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked):
            cid = chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            representative.setdefault(cid, chunk)

    fused = []
    for cid, score in scores.items():
        base = representative[cid]
        fused.append(
            RetrievedChunk(
                chunk_id=base.chunk_id,
                doc_id=base.doc_id,
                text=base.text,
                score=score,
                source="rrf",
            )
        )
    fused.sort(key=lambda c: c.score, reverse=True)
    return fused[:top_k] if top_k else fused
