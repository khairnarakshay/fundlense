# ai_intelligence/management/commands/reindex_knowledge.py
"""
Re-chunk and re-embed every document from its stored text. Run this after changing
AI_EMBEDDING_PROVIDER / AI_EMBEDDING_MODEL_ID.

If the new model has a different number of DIMENSIONS, the vector column must be
changed first - see README, "Changing the embedding model". Vectors from the old
model are never searched once the configured model changes, so until this
command finishes, retrieval simply returns nothing rather than wrong results.
"""
from django.core.management.base import BaseCommand

from ai_intelligence.domain.exceptions import AIIntelligenceError
from ai_intelligence.embeddings.factory import get_embeddings, load_embedding_config
from ai_intelligence.models import KnowledgeDocument
from ai_intelligence.rag.ingestion import reindex_document


class Command(BaseCommand):
    help = "Re-embed all knowledge documents with the currently configured embedding model."

    def handle(self, *args, **opts):
        config = load_embedding_config()
        embeddings = get_embeddings(config)
        failures = 0
        for document in KnowledgeDocument.objects.all():
            try:
                result = reindex_document(document, embeddings=embeddings, config=config)
                self.stdout.write(f"{document.source}: {result.chunk_count} chunks")
            except AIIntelligenceError as exc:
                failures += 1
                self.stderr.write(self.style.ERROR(f"{document.source}: {exc}"))
        self.stdout.write(self.style.SUCCESS(f"Done ({failures} failure(s)) with {config.label}."))