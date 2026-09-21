"""
Import BSE Scheme Master file (pipe-delimited SCHMSTRDET_*.txt) and update
existing MutualFundsScheme records with BSE/RTA specific data.

Usage:
    python manage.py import_bse_scheme_master <path_to_file>
    python manage.py import_bse_scheme_master <path_to_file> --dry-run
    python manage.py import_bse_scheme_master <path_to_file> --update-by amfi_code
"""

import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from mutual_fund.models import MutualFundsScheme, MutualFundMaster

AMFI_NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
BSE_FILE_NAME = "SCHMSTRDET_20092026.txt"

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

def _normalize_isin(value):
    """Normalize an ISIN value and return None for missing or invalid values."""
    value = _clean(value)

    if not value or value == "-":
        return None

    value = value.upper()

    if len(value) != 12:
        return None

    return value

def _normalize_plan(value):
    """Convert AMFI and BSE plan labels into the model's plan choices."""
    value = _clean(value)

    if not value:
        return None

    normalized = value.upper().replace("-", " ").strip()

    if "DIRECT" in normalized:
        return "DIRECT"

    if "REGULAR" in normalized:
        return "REGULAR"

    return None

def _normalize_option(value):
    """Convert AMFI option labels into normalized option values."""
    value = _clean(value)

    if not value:
        return None

    normalized = re.sub(r"[\s_-]+", " ", value.upper()).strip()

    if "GROWTH" in normalized:
        return "GROWTH"

    if "REINVEST" in normalized:
        return "IDCW_REINVESTMENT"

    if "PAYOUT" in normalized:
        return "IDCW_PAYOUT"

    if normalized == "IDCW" or normalized == "IDCW OPTION":
        return "IDCW"

    return None


def _parse_amfi_date(value):
    """Convert an AMFI NAV date such as 18-Sep-2026 into a date object."""
    value = _clean(value)

    if not value:
        return None

    for date_format in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None


def _value_or_existing(value, existing):
    """Return the parsed value when available, otherwise preserve the existing value."""

    return value if value is not None else existing


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
        """Register optional import execution settings."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and log but do not save.",
        )

        parser.add_argument(
            "--update-by",
            choices=["isin", "amfi_code", "auto"],
            default="auto",
            help="How to link BSE rows to existing schemes.",
        )

    def _load_amfi_nav_data(self):
        """Download and index AMFI NAV records by their available ISIN values."""
        request = Request(
            AMFI_NAV_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        try:
            with urlopen(request, timeout=30) as response:
                content = response.read().decode("utf-8-sig", errors="replace")
        except Exception as exc:
            raise CommandError(f"Unable to download AMFI NAV data: {exc}") from exc

        amfi_records = []
        current_amc = None

        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()

            if not line:
                continue

            parts = [part.strip() for part in line.split(";")]

            if len(parts) != 8:
                current_amc = line
                continue

            scheme_code, isin_primary, isin_reinvest, scheme_name, plan, option, nav, nav_date = parts

            if not scheme_code.isdigit():
                continue

            record = {
                "amfi_code": scheme_code,
                "isin_primary": _normalize_isin(isin_primary),
                "isin_reinvest": _normalize_isin(isin_reinvest),
                "scheme_name": _clean(scheme_name),
                "plan": _normalize_plan(plan),
                "option": _normalize_option(option),
                "current_nav": _to_decimal(nav),
                "current_nav_date": _parse_amfi_date(nav_date),
                "amc_name": current_amc,
            }

            amfi_records.append(record)

        return self._build_amfi_lookup(amfi_records)

    def _build_amfi_lookup(self, records):
        """Build an AMFI lookup using each available ISIN and AMFI code."""
        lookup = {
            "isin": {},
            "amfi_code": {},
        }

        for record in records:
            amfi_code = record.get("amfi_code")

            if amfi_code:
                lookup["amfi_code"][amfi_code] = record

            isins = {
                record.get("isin_primary"),
                record.get("isin_reinvest"),
            }

            for isin in isins:
                if isin:
                    existing = lookup["isin"].get(isin)

                    if existing and existing.get("amfi_code") != amfi_code:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Duplicate AMFI ISIN detected: {isin}"
                            )
                        )

                    lookup["isin"][isin] = record

        return lookup

    def _find_amfi_record(self, amfi_lookup, isins, amfi_code=None):
        """Find an AMFI record using AMFI code or any available scheme ISIN."""
        if amfi_code:
            record = amfi_lookup["amfi_code"].get(amfi_code)

            if record:
                return record

        for isin in isins:
            normalized_isin = _normalize_isin(isin)

            if not normalized_isin:
                continue

            record = amfi_lookup["isin"].get(normalized_isin)

            if record:
                return record

        return None

    def _build_isin_updates(self, amfi_record):
        """Build ISIN field updates according to the AMFI scheme option."""
        if not amfi_record:
            return {}

        option = amfi_record.get("option")
        isin_primary = amfi_record.get("isin_primary")
        isin_reinvest = amfi_record.get("isin_reinvest")

        updates = {}

        if option == "GROWTH":
            if isin_primary:
                updates["isin_code"] = isin_primary

        elif option == "IDCW_PAYOUT":
            if isin_primary:
                updates["isin_payout"] = isin_primary

        elif option == "IDCW_REINVESTMENT":
            if isin_reinvest:
                updates["isin_reinvest"] = isin_reinvest

        else:
            if isin_primary:
                updates["isin_code"] = isin_primary

            if isin_reinvest:
                updates["isin_reinvest"] = isin_reinvest

        return updates

    def _create_new_scheme(self, parts, amfi_record):
        """Create a new mutual fund scheme using BSE and AMFI identifiers."""

        if amfi_record is None:
            return None

        amfi_code = _clean(amfi_record.get("amfi_code"))

        isin_code = (
                amfi_record.get("isin_primary")
                or amfi_record.get("isin_reinvest")
                or _normalize_isin(parts[COL_ISIN])
        )

        scheme_name = (
                _clean(amfi_record.get("scheme_name"))
                or _clean(parts[COL_SCHEME_NAME])
        )

        if not amfi_code or not scheme_name:
            return None

        fund_master = self._find_fund_master(
            parts=parts,
            amfi_record=amfi_record,
        )

        if fund_master is None:
            self.stdout.write(
                self.style.WARNING(
                    f"Fund master not found for AMC code "
                    f"{parts[COL_AMC_CODE]}: {scheme_name}"
                )
            )
            return None

        bse_unique_no = _to_int(parts[COL_UNIQUE_NO], default=0)

        if bse_unique_no <= 0:
            return None

        return MutualFundsScheme.objects.create(
            fund_master=fund_master,
            scheme_name=scheme_name,
            amfi_code=amfi_code,
            bse_unique_no=bse_unique_no,
            scheme_code=_clean(parts[COL_SCHEME_CODE]) or "",
            amc_scheme_code=_clean(parts[COL_AMC_SCHEME_CODE]),
            isin_code=isin_code,
            rta_code=_clean(parts[COL_RTA_AGENT_CODE]),
            rta_scheme_code=_clean(parts[COL_RTA_SCHEME_CODE]),
        )

    def _find_fund_master(self, parts, amfi_record):
        """Find the fund master using the BSE AMC code."""

        from mutual_fund.models import MutualFundMaster

        amc_code = _clean(parts[COL_AMC_CODE])

        if not amc_code:
            return None

        return (
            MutualFundMaster.objects
            .select_related("fund_house")
            .filter(fund_house__bse_amc_code=amc_code)
            .first()
        )    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        """Import BSE scheme data and enrich existing records using AMFI NAV data."""
        dry_run = options["dry_run"]
        update_by = options["update_by"]

        path = Path(__file__).resolve().parent / BSE_FILE_NAME

        if not path.is_file():
            raise CommandError(f"BSE file not found: {path}")

        self.stdout.write(
            self.style.HTTP_INFO(f"Reading BSE file: {path}")
        )

        amfi_lookup = self._load_amfi_nav_data()

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(amfi_lookup['amfi_code'])} AMFI records"
            )
        )

        matched = 0
        created = 0
        unmatched = 0
        skipped = 0
        failed = 0

        with path.open("r", encoding="utf-8-sig", errors="replace") as file:
            for line_number, raw_line in enumerate(file, start=1):
                line = raw_line.strip()

                if not line:
                    skipped += 1
                    continue

                parts = [part.strip() for part in line.split("|")]

                if len(parts) < MIN_COLUMNS:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping line {line_number}: "
                            f"expected {MIN_COLUMNS} columns, got {len(parts)}"
                        )
                    )
                    continue

                # Skip the header row when it is present in the BSE file.
                if parts[COL_UNIQUE_NO].upper() in {
                    "UNIQUE NO",
                    "UNIQUE_NO",
                    "UNIQUE NUMBER",
                }:
                    skipped += 1
                    continue

                bse_unique_no = _clean(parts[COL_UNIQUE_NO])
                bse_scheme_code = _clean(parts[COL_SCHEME_CODE])
                isin = _normalize_isin(parts[COL_ISIN])

                if not bse_unique_no and not bse_scheme_code and not isin:
                    skipped += 1
                    continue

                # Search AMFI using the BSE ISIN first.
                amfi_record = self._find_amfi_record(
                    amfi_lookup=amfi_lookup,
                    isins=[isin],
                    amfi_code=None,
                )

                amfi_code = (
                    amfi_record.get("amfi_code")
                    if amfi_record
                    else None
                )

                scheme = None

                # Match existing schemes by ISIN when requested.
                if update_by in ("isin", "auto") and isin:
                    scheme = (
                        MutualFundsScheme.objects
                        .filter(
                            Q(isin_code=isin)
                            | Q(isin_payout=isin)
                            | Q(isin_reinvest=isin)
                        )
                        .first()
                    )

                # If ISIN matching fails, use the AMFI code obtained from AMFI.
                if (
                    scheme is None
                    and update_by in ("amfi_code", "auto")
                    and amfi_code
                ):
                    scheme = (
                        MutualFundsScheme.objects
                        .filter(amfi_code=amfi_code)
                        .first()
                    )

                is_new_scheme = False

                if scheme is None and dry_run:
                    self.stdout.write(
                        self.style.HTTP_INFO(
                            f"[dry-run] Would create: "
                            f"{_clean(parts[COL_SCHEME_NAME])}"
                        )
                    )
                    unmatched += 1
                    continue

                if scheme is None:
                    scheme = self._create_new_scheme(
                        parts=parts,
                        amfi_record=amfi_record,
                    )

                    if scheme is None:
                        unmatched += 1
                        continue

                    is_new_scheme = True

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"New scheme found: {scheme.scheme_name}"
                        )
                    )




                updates = {
                    # ---------------- Core BSE Identifiers ----------------
                    "bse_unique_no": _to_int(
                        parts[COL_UNIQUE_NO],
                        default=scheme.bse_unique_no,
                    ),
                    "scheme_code": _clean(
                        parts[COL_SCHEME_CODE]
                    ) or scheme.scheme_code,
                    "amc_scheme_code": _clean(
                        parts[COL_AMC_SCHEME_CODE]
                    ) or scheme.amc_scheme_code,

                    # ---------------- RTA Information ----------------
                    "rta_code": _clean(
                        parts[COL_RTA_AGENT_CODE]
                    ) or scheme.rta_code,
                    "rta_scheme_code": _clean(
                        parts[COL_RTA_SCHEME_CODE]
                    ) or scheme.rta_scheme_code,
                    "register_agent": _map_rta_agent(
                        parts[COL_RTA_AGENT_CODE]
                    ) or scheme.register_agent,

                    # ---------------- Scheme Information ----------------
                    "face_value": _value_or_existing(
                        _to_decimal(parts[COL_FACE_VALUE]),
                        scheme.face_value,
                    ),
                    "launch_date": _value_or_existing(
                        _to_date(parts[COL_START_DATE]),
                        scheme.launch_date,
                    ),
                    "end_date": _value_or_existing(
                        _to_date(parts[COL_END_DATE]),
                        scheme.end_date,
                    ),
                    # ---------------- Purchase Controls ----------------
                    "purchase_allowed": _to_bool(
                        parts[COL_PURCHASE_ALLOWED],
                        default=scheme.purchase_allowed,
                    ),
                    "purchase_transaction_mode": _clean(
                        parts[COL_PURCHASE_MODE]
                    ) or scheme.purchase_transaction_mode,
                    "min_investment": _value_or_existing(
                        _to_decimal(parts[COL_MIN_PURCHASE_AMOUNT]),
                        scheme.min_investment,
                    ),
                    "additional_investment": _value_or_existing(
                        _to_decimal(parts[COL_ADDITIONAL_PURCHASE_AMOUNT]),
                        scheme.additional_investment,
                    ),
                    "max_purchase_amount": _value_or_existing(
                        _to_decimal(parts[COL_MAX_PURCHASE_AMOUNT]),
                        scheme.max_purchase_amount,
                    ),
                    "purchase_amount_multiplier": _value_or_existing(
                        _to_decimal(parts[COL_PURCHASE_AMOUNT_MULTIPLIER]),
                        scheme.purchase_amount_multiplier,
                    ),
                    "purchase_cutoff_time": _value_or_existing(
                        _to_time(parts[COL_PURCHASE_CUTOFF]),
                        scheme.purchase_cutoff_time,
                    ),

                    # ---------------- Redemption Controls ----------------
                    "redemption_allowed": _to_bool(
                        parts[COL_REDEMPTION_ALLOWED],
                        default=scheme.redemption_allowed,
                    ),
                    "redemption_transaction_mode": _clean(
                        parts[COL_REDEMPTION_MODE]
                    ) or scheme.redemption_transaction_mode,
                    "min_redemption_qty": _to_decimal(
                        parts[COL_MIN_REDEMPTION_QTY]
                    ),
                    "redemption_qty_multiplier": _to_decimal(
                        parts[COL_REDEMPTION_QTY_MULTIPLIER]
                    ),
                    "max_redemption_qty": _to_decimal(
                        parts[COL_MAX_REDEMPTION_QTY]
                    ),
                    "min_redemption_amount": _to_decimal(
                        parts[COL_MIN_REDEMPTION_AMOUNT]
                    ),
                    "max_redemption_amount": _to_decimal(
                        parts[COL_MAX_REDEMPTION_AMOUNT]
                    ),
                    "redemption_amount_multiple": _to_decimal(
                        parts[COL_REDEMPTION_AMOUNT_MULTIPLE]
                    ),
                    "redemption_cutoff_time": _to_time(
                        parts[COL_REDEMPTION_CUTOFF]
                    ),

                    # ---------------- Operational Flags ----------------
                    "settlement_type": _clean(
                        parts[COL_SETTLEMENT_TYPE]
                    ) or scheme.settlement_type,
                    "is_amc_active": _to_bool(
                        parts[COL_AMC_ACTIVE_FLAG],
                        default=scheme.is_amc_active,
                    ),
                    "is_dividend_reinvestment": _to_bool(
                        parts[COL_DIV_REINVEST_FLAG],
                        default=scheme.is_dividend_reinvestment,
                    ),
                    "is_sip_allowed": _to_bool(
                        parts[COL_SIP_FLAG],
                        default=scheme.is_sip_allowed,
                    ),
                    "is_stp_allowed": _to_bool(
                        parts[COL_STP_FLAG],
                        default=scheme.is_stp_allowed,
                    ),
                    "is_swp_allowed": _to_bool(
                        parts[COL_SWP_FLAG],
                        default=scheme.is_swp_allowed,
                    ),
                    "is_switch_allowed": _to_bool(
                        parts[COL_SWITCH_FLAG],
                        default=scheme.is_switch_allowed,
                    ),

                    # ---------------- Exit Load / Lock-in ----------------
                    "has_exit_load": _to_bool(
                        parts[COL_EXIT_LOAD_FLAG],
                        default=scheme.has_exit_load,
                    ),
                    "exit_load_value": _to_decimal(
                        parts[COL_EXIT_LOAD]
                    ) or scheme.exit_load_value,
                    "has_lock_in": _to_bool(
                        parts[COL_LOCKIN_FLAG],
                        default=scheme.has_lock_in,
                    ),
                    "lock_in_period_days": _to_int(
                        parts[COL_LOCKIN_PERIOD],
                        default=scheme.lock_in_period_days,
                    ),

                    # ---------------- Distribution / Partner ----------------
                    "channel_partner_code": _clean(
                        parts[COL_CHANNEL_PARTNER]
                    ) or scheme.channel_partner_code,

                    # ---------------- Dates ----------------
                    "reopening_date": _to_date(
                        parts[COL_REOPENING_DATE]
                    ),
                }

                # Enrich the record with AMFI data when a matching record exists.
                if amfi_record:
                    updates.update({
                        "amfi_code": amfi_record.get("amfi_code")
                        or scheme.amfi_code,
                        "current_nav": (
                            amfi_record.get("current_nav")
                            or scheme.current_nav
                        ),
                        "current_nav_date": (
                            amfi_record.get("current_nav_date")
                            or scheme.current_nav_date
                        ),
                    })

                    updates.update(
                        self._build_isin_updates(amfi_record)
                    )

                    if amfi_record.get("plan"):
                        updates["plans"] = amfi_record["plan"]

                    if amfi_record.get("option"):
                        updates["option"] = amfi_record["option"]

                if dry_run:
                    self.stdout.write(
                        self.style.HTTP_INFO(
                            f"[dry-run] Line {line_number}: "
                            f"{scheme.scheme_name}"
                        )
                    )
                    matched += 1
                    continue

                try:
                    with transaction.atomic():
                        old_values = {
                            field_name: getattr(scheme, field_name, None)
                            for field_name in updates
                        }




                        changed_fields = {}

                        for field_name, new_value in updates.items():
                            old_value = getattr(scheme, field_name, None)

                            if old_value != new_value:
                                changed_fields[field_name] = {
                                    "old": old_value,
                                    "new": new_value,
                                }

                            setattr(scheme, field_name, new_value)

                        scheme.save(update_fields=list(updates.keys()))

                        scheme.refresh_from_db()

                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Database save completed: {scheme.pk} - {scheme.scheme_name}"
                            )
                        )

                        self.stdout.write(
                            f"Changed fields: {list(changed_fields.keys())}"
                        )

                        for field_name, values in changed_fields.items():
                            saved_value = getattr(scheme, field_name, None)

                            self.stdout.write(
                                f"{field_name}: "
                                f"old={values['old']} | "
                                f"new={values['new']} | "
                                f"saved={saved_value}"
                            )

                    if is_new_scheme:
                        created += 1
                    else:
                        matched += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Updated: {scheme.scheme_name}"
                        )
                    )

                except Exception as exc:
                    failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Failed line {line_number}: {exc}"
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS(
                "\nBSE import completed."
            )
        )

        self.stdout.write(f"Created: {created}")
        self.stdout.write(f"Updated: {matched}")
        self.stdout.write(f"Unmatched: {unmatched}")
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write(f"Failed: {failed}")