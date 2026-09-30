# mutual_fund/services/nav_utils.py
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.db import transaction
from django.utils import timezone

from mutual_fund.models import MutualFundNAV, MutualFundsScheme

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
MAX_MISSING_CODES_LOGGED = 500
AMFI_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?mf=&frmdt={frmdt}&todt={todt}"


def eligible_scheme_qs():
    """
    Single entry point for every scheme loop (sync, stats, backfill).
    NFO placeholders (amfi_code like NFO123 / NFOanything) and schemes without an amfi_code are
    excluded at query level, so they never reach any later step.
    """
    return (MutualFundsScheme.objects
            .exclude(amfi_code__isnull=True)
            .exclude(amfi_code="")
            .exclude(amfi_code__istartswith="NFO"))


def get_target_nav_date():
    """
    AMFI shows yesterday's NAV under yesterday's date, so the daily target is ALWAYS yesterday.
    timezone.localdate() respects settings.TIME_ZONE -> set it to 'Asia/Kolkata'.
    """
    return timezone.localdate() - timedelta(days=1)


def fetch_amfi_text(frmdt, todt, retries=3, backoff=5):
    url = AMFI_URL.format(frmdt=frmdt.strftime("%d-%b-%Y"), todt=todt.strftime("%d-%b-%Y"))
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("AMFI fetch attempt %s/%s failed: %s", attempt, retries, exc)
            time.sleep(backoff * attempt)
    raise last_exc


def parse_amfi(text):
    """
    Returns (rows, parse_errors) where rows = [(amfi_code, nav, nav_date), ...]
    Columns: Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;
             Net Asset Value;Repurchase Price;Sale Price;Date      (verify on a real download)
    Non-data lines (AMC names, category headers, blank) are skipped silently.
    Malformed data lines ('N.A.' NAV, bad date) are counted as parse errors.
    """
    parsed, parse_errors = [], 0
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        amfi_code = parts[0]
        try:
            nav = Decimal(parts[4])
            nav_date = datetime.strptime(parts[7], "%d-%b-%Y").date()
            if nav <= 0:
                raise ValueError("non-positive NAV")
            parsed.append((amfi_code, nav, nav_date))
        except (InvalidOperation, ValueError):
            parse_errors += 1
    return parsed, parse_errors


def carry_forward_missing(target_date):
    """
    Duplicate the last REAL NAV onto target_date for active schemes that have no row for that date
    (weekend / holiday / late publication), so the NAV series is never empty for a day.

      * only if the last real NAV is inside the 7-day window -> lines up with the nav_closed rule
      * uses scheme.current_nav / current_nav_date, which are only ever set from REAL rows
      * current_nav_date is NEVER touched here, so a stopped scheme cannot be kept alive by copies
      * ignore_conflicts: never overwrites an existing row (real or already carried)
    Returns the number of schemes carried forward for target_date.
    """
    window_start = target_date - timedelta(days=WINDOW_DAYS)
    candidates = list(eligible_scheme_qs()
                      .filter(nav_closed=False, current_nav__isnull=False,
                              current_nav_date__gte=window_start, current_nav_date__lt=target_date)
                      .values_list("id", "current_nav"))
    rows = [MutualFundNAV(scheme_id=sid, nav_date=target_date, nav=nav, is_carry_forward=True)
            for sid, nav in candidates]
    for i in range(0, len(rows), 5000):
        with transaction.atomic():
            MutualFundNAV.objects.bulk_create(rows[i:i + 5000], ignore_conflicts=True)
    return len(rows)