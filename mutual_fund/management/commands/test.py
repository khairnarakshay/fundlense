"""
Import BSE Scheme Master file (pipe-delimited SCHMSTRDET_*.txt) and update
existing MutualFundsScheme records with BSE/RTA specific data.

Usage:
    python manage.py import_bse_scheme_master <path_to_file>
    python manage.py import_bse_scheme_master <path_to_file> --dry-run
    python manage.py import_bse_scheme_master <path_to_file> --update-by amfi_code
"""

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from mutual_fund.models import MutualFundsScheme


# ---------------------------------------------------------------------------
# Column indices (0-based) - must match SCHMSTRDET header order
# ---------------------------------------------------------------------------
COL_UNIQUE_NO                  = 0
COL_SCHEME_CODE                = 1
COL_RTA_SCHEME_CODE            = 2
COL_AMC_SCHEME_CODE            = 3
COL_ISIN                       = 4
COL_AMC_CODE                   = 5
COL_SCHEME_TYPE                = 6
COL_SCHEME_PLAN                = 7
COL_SCHEME_NAME                = 8
COL_PURCHASE_ALLOWED           = 9
COL_PURCHASE_MODE              = 10
COL_MIN_PURCHASE_AMOUNT        = 11
COL_ADDITIONAL_PURCHASE_AMOUNT = 12
COL_MAX_PURCHASE_AMOUNT        = 13
COL_PURCHASE_AMOUNT_MULTIPLIER = 14
COL_PURCHASE_CUTOFF            = 15
COL_REDEMPTION_ALLOWED         = 16
COL_REDEMPTION_MODE            = 17
COL_MIN_REDEMPTION_QTY         = 18
COL_REDEMPTION_QTY_MULTIPLIER  = 19
COL_MAX_REDEMPTION_QTY         = 20
COL_MIN_REDEMPTION_AMOUNT      = 21
COL_MAX_REDEMPTION_AMOUNT      = 22
COL_REDEMPTION_AMOUNT_MULTIPLE = 23
COL_REDEMPTION_CUTOFF          = 24
COL_RTA_AGENT_CODE             = 25
COL_AMC_ACTIVE_FLAG            = 26
COL_DIV_REINVEST_FLAG          = 27
COL_SIP_FLAG                   = 28
COL_STP_FLAG                   = 29
COL_SWP_FLAG                   = 30
COL_SWITCH_FLAG                = 31
COL_SETTLEMENT_TYPE            = 32
COL_AMC_IND                    = 33
COL_FACE_VALUE                 = 34
COL_START_DATE                 = 35
COL_END_DATE                   = 36
COL_EXIT_LOAD_FLAG             = 37
COL_EXIT_LOAD                  = 38
COL_LOCKIN_FLAG                = 39
COL_LOCKIN_PERIOD              = 40
COL_CHANNEL_PARTNER            = 41
COL_REOPENING_DATE             = 42

MIN_COLUMNS = 43  # at least up to reopening date


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------
DATE_FORMATS = ("%b %d %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
TIME_FORMATS = ("%H:%M:%S", "%H:%M")


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _to_bool(v, default=False):
    v = _clean(v)
    if v is None:
        return default
    return v.upper() == "Y"


def _to_int(v, default=0):
    v = _clean(v)
    if v is None:
        return default
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def _to_decimal(v):
    v = _clean(v)
    if v is None:
        return None
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError):
        return None


def _to_date(v):
    v = _clean(v)
    if v is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _to_time(v):
    v = _clean(v)
    if v is None:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            continue
    return None


def _map_rta_agent(raw):
    """Map raw RTA Agent Code to the model choice value."""
    raw = _clean(raw)
    if raw is None:
        return None
    up = raw.upper()
    mapping = {
        "CAMS": "CAMS",
        "KARVY": "KARVY",
        "KFINTECH": "KFINTECH",
        "FRANKLIN": "FRANKLIN",
        "SUNDARAM": "SUNDARAM",
        "NIHAL": "NIHAL",
        "OTHER": "OTHER",
    }
    return mapping.get(up, up)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = (
        "Import BSE Scheme Master file and update existing MutualFundsScheme "
        "records with BSE/RTA level data (purchase, redemption, cut-offs, "
        "exit load, lock-in, etc.)."
    )

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str,
                            help="Path to SCHMSTRDET_*.txt file")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and log but do not save.")
        parser.add_argument("--update-by", choices=["isin", "amfi_code", "auto"],
                            default="auto",
                            help="How to link BSE rows to existing schemes.")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        path = options["file_path"]
        dry_run = options["dry_run"]
        update_by = options["update_by"]

        if not os.path.isfile(path):
            raise CommandError(f"File not found: {path}")

        matched = 0
        created_master_only = 0
        unmatched = 0
        skipped = 0

        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            header = fh.readline()  # skip header
            self.stdout.write(self.style.HTTP_INFO(
                f"Header: {header.strip()[:120]}...\n"
            ))

            for lineno, raw_line in enumerate(fh, start=2):
                line = raw_line.rstrip("\r\n")
                if not line or not line.strip("|"):
                    continue

                parts = line.split("|")
                if len(parts) < MIN_COLUMNS:
                    skipped += 1
                    continue

                # ------------------ extract identifiers ------------------
                isin       = _clean(parts[COL_ISIN]) or ""
                scheme_code = _clean(parts[COL_SCHEME_CODE]) or ""
                amfi_code = scheme_code if scheme_code.isdigit() else None

                # ------------------ find matching scheme ---------------
                scheme = None

                if update_by in ("isin", "auto") and isin:
                    scheme = MutualFundsScheme.objects.filter(
                        isin_code=isin
                    ).first()

                if scheme is None and update_by in ("amfi_code", "auto") and amfi_code:
                    scheme = MutualFundsScheme.objects.filter(
                        amfi_code=amfi_code
                    ).first()

                if scheme is None:
                    unmatched += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [line {lineno}] no match  ISIN={isin or '-'}  "
                            f"code={scheme_code}  name={parts[COL_SCHEME_NAME][:60]}"
                        )
                    )
                    continue

                # ------------------ build update dict -------------------
                updates = {
                    "bse_unique_no":         _to_int(parts[COL_UNIQUE_NO]) or scheme.bse_unique_no,
                    "scheme_code":           scheme_code or scheme.scheme_code,
                    "rta_scheme_code":       _clean(parts[COL_RTA_SCHEME_CODE]),
                    "amc_scheme_code":       _clean(parts[COL_AMC_SCHEME_CODE]),
                    "rta_code":              _clean(parts[COL_AMC_CODE]),
                    "register_agent":        _map_rta_agent(parts[COL_RTA_AGENT_CODE]),

                    "purchase_allowed":      _to_bool(parts[COL_PURCHASE_ALLOWED], True),
                    "purchase_transaction_mode": _clean(parts[COL_PURCHASE_MODE]) or "DP",
                    "min_investment":        _to_decimal(parts[COL_MIN_PURCHASE_AMOUNT]),
                    "additional_investment": _to_decimal(parts[COL_ADDITIONAL_PURCHASE_AMOUNT]),
                    "max_purchase_amount":   _to_decimal(parts[COL_MAX_PURCHASE_AMOUNT]) or Decimal("0.000"),
                    "purchase_amount_multiplier": _to_decimal(parts[COL_PURCHASE_AMOUNT_MULTIPLIER]),
                    "purchase_cutoff_time":  _to_time(parts[COL_PURCHASE_CUTOFF]),

                    "redemption_allowed":    _to_bool(parts[COL_REDEMPTION_ALLOWED], True),
                    "redemption_transaction_mode": _clean(parts[COL_REDEMPTION_MODE]),
                    "min_redemption_qty":    _to_decimal(parts[COL_MIN_REDEMPTION_QTY]),
                    "redemption_qty_multiplier": _to_decimal(parts[COL_REDEMPTION_QTY_MULTIPLIER]),
                    "max_redemption_qty":    _to_decimal(parts[COL_MAX_REDEMPTION_QTY]),
                    "min_redemption_amount": _to_decimal(parts[COL_MIN_REDEMPTION_AMOUNT]),
                    "max_redemption_amount": _to_decimal(parts[COL_MAX_REDEMPTION_AMOUNT]),
                    "redemption_amount_multiple": _to_decimal(parts[COL_REDEMPTION_AMOUNT_MULTIPLE]),
                    "redemption_cutoff_time": _to_time(parts[COL_REDEMPTION_CUTOFF]),

                    "settlement_type":       _clean(parts[COL_SETTLEMENT_TYPE]) or "T1",
                    "is_amc_active":         _to_bool(parts[COL_AMC_ACTIVE_FLAG], True),
                    "is_dividend_reinvestment": _to_bool(parts[COL_DIV_REINVEST_FLAG], False),
                    "is_sip_allowed":        _to_bool(parts[COL_SIP_FLAG], False),
                    "is_stp_allowed":        _to_bool(parts[COL_STP_FLAG], False),
                    "is_swp_allowed":        _to_bool(parts[COL_SWP_FLAG], False),
                    "is_switch_allowed":     _to_bool(parts[COL_SWITCH_FLAG], False),

                    "face_value":            _to_decimal(parts[COL_FACE_VALUE]),
                    "start_date":            _to_date(parts[COL_START_DATE]),
                    "end_date":              _to_date(parts[COL_END_DATE]),
                    "reopening_date":        _to_date(parts[COL_REOPENING_DATE]),

                    "has_exit_load":         _to_bool(parts[COL_EXIT_LOAD_FLAG], False),
                    "exit_load_value":       _to_decimal(parts[COL_EXIT_LOAD]) or Decimal("0.00"),
                    "has_lock_in":           _to_bool(parts[COL_LOCKIN_FLAG], False),
                    "lock_in_period_days":   _to_int(parts[COL_LOCKIN_PERIOD], 0),
                    "channel_partner_code":  _clean(parts[COL_CHANNEL_PARTNER]),

                    "rank":                  _to_int(parts[COL_UNIQUE_NO]) or scheme.rank,
                }

                if dry_run:
                    self.stdout.write(
                        f"  [dry-run] {isin or scheme.amfi_code} -> "
                        f"{updates['scheme_name'] if 'scheme_name' in updates else scheme.scheme_name} "
                        f"(bse_no={updates['bse_unique_no']})"
                    )
                    matched += 1
                    continue

                try:
                    with transaction.atomic():
                        for field, value in updates.items():
                            setattr(scheme, field, value)
                        scheme.save(update_fields=list(updates.keys()))
                    matched += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  updated  {scheme.amfi_code or isin}  "
                            f"(bse_no={updates['bse_unique_no']})  {scheme.scheme_name[:60]}"
                        )
                    )
                except Exception as exc:
                    self.stderr.write(
                        self.style.ERROR(
                            f"  [line {lineno}] failed to save {isin}: {exc}"
                        )
                    )

        # ------------------ summary ------------------
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(f"  matched/updated : {matched}")
        self.stdout.write(f"  unmatched       : {unmatched}")
        self.stdout.write(f"  skipped (short) : {skipped}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  (dry-run, nothing saved)"))