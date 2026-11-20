# ai_intelligence/rag/vector_store.py
"""
Vector store behind a small interface, so pgvector can be swapped for another
store later without touching ingestion or retrieval. PgVectorStore is the
implementation: chunk rows with a pgvector column, searched by cosine distance
through the HNSW index created in the migration.

ACCESS CONTROL lives in search(): the owner filter is part of the SQL query, so
another user's private chunks are never even fetched, let alone shown to a
model. (A prompt telling the model to ignore them would not be a control.)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.db.models import Q
from pgvector.django import CosineDistance

from ai_intelligence.models import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True)
class ChunkToStore:
    chunk_index: int
    content: str
    token_estimate: int
    embedding: list[float]
    metadata: dict


@dataclass(frozen=True)
class ScoredChunk:
    chunk: KnowledgeChunk
    distance: float          # cosine distance: 0 = identical direction, 2 = opposite


class VectorStore(ABC):
    @abstractmethod
    def replace_document_chunks(self, document: KnowledgeDocument, chunks: list[ChunkToStore],
                                embedding_model: str) -> int: ...

    @abstractmethod
    def search(self, query_vector: list[float], *, user, embedding_model: str, k: int) -> list[ScoredChunk]: ...


class PgVectorStore(VectorStore):
    def replace_document_chunks(self, document, chunks, embedding_model) -> int:
        """Delete the document's old chunks and insert the new ones. Call inside a
        transaction so a failure leaves the previous chunks intact."""
        KnowledgeChunk.objects.filter(document=document).delete()
        KnowledgeChunk.objects.bulk_create([
            KnowledgeChunk(document=document, owner=document.owner, chunk_index=c.chunk_index,
                           content=c.content, token_estimate=c.token_estimate, embedding=c.embedding,
                           embedding_model=embedding_model, metadata=c.metadata)
            for c in chunks
        ], batch_size=200)
        return len(chunks)

    def search(self, query_vector, *, user, embedding_model, k) -> list[ScoredChunk]:
        visible = Q(owner__isnull=True)                       # shared knowledge
        if user is not None and getattr(user, "pk", None) is not None:
            visible |= Q(owner=user)                          # plus this user's own private chunks
        rows = (KnowledgeChunk.objects
                .filter(embedding_model=embedding_model)      # never compare vectors from different models
                .filter(visible)
                .annotate(distance=CosineDistance("embedding", query_vector))
                .select_related("document")
                .order_by("distance")[:k])
        return [ScoredChunk(chunk=row, distance=float(row.distance)) for row in rows]