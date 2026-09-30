# mutual_fund/management/commands/sync_daily_nav.py
import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from mutual_fund.models import MutualFundNAV, MutualFundNavSyncLog, MutualFundsScheme
from mutual_fund.services.mf_returns import compute_and_store_stats
from mutual_fund.services.nav_utils import (
    MAX_MISSING_CODES_LOGGED, WINDOW_DAYS, carry_forward_missing, eligible_scheme_qs,
    fetch_amfi_text, get_target_nav_date, parse_amfi,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):          # <- Django requires this exact class name
    help = ("Fetch yesterday's NAV from AMFI, upsert (safe to re-run), carry forward gaps, update "
            "nav_closed, recalculate return stats, write sync log.")

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=2,
                            help="Window size ending at target date. Default 2 = yesterday + day before, "
                                 "so late-published NAVs replace earlier carried-forward rows. "
                                 "Use 7 for catch-up after a missed cron.")
        parser.add_argument("--nav-date", type=str, default=None,
                            help="Override target date (YYYY-MM-DD). Default: yesterday.")
        parser.add_argument("--skip-stats", action="store_true",
                            help="Only sync NAVs, do not recalculate return stats.")
        parser.add_argument("--include-closed-stats", action="store_true",
                            help="First run only: also compute stats for schemes that are already closed.")

    def handle(self, *args, **opts):
        self._stats_step_failed = False
        target_date = (datetime.strptime(opts["nav_date"], "%Y-%m-%d").date()
                       if opts["nav_date"] else get_target_nav_date())
        from_date = target_date - timedelta(days=max(opts["days"], 1) - 1)

        log, _ = MutualFundNavSyncLog.objects.get_or_create(nav_date=target_date)
        # Reset per-run counters so a re-run reflects the latest state, not a running total
        for f in ("active_schemes", "rows_in_feed", "inserted_count", "updated_count", "missing_count",
                  "unmapped_count", "skipped_closed_count", "parse_error_count", "newly_closed_count",
                  "total_closed", "closed_but_reporting", "carried_forward_count",
                  "stats_computed", "stats_failed", "stats_skipped_closed"):
            setattr(log, f, 0)
        log.status, log.error_message = "running", ""
        log.run_count += 1
        log.started_at, log.finished_at = timezone.now(), None
        log.missing_amfi_codes = None
        log.save()

        try:
            self._run(log, target_date, from_date, opts)
        except Exception as exc:                       # noqa: BLE001 - top-level guard for cron
            logger.exception("sync_daily_nav failed for %s", target_date)
            log.status = "failed"
            log.error_message = f"{type(exc).__name__}: {exc}"[:4000]
            log.finished_at = timezone.now()
            log.save()
            raise CommandError(f"sync failed: {exc}")   # non-zero exit so cron/monitoring notices

        if self._stats_step_failed:
            raise CommandError("NAV sync OK but stats step failed - see MutualFundNavSyncLog.error_message")

    # ------------------------------------------------------------------
    def _run(self, log, target_date, from_date, opts):
        # ---- 1. fetch + parse (network / parse errors bubble up to handle()) ----
        text = fetch_amfi_text(from_date, target_date)
        parsed, parse_errors = parse_amfi(text)
        log.parse_error_count = parse_errors

        # ---- 2. scheme maps (NFO / no-amfi_code already excluded by eligible_scheme_qs) ----
        # Closed schemes are IGNORED from here on (no NAV write, no stats).
        active_map = dict(eligible_scheme_qs().filter(nav_closed=False).values_list("amfi_code", "id"))
        closed_amfi_codes = set(eligible_scheme_qs().filter(nav_closed=True).values_list("amfi_code", flat=True))
        all_known = set(active_map) | closed_amfi_codes
        log.active_schemes = len(active_map)

        # ---- 3. build rows; dedupe inside the batch (ON CONFLICT can't touch a row twice) ----
        batch = {}                                     # (scheme_id, nav_date) -> nav  (last one wins)
        latest_per_scheme = {}                         # scheme_id -> (nav_date, nav)
        unmapped, skipped_closed, closed_reporting = set(), 0, set()

        for amfi_code, nav, nav_date in parsed:
            if amfi_code in closed_amfi_codes:
                skipped_closed += 1
                if nav_date == target_date:
                    closed_reporting.add(amfi_code)
                continue
            scheme_id = active_map.get(amfi_code)
            if scheme_id is None:
                if amfi_code not in all_known:
                    unmapped.add(amfi_code)
                continue
            batch[(scheme_id, nav_date)] = nav
            prev = latest_per_scheme.get(scheme_id)
            if prev is None or nav_date >= prev[0]:
                latest_per_scheme[scheme_id] = (nav_date, nav)

        log.skipped_closed_count = skipped_closed
        log.unmapped_count = len(unmapped)
        log.closed_but_reporting = len(closed_reporting)

        target_ids_in_feed = {sid for (sid, d) in batch if d == target_date}
        log.rows_in_feed = len(target_ids_in_feed)

        # ---- 4. holiday / weekend / not-yet-published detection ----
        # No early return: window rows (e.g. day before) still get upserted and carry-forward still runs.
        # The only thing a no-data day skips is the nav_closed evaluation (step 9).
        is_no_data_day = not target_ids_in_feed

        # ---- 5. insert vs update counts (for the log) - only REAL rows count ----
        existing_ids = set(MutualFundNAV.objects
                           .filter(nav_date=target_date, scheme_id__in=target_ids_in_feed, is_carry_forward=False)
                           .values_list("scheme_id", flat=True))
        log.updated_count = len(existing_ids)
        log.inserted_count = len(target_ids_in_feed) - len(existing_ids)

        # ---- 6. idempotent upsert, chunked, each chunk in its own transaction ----
        rows = [MutualFundNAV(scheme_id=sid, nav_date=d, nav=nav, is_carry_forward=False)
                for (sid, d), nav in batch.items()]
        failed_chunks = 0
        for i in range(0, len(rows), 5000):
            chunk = rows[i:i + 5000]
            try:
                with transaction.atomic():
                    MutualFundNAV.objects.bulk_create(
                        chunk, update_conflicts=True,
                        unique_fields=["scheme", "nav_date"], update_fields=["nav", "is_carry_forward"])
            except Exception:                            # noqa: BLE001
                failed_chunks += 1
                logger.exception("NAV upsert chunk %s failed", i // 5000)
        if failed_chunks:
            raise RuntimeError(f"{failed_chunks} NAV upsert chunk(s) failed")

        # ---- 7. scheme.current_nav / current_nav_date (REAL rows only, only move forward) ----
        schemes = MutualFundsScheme.objects.in_bulk(list(latest_per_scheme))
        to_update = []
        for sid, (d, nav) in latest_per_scheme.items():
            scheme = schemes.get(sid)
            if scheme and (scheme.current_nav_date is None or d >= scheme.current_nav_date):
                scheme.current_nav, scheme.current_nav_date = nav, d
                to_update.append(scheme)
        try:
            with transaction.atomic():
                MutualFundsScheme.objects.bulk_update(to_update, ["current_nav", "current_nav_date"], batch_size=2000)
        except Exception:                                # noqa: BLE001
            logger.exception("bulk_update current_nav failed")
            raise

        # ---- 8. missing = active schemes with no real row for target date ----
        missing_ids = set(active_map.values()) - target_ids_in_feed
        log.missing_count = len(missing_ids)
        id_to_amfi_code = {v: k for k, v in active_map.items()}
        log.missing_amfi_codes = sorted(id_to_amfi_code[i] for i in missing_ids)[:MAX_MISSING_CODES_LOGGED]

        # ---- 8b. carry forward: duplicate last REAL NAV onto target_date where no row exists ----
        log.carried_forward_count = carry_forward_missing(target_date)

        # ---- 9. close schemes with no REAL NAV inside the 7-day window ----
        # Skipped on a no-data day, so an empty/failed feed can never mass-close schemes.
        # Carry-forward never touches current_nav_date, so copies cannot keep a dead scheme alive.
        newly_closed = 0
        if not is_no_data_day:
            cutoff = target_date - timedelta(days=WINDOW_DAYS)
            newly_closed = (eligible_scheme_qs()
                            .filter(nav_closed=False, current_nav_date__isnull=False,
                                    current_nav_date__lt=cutoff)
                            .update(nav_closed=True))
        log.newly_closed_count = newly_closed
        log.total_closed = MutualFundsScheme.objects.filter(nav_closed=True).count()

        log.status = "no_data" if is_no_data_day else "success"
        log.save()          # NAV part is saved and visible before the stats step starts
        self.stdout.write(self.style.SUCCESS(
            f"{target_date}: status={log.status} inserted={log.inserted_count} updated={log.updated_count} "
            f"missing={log.missing_count} carried_forward={log.carried_forward_count} "
            f"newly_closed={newly_closed} total_closed={log.total_closed}"))

        # ---- 10. return stats, same run (schemes closed in step 9 are skipped here) ----
        # Skipped only if the feed gave no real rows at all, or --skip-stats was passed.
        if opts["skip_stats"] or not batch:
            self.stdout.write("Stats step skipped (no real NAV rows in feed, or --skip-stats).")
        else:
            try:
                computed, failed, skipped_closed_stats = compute_and_store_stats(
                    log, target_date, include_closed=opts["include_closed_stats"])
                self.stdout.write(
                    f"stats computed={computed} failed={failed} skipped_closed={skipped_closed_stats}")
            except Exception as exc:                     # noqa: BLE001
                logger.exception("stats step failed")
                self._stats_step_failed = True
                log.error_message = f"stats step failed: {type(exc).__name__}: {exc}"[:4000]

        log.finished_at = timezone.now()
        log.save()