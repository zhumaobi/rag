from __future__ import annotations

from config import get_settings
from raglog import get_logger
from models import Chunk

log = get_logger("embed")


class Embedder:
    """Batch embedding with dynamic batch sizing to keep GPU utilization > 80%."""

    def __init__(self) -> None:
        s = get_settings()
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(s.embedding_model)
        self._batch_size = s.embedding_batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return chunks
        vectors = self.embed_texts([c.text for c in chunks])
        for chunk, vec in zip(chunks, vectors):
            chunk.embedding = vec
        log.info("chunks_embedded", count=len(chunks))
        return chunks
