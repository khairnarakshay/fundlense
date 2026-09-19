import logging
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from mutual_fund.sync_portfolio_statistic import (
    sync_missing_portfolio_stats,
    sync_portfolio_statistics,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Mutual Fund Portfolio Statistics (run monthly)."

    API_URL = "https://finapi.upvaly.com/api/mf/fund-house/{}"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed logging for debugging.",
        )
        parser.add_argument(
            "--amc",
            type=str,
            help="Sync only a single AMC (for testing).",
        )
        parser.add_argument(
            "--skip-init",
            action="store_true",
            help="Skip STEP 1 (creating missing portfolio-stat rows).",
        )

    def handle(self, *args, **options):
        start_time    = time.time()
        verbose       = options.get("verbose", False)
        specific_amc  = options.get("amc")
        skip_init     = options.get("skip_init", False)

        self.stdout.write(
            "\n timestamp: " + timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self.stdout.write("=" * 80)
        self.stdout.write("Portfolio Stats Sync Started")
        self.stdout.write("=" * 80)

        if specific_amc:
            self.stdout.write(f"Testing mode — syncing only AMC: {specific_amc}")

        # ------------------------------------------------------------------
        # STEP 1
        # ------------------------------------------------------------------
        created_count = 0
        if skip_init:
            self.stdout.write("\nSTEP 1 skipped (--skip-init)")
        else:
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write("STEP 1: Creating missing portfolio stats from Master")
            self.stdout.write("=" * 80)
            created_count = sync_missing_portfolio_stats(
                self, verbose=verbose, specific_amc=specific_amc
            )

        # ------------------------------------------------------------------
        # STEP 2
        # ------------------------------------------------------------------
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("STEP 2: Syncing portfolio statistics from API")
        self.stdout.write("=" * 80)
        result = sync_portfolio_statistics(
            self,
            api_url=self.API_URL,
            verbose=verbose,
            specific_amc=specific_amc,
        )

        duration = round(time.time() - start_time, 2)

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.stdout.write("\n")
        self.stdout.write("=" * 80)
        self.stdout.write("PORTFOLIO STATS SYNC COMPLETED")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total AMC       : {result['total_amc']}")
        self.stdout.write(f"Success AMC     : {result['success_amc']}")
        self.stdout.write(f"Failed AMC      : {result['failed_amc']}")
        self.stdout.write(f"Updated Records : {result['total_updated']}")
        self.stdout.write(f"Created Records : {created_count}")
        self.stdout.write(f"Closed Funds    : {result['total_closed']}")
        self.stdout.write(f"Reopened Funds  : {result['total_reopened']}")
        self.stdout.write(f"Duration        : {duration} sec")
        self.stdout.write("=" * 80)