# ai_intelligence/management/commands/prune_conversations.py
"""
Retention: delete conversations (and their messages) with no activity for N days.

  python manage.py prune_conversations --days 180
  python manage.py prune_conversations                  (uses AI_CHAT_RETENTION_DAYS; 0 = nothing to do)
  python manage.py prune_conversations --days 180 --dry-run

Schedule it (cron / Celery beat) if you want an automatic retention policy.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from ai_intelligence.conf import ai_int
from ai_intelligence.models import ChatConversation


class Command(BaseCommand):
    help = "Delete conversations inactive for N days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        days = opts["days"] if opts["days"] is not None else ai_int("AI_CHAT_RETENTION_DAYS")
        if days < 0:
            raise CommandError("--days must not be negative.")
        if days == 0:
            self.stdout.write("Retention is 0 (keep forever); nothing to do. Pass --days N to prune.")
            return
        cutoff = timezone.now() - timedelta(days=days)
        stale = ChatConversation.objects.filter(
            Q(last_message_at__lt=cutoff) | Q(last_message_at__isnull=True, created_at__lt=cutoff))
        if opts["dry_run"]:
            self.stdout.write(f"{stale.count()} conversation(s) would be deleted.")
            return
        deleted, _ = stale.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} record(s) (conversations and their messages)."))