# ai_intelligence/models.py
"""
Persistence for the AI layer. Five tables, in two groups:

  Conversations (private to one user)
    ChatConversation  one chat thread. Holds the ROLLING SUMMARY of old turns.
    ChatMessage       one user/assistant message, numbered `sequence` within its thread.
    UserMemory        small explicit facts the user stated (goals, horizon, preferences).

  Knowledge base (RAG)
    KnowledgeDocument one source document. owner NULL = shared with everyone,
                      owner set = private to that user.
    KnowledgeChunk    one embedded slice of a document, stored in a pgvector column.

Design rules baked into the schema:
  * Every private row reaches a user through a foreign key that every query
    filters on (see selectors.py). An id on its own is never authorization.
  * Financial data is NOT stored here as a snapshot. Portfolio numbers are
    re-read from the authoritative tables on every turn; the conversation only
    keeps the words that were said.
  * Chunks record the embedding model that produced them, and retrieval only
    searches chunks from the CURRENT model, so vectors from different models
    are never compared (see README: changing embedding model/dimensions).
"""
from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

from ai_intelligence.conf import ai_int
from core.models import BaseModel


class ChatConversation(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations")
    title = models.CharField(max_length=200, blank=True)
    # Rolling summary of every message with sequence <= summary_through_sequence.
    # Older turns live here in compressed form; newer ones are replayed verbatim.
    summary = models.TextField(blank=True)
    summary_through_sequence = models.PositiveIntegerField(default=0)
    message_count = models.PositiveIntegerField(default=0)   # also the last allocated sequence number
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "ai_chat_conversation"
        ordering = ["-last_message_at", "-id"]
        indexes = [models.Index(fields=["user", "-last_message_at"], name="ai_conv_user_recent_idx")]

    def __str__(self):
        return f"Conversation {self.pk}"


class ChatMessage(BaseModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    sequence = models.PositiveIntegerField()
    token_estimate = models.PositiveIntegerField(default=0)
    # citations / verification result / routing decisions. Never portfolio snapshots.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_chat_message"
        ordering = ["sequence"]
        constraints = [models.UniqueConstraint(fields=["conversation", "sequence"], name="ai_msg_unique_sequence")]
        indexes = [models.Index(fields=["conversation", "sequence"], name="ai_msg_conv_seq_idx")]


class UserMemory(BaseModel):
    class Category(models.TextChoices):
        GOAL = "goal", "Goal"
        HORIZON = "horizon", "Investment horizon"
        RISK_PREFERENCE = "risk_preference", "Risk preference"
        PREFERENCE = "preference", "Preference"
        OTHER = "other", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_memories")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    content = models.CharField(max_length=300)
    content_hash = models.CharField(max_length=64)       # sha256 of normalized content, for de-duplication
    source_conversation = models.ForeignKey(ChatConversation, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name="memories")

    class Meta:
        db_table = "ai_user_memory"
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["user", "content_hash"], name="ai_memory_unique_per_user")]
        indexes = [models.Index(fields=["user", "category"], name="ai_memory_user_cat_idx")]


class KnowledgeDocument(BaseModel):
    class DocType(models.TextChoices):
        PRODUCT_DOC = "product_doc", "Product documentation"
        EDUCATION = "education", "Educational material"
        SCHEME_DOCUMENT = "scheme_document", "Scheme document (SID/KIM)"
        REGULATORY = "regulatory", "Regulatory material"
        USER_UPLOAD = "user_upload", "User upload"

    title = models.CharField(max_length=255)
    source = models.CharField(max_length=500)             # file name or URL; identity of the document
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.PRODUCT_DOC)
    scheme_isin = models.CharField(max_length=20, blank=True, db_index=True)   # set for scheme-specific documents
    version = models.CharField(max_length=50, blank=True)
    published_date = models.DateField(null=True, blank=True)
    content = models.TextField()                          # full normalized text, kept so we can re-chunk / re-embed
    checksum = models.CharField(max_length=64)            # sha256 of content; unchanged re-ingest is a no-op
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="ai_documents")
    embedding_model = models.CharField(max_length=100, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    ingested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_knowledge_document"
        ordering = ["title", "id"]
        constraints = [
            # source identifies a document; shared documents (owner NULL) and each user's
            # private documents are separate namespaces. Two partial constraints, because a
            # plain unique(owner, source) would allow duplicate shared rows (NULL != NULL).
            models.UniqueConstraint(fields=["source"], condition=models.Q(owner__isnull=True),
                                    name="ai_doc_unique_shared_source"),
            models.UniqueConstraint(fields=["owner", "source"], condition=models.Q(owner__isnull=False),
                                    name="ai_doc_unique_owner_source"),
        ]

    def __str__(self):
        return self.title


class KnowledgeChunk(BaseModel):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    # Copy of document.owner, so the vector query can filter on it without a join.
    # Written only by rag/vector_store.py at ingestion; never edited by hand.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                              related_name="ai_chunks")
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    token_estimate = models.PositiveIntegerField(default=0)
    embedding = VectorField(dimensions=ai_int("AI_EMBEDDING_DIMENSIONS"))
    embedding_model = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_knowledge_chunk"
        ordering = ["document_id", "chunk_index"]
        constraints = [models.UniqueConstraint(fields=["document", "chunk_index"], name="ai_chunk_unique_index")]
        indexes = [
            # Approximate nearest-neighbour index for cosine distance.
            HnswIndex(name="ai_chunk_embedding_hnsw", fields=["embedding"], m=16, ef_construction=64,
                      opclasses=["vector_cosine_ops"]),
            models.Index(fields=["owner", "embedding_model"], name="ai_chunk_owner_model_idx"),
        ]