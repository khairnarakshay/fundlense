# ai_intelligence/rag/ingestion.py
"""
Controlled ingestion: document -> normalised text -> chunks -> embeddings -> store.

Documents enter ONLY through this module (used by the management commands) -
there is deliberately no public upload endpoint, so what the assistant can
quote is limited to material an administrator approved.

Re-running is safe: the same source with unchanged content and the same
embedding model is a no-op; changed content replaces the old chunks atomically.
Embedding (slow, possibly a network call) happens BEFORE the database
transaction, so a provider failure never leaves a half-written document.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from ai_intelligence.conf import ai_int
from ai_intelligence.domain.exceptions import IngestionError
from ai_intelligence.domain.guardrails import looks_like_prompt_injection
from ai_intelligence.embeddings.factory import (
    EmbeddingConfig, embed_texts, get_embeddings, load_embedding_config,
)
from ai_intelligence.memory.context_window import estimate_tokens
from ai_intelligence.models import KnowledgeDocument
from ai_intelligence.rag.chunking import normalize_text, split_text
from ai_intelligence.rag.vector_store import ChunkToStore, PgVectorStore, VectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    document_id: int
    status: str                 # "created" | "updated" | "unchanged"
    chunk_count: int
    skipped_suspicious_chunks: int = 0


def ingest_document(*, title: str, text: str, source: str,
                    doc_type: str = KnowledgeDocument.DocType.PRODUCT_DOC, owner=None,
                    scheme_isin: str = "", version: str = "", published_date: date | None = None,
                    embeddings=None, config: EmbeddingConfig | None = None,
                    store: VectorStore | None = None, force: bool = False) -> IngestResult:
    config = config or load_embedding_config()
    store = store or PgVectorStore()

    content = normalize_text(text)
    if not content:
        raise IngestionError("Document has no text.")
    if len(content) > ai_int("AI_RAG_MAX_DOCUMENT_CHARS"):
        raise IngestionError(f"Document is too large (max {ai_int('AI_RAG_MAX_DOCUMENT_CHARS')} characters).")
    if not source.strip() or not title.strip():
        raise IngestionError("title and source are required.")

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = KnowledgeDocument.objects.filter(source=source, owner=owner).first()   # owner=None -> IS NULL
    if (existing and not force and existing.checksum == checksum
            and existing.embedding_model == config.label and existing.chunk_count > 0):
        return IngestResult(existing.pk, "unchanged", existing.chunk_count)

    pieces = split_text(content)
    clean = [p for p in pieces if not looks_like_prompt_injection(p)]
    skipped = len(pieces) - len(clean)
    if skipped:
        logger.warning("Skipped %d chunk(s) that look like prompt injection while ingesting %r", skipped, source)
    if not clean:
        raise IngestionError("No usable chunks after screening.")

    vectors = embed_texts(embeddings or get_embeddings(config), clean, config.dimensions)   # before the transaction
    to_store = [ChunkToStore(i, piece, estimate_tokens(piece), vec, {})
                for i, (piece, vec) in enumerate(zip(clean, vectors))]

    with transaction.atomic():
        fields = dict(title=title, doc_type=doc_type, scheme_isin=scheme_isin, version=version,
                      published_date=published_date, content=content, checksum=checksum,
                      embedding_model=config.label, ingested_at=timezone.now())
        if existing:
            for name, value in fields.items():
                setattr(existing, name, value)
            existing.save()
            document, status = existing, "updated"
        else:
            document = KnowledgeDocument.objects.create(source=source, owner=owner, **fields)
            status = "created"
        count = store.replace_document_chunks(document, to_store, config.label)
        KnowledgeDocument.objects.filter(pk=document.pk).update(chunk_count=count)

    return IngestResult(document.pk, status, count, skipped)


def reindex_document(document: KnowledgeDocument, *, embeddings=None, config: EmbeddingConfig | None = None,
                     store: VectorStore | None = None) -> IngestResult:
    """Re-chunk and re-embed from the stored text - used after changing the embedding model."""
    return ingest_document(title=document.title, text=document.content, source=document.source,
                           doc_type=document.doc_type, owner=document.owner, scheme_isin=document.scheme_isin,
                           version=document.version, published_date=document.published_date,
                           embeddings=embeddings, config=config, store=store, force=True)