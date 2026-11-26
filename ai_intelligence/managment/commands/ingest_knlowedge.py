# ai_intelligence/management/commands/ingest_knowledge.py
"""
Add, update or remove SHARED knowledge-base documents (visible to every user's chat).

  python manage.py ingest_knowledge path/to/file.md
  python manage.py ingest_knowledge path/to/folder/ --type education
  python manage.py ingest_knowledge file.pdf --title "HDFC Flexi Cap SID" --type scheme_document --isin INF179K01XXX --version 2026-03
  python manage.py ingest_knowledge --delete "file.md"        (removes the document with that source)

Re-running on unchanged files does nothing; changed files replace their old chunks.
This command is the ONLY way documents enter the knowledge base - there is no upload API.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai_intelligence.domain.exceptions import AIIntelligenceError
from ai_intelligence.models import KnowledgeDocument
from ai_intelligence.rag.chunking import SUPPORTED_SUFFIXES, extract_text
from ai_intelligence.rag.ingestion import ingest_document


class Command(BaseCommand):
    help = "Ingest (or delete) shared knowledge-base documents."

    def add_arguments(self, parser):
        parser.add_argument("path", help="File or folder to ingest; with --delete, the document's source name.")
        parser.add_argument("--title", help="Title (single file only). Default: first heading, else file name.")
        parser.add_argument("--source", help="Source id (single file only). Default: the file name.")
        parser.add_argument("--type", dest="doc_type", default=KnowledgeDocument.DocType.PRODUCT_DOC,
                            choices=KnowledgeDocument.DocType.values)
        parser.add_argument("--isin", default="", help="ISIN for a scheme-specific document.")
        parser.add_argument("--version", default="")
        parser.add_argument("--force", action="store_true", help="Re-embed even if the content is unchanged.")
        parser.add_argument("--delete", action="store_true", help="Delete the shared document whose source is PATH.")

    def handle(self, *args, **opts):
        if opts["delete"]:
            deleted, _ = KnowledgeDocument.objects.filter(source=opts["path"], owner__isnull=True).delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} record(s) for source {opts['path']!r}."))
            return

        target = Path(opts["path"])
        if target.is_dir():
            files = sorted(p for p in target.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
            if opts["title"] or opts["source"]:
                raise CommandError("--title/--source apply to a single file, not a folder.")
        elif target.is_file():
            files = [target]
        else:
            raise CommandError(f"{target} does not exist.")
        if not files:
            raise CommandError("No .md/.txt/.pdf files found.")

        failures = 0
        for path in files:
            try:
                text = extract_text(path)
                title = opts["title"] or _title_from(text) or path.stem.replace("_", " ")
                result = ingest_document(title=title, text=text, source=opts["source"] or path.name,
                                         doc_type=opts["doc_type"], scheme_isin=opts["isin"],
                                         version=opts["version"], force=opts["force"])
                self.stdout.write(f"{path.name}: {result.status} ({result.chunk_count} chunks"
                                  + (f", {result.skipped_suspicious_chunks} skipped" if result.skipped_suspicious_chunks else "")
                                  + ")")
            except AIIntelligenceError as exc:
                failures += 1
                self.stderr.write(self.style.ERROR(f"{path.name}: {exc}"))
        if failures:
            raise CommandError(f"{failures} file(s) failed.")


def _title_from(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
        if line.strip():
            break
    return ""