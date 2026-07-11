from __future__ import annotations

import tiktoken

from config import get_settings
from raglog import get_logger
from models import Chunk, RawDocument

log = get_logger("chunk")

_enc = tiktoken.get_encoding("cl100k_base")


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _token_len(text: str) -> int:
    return len(_enc.encode(text))


def chunk_document(doc: RawDocument) -> list[Chunk]:
    """Sliding token window (512 tokens, 50 overlap) that respects paragraph boundaries.

    Paragraphs are packed into a window until the token budget is reached; oversized
    paragraphs are hard-split on token count. Successive windows overlap by
    `chunk_overlap_tokens` to preserve context continuity across chunk edges.
    """
    s = get_settings()
    max_tokens, overlap = s.chunk_tokens, s.chunk_overlap_tokens

    # Flatten to token-tagged paragraph units, hard-splitting oversized paragraphs.
    units: list[str] = []
    for para in _split_paragraphs(doc.content):
        if _token_len(para) <= max_tokens:
            units.append(para)
        else:
            tokens = _enc.encode(para)
            for i in range(0, len(tokens), max_tokens):
                units.append(_enc.decode(tokens[i : i + max_tokens]))

    chunks: list[Chunk] = []
    window: list[str] = []
    window_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal ordinal, window, window_tokens
        if not window:
            return
        text = "\n\n".join(window)
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}#c{ordinal}",
                doc_id=doc.doc_id,
                tenant_id=doc.tenant_id,
                ordinal=ordinal,
                text=text,
                token_count=_token_len(text),
            )
        )
        ordinal += 1
        # Carry overlap: keep trailing paragraphs up to `overlap` tokens.
        carried: list[str] = []
        carried_tokens = 0
        for para in reversed(window):
            pt = _token_len(para)
            if carried_tokens + pt > overlap:
                break
            carried.insert(0, para)
            carried_tokens += pt
        window = carried
        window_tokens = carried_tokens

    for unit in units:
        ut = _token_len(unit)
        if window_tokens + ut > max_tokens and window:
            flush()
        window.append(unit)
        window_tokens += ut
    flush()

    log.info("document_chunked", doc_id=doc.doc_id, chunks=len(chunks))
    return chunks
