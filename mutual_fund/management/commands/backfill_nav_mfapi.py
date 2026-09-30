# mutual_fund/management/commands/backfill_nav_mfapi.py
import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from mutual_fund.models import MutualFundNAV, MutualFundsScheme
from mutual_fund.services.nav_utils import eligible_scheme_qs

logger = logging.getLogger(__name__)


class Command(BaseCommand):          # <- Django requires this exact class name
    help = ("One-time historical NAV load from api.mfapi.in. Resumable. Also sets current_nav / "
            "current_nav_date so the first sync_daily_nav can evaluate nav_closed correctly.")

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="reload schemes that already have NAV rows")
        parser.add_argument("--amfi-code", dest="amfi_code", help="load a single scheme by amfi_code")
        parser.add_argument("--sleep", type=float, default=0.3)

    def handle(self, *args, **opts):
        qs = eligible_scheme_qs()                        # NFO / no-amfi_code excluded here
        if opts["amfi_code"]:
            qs = qs.filter(amfi_code=opts["amfi_code"])
        already_loaded = set() if opts["force"] else set(
            MutualFundNAV.objects.values_list("scheme_id", flat=True).distinct())

        ok = failed = skipped = 0
        for scheme in qs.iterator():
            amfi_code = scheme.amfi_code
            if scheme.id in already_loaded:
                skipped += 1
                continue
            try:
                data = self._fetch_history(amfi_code)
                rows, latest = {}, None
                for item in data:                        # {"date": "dd-mm-yyyy", "nav": "12.3456"}
                    try:
                        nav_date = datetime.strptime(item["date"], "%d-%m-%Y").date()
                        nav = Decimal(item["nav"])
                        if nav <= 0:
                            continue
                    except (InvalidOperation, ValueError, KeyError, TypeError):
                        continue
                    rows[nav_date] = nav                 # dedupe by date
                    if latest is None or nav_date > latest[0]:
                        latest = (nav_date, nav)
                if not rows:
                    logger.warning("mfapi: no usable rows for amfi_code=%s", amfi_code)
                    failed += 1
                    continue

                objs = [MutualFundNAV(scheme_id=scheme.id, nav_date=d, nav=n, is_carry_forward=False)
                        for d, n in rows.items()]
                with transaction.atomic():
                    MutualFundNAV.objects.bulk_create(objs, batch_size=5000, ignore_conflicts=True)
                    MutualFundsScheme.objects.filter(pk=scheme.pk).update(
                        current_nav=latest[1], current_nav_date=latest[0])
                ok += 1
                self.stdout.write(f"{amfi_code}: {len(objs)} rows")
            except Exception:                            # noqa: BLE001 - keep going; re-run resumes
                failed += 1
                logger.exception("mfapi backfill failed for amfi_code=%s", amfi_code)
            time.sleep(opts["sleep"])

        self.stdout.write(f"backfill done ok={ok} failed={failed} skipped_existing={skipped}")

    @staticmethod
    def _fetch_history(amfi_code, retries=3, backoff=3):
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                resp = requests.get(f"https://api.mfapi.in/mf/{amfi_code}", timeout=60)
                resp.raise_for_status()
                return resp.json().get("data", [])
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                time.sleep(backoff * attempt)
        raise last_exc