# ai_intelligence/rag/retrieval.py
"""Retrieval: embed the question, search the vector store, filter, return typed results."""
from __future__ import annotations

import logging

from pydantic import BaseModel

from ai_intelligence.conf import ai_float, ai_int
from ai_intelligence.domain.guardrails import looks_like_prompt_injection
from ai_intelligence.embeddings.factory import EmbeddingConfig, embed_query, get_embeddings, load_embedding_config
from ai_intelligence.rag.vector_store import PgVectorStore, VectorStore

logger = logging.getLogger(__name__)


class RetrievedChunk(BaseModel):
    document_title: str
    source: str
    doc_type: str
    version: str = ""
    scheme_isin: str = ""
    chunk_index: int
    content: str
    distance: float


def retrieve_knowledge(question: str, *, user, embeddings=None, config: EmbeddingConfig | None = None,
                       store: VectorStore | None = None, top_k: int | None = None,
                       max_distance: float | None = None) -> list[RetrievedChunk]:
    """
    Shared knowledge plus `user`'s own private chunks (enforced inside the SQL
    query by PgVectorStore.search). Chunks farther than `max_distance` are
    dropped - weak matches are worse than none, because the model will try to use
    whatever it is given. Chunks that look like prompt injection are dropped too.
    """
    config = config or load_embedding_config()
    store = store or PgVectorStore()
    top_k = top_k or ai_int("AI_RAG_TOP_K")
    max_distance = ai_float("AI_RAG_MAX_DISTANCE") if max_distance is None else max_distance

    vector = embed_query(embeddings or get_embeddings(config), question, config.dimensions)
    results: list[RetrievedChunk] = []
    for scored in store.search(vector, user=user, embedding_model=config.label, k=top_k):
        if scored.distance > max_distance:
            continue
        if looks_like_prompt_injection(scored.chunk.content):
            logger.warning("Dropped a retrieved chunk that looks like prompt injection (document id=%s)",
                           scored.chunk.document_id)
            continue
        doc = scored.chunk.document
        results.append(RetrievedChunk(
            document_title=doc.title, source=doc.source, doc_type=doc.doc_type, version=doc.version,
            scheme_isin=doc.scheme_isin, chunk_index=scored.chunk.chunk_index,
            content=scored.chunk.content, distance=round(scored.distance, 4)))
    return results
