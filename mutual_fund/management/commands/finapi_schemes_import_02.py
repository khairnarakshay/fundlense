"""
Sync mutual-fund schemes from Upvaly FinAPI into local DB.

For every AMC in MutualFundAMC table:
    GET https://finapi.upvaly.com/api/mf/fund-house/{amc.name}
and upsert MutualFundMaster + MutualFundsScheme records.
"""

import time
import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils.text import slugify

from mutual_fund.models import (
    MutualFundAMC,
    MutualFundMaster,
    MutualFundsScheme,
    FundCategory,
    FundSubCategory,
)


# ---------------------------------------------------------------------------
# API config
# ---------------------------------------------------------------------------
BASE_URL = "https://finapi.upvaly.com/api/mf/fund-house/{fund_house_name}"
REQUEST_TIMEOUT = 30
SLEEP_BETWEEN_REQUESTS = 1.0


# ---------------------------------------------------------------------------
# Choice mappings  (API value -> model choice key)
# ---------------------------------------------------------------------------
PLAN_MAP = {
    "direct": "DIRECT",
    "direct plan": "DIRECT",
    "regular": "REGULAR",
    "regular plan": "REGULAR",
}

OPTION_MAP = {
    "growth": "GROWTH",
    "growth option": "GROWTH",
    "idcw": "IDCW",
    "idcw option": "IDCW",
    "idcw payout": "IDCW_PAYOUT",
    "idcw payout option": "IDCW_PAYOUT",
    "dividend payout": "IDCW_PAYOUT",
    "idcw reinvestment": "IDCW_REINVESTMENT",
    "idcw reinvestment option": "IDCW_REINVESTMENT",
    "dividend reinvestment": "IDCW_REINVESTMENT",
}

FUND_TYPE_MAP = {
    "open ended schemes": "OPEN_ENDED",
    "open ended scheme": "OPEN_ENDED",
    "open-ended schemes": "OPEN_ENDED",
    "close ended schemes": "CLOSE_ENDED",
    "close ended scheme": "CLOSE_ENDED",
    "interval": "INTERVAL",
    "interval schemes": "INTERVAL",
    "interval scheme": "INTERVAL",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _clean(value):
    if value is None:
        return None
    val = str(value).strip()
    return val or None


def _match_choice(raw, mapping, default=None):
    """Case-insensitive lookup inside a mapping dict."""
    if not raw:
        return default
    return mapping.get(raw.strip().lower(), default)


def _first_word(text):
    return (text or "").split()[0] if text else ""


def _split_category(label):
    """
    'Equity Scheme - Flexi Cap Fund'  ->  ('Equity Scheme', 'Flexi Cap Fund')
    """
    if not label:
        return "Other", "Other"
    parts = [p.strip() for p in label.split(" - ", 1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return "Other", parts[0]


def fetch_fund_house_schemes(fund_house_name):
    """Hit the API and return the list of scheme dicts."""
    url = BASE_URL.format(fund_house_name=fund_house_name)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise CommandError(f"API failed for '{fund_house_name}': {exc}") from exc

    payload = resp.json()
    if payload.get("status") != "success":
        raise CommandError(
            f"API non-success for '{fund_house_name}': {payload.get('message')}"
        )
    return payload.get("data", []) or []

def _parse_nav(value):
    """Convert an API NAV value into Decimal while preserving missing values."""
    value = _clean(value)
    if value is None:
        return None

    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _parse_nav_date(value):
    """Convert supported API NAV date formats into a Python date."""
    value = _clean(value)
    if value is None:
        return None

    for date_format in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None

# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Fetch schemes for every AMC from Upvaly FinAPI and store them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fund-house",
            type=str,
            default=None,
            help="Optional: sync only this AMC name (exact match).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and log without writing to DB.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        only_house = options.get("fund_house")
        dry_run = options.get("dry_run")

        # ---------- Load ALL AMCs (or a single one) from DB ----------
        qs = MutualFundAMC.objects.filter(is_active=True).order_by("name")
        if only_house:
            qs = qs.filter(name__iexact=only_house)

        total_amc = qs.count()
        if not total_amc:
            raise CommandError("No active AMC found in MutualFundAMC table.")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Loaded {total_amc} AMC(s) from DB. Starting sync...\n"
            )
        )

        grand_total = 0
        for index, amc in enumerate(qs, start=1):
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"[{index}/{total_amc}] → {amc.name}"
                )
            )
            try:
                schemes = fetch_fund_house_schemes(amc.name)
            except CommandError as exc:
                self.stderr.write(self.style.ERROR(f"   {exc}"))
                continue

            if not schemes:
                self.stdout.write(self.style.WARNING("   No schemes returned."))
                continue

            for data in schemes:
                if dry_run:
                    self.stdout.write(
                        f"   [dry-run] {data.get('schemeCode')} – {data.get('schemeName')}"
                    )
                    grand_total += 1
                else:
                    try:
                        self._upsert_scheme(amc, data)
                        grand_total += 1
                    except Exception as exc:      # keep loop going
                        import traceback
                        self.stderr.write(
                            self.style.ERROR(
                                f"   Failed {data.get('schemeCode')}: {exc}"
                            )
                        )
                        traceback.print_exc()

            time.sleep(SLEEP_BETWEEN_REQUESTS)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSync complete. Processed {grand_total} scheme record(s)."
            )
        )

    # ------------------------------------------------------------------
    @transaction.atomic
    def _upsert_scheme(self, amc, data):
        scheme_code = _clean(data.get("schemeCode"))
        scheme_name = _clean(data.get("schemeName"))
        if not scheme_code or not scheme_name:
            raise ValueError("missing schemeCode / schemeName")

        # ---------- 1. SIF handling -------------------------------------
        is_sif = str(data.get("isSIF", "false")).lower() == "true"
        fund_house = amc
        if is_sif:
            fund_house, _ = MutualFundAMC.objects.get_or_create(
                name=f"{amc.name} - SIF",
                defaults={"is_active": True},
            )

        # ---------- 2. Category / SubCategory ---------------------------
        category_name, subcategory_name = _split_category(
            _clean(data.get("schemeCategoryLabel"))
        )

        category, _ = FundCategory.objects.get_or_create(
            name=category_name,
            defaults={"is_show": True},
        )
        subcategory, _ = FundSubCategory.objects.get_or_create(
            category=category,
            name=subcategory_name,
            defaults={"is_show": True},
        )

        # ---------- 3. MutualFundMaster ---------------------------------
        master, _ = MutualFundMaster.objects.update_or_create(
            fund_house=fund_house,
            master_name=scheme_name,
            defaults={
                "category": subcategory,
                "show_on_site": True,
            },
        )

        # ---------- 4. Map choices --------------------------------------
        plan_raw   = _clean(data.get("planName"))
        option_raw = _clean(data.get("optionName"))
        type_raw   = _clean(data.get("schemeStructure"))

        plans     = _match_choice(plan_raw,   PLAN_MAP)
        option    = _match_choice(option_raw, OPTION_MAP)
        fund_type = _match_choice(type_raw,   FUND_TYPE_MAP, default="OPEN_ENDED")

        # ---------- 5. Scheme name --------------------------------------
        # master_name + first word of plan   →  "360 ONE Flexicap Fund - Direct"
        scheme_display_name = scheme_name
        first_plan_word = _first_word(plan_raw)
        option_display_name = _first_word(option_raw)
        if first_plan_word:
            scheme_display_name = f"{scheme_name} - {first_plan_word}-{option_display_name}"


        # NAV parsing
        current_nav = _parse_nav(data.get("latestNav"))
        current_nav_date = _parse_nav_date(data.get("latestNavDate"))

        # BSE unique no is not in API → use numeric schemeCode as placeholder
        bse_unique_no = int(scheme_code) if scheme_code.isdigit() else 0

        isin = _clean(data.get("isinDivPayoutOrGrowth"))
        isin_payout = _clean(data.get("isinDivPayout"))
        isin_reinvest = _clean(data.get("isinDivReinvestment"))



        if isin:
            isin = isin[:12]

        if isin_payout:
            isin_payout = isin_payout[:12]

        if isin_reinvest:
            isin_reinvest = isin_reinvest[:12]

        defaults = {
            "fund_master": master,
            "scheme_name": scheme_display_name,
            "fund_type": fund_type,
            "option": option,
            "plans": plans,
            "amfi_code": scheme_code,
            "bse_unique_no": bse_unique_no,
            "scheme_code": scheme_code,
            "isin_code": isin,
            "isin_payout": isin_payout,
            "isin_reinvest": isin_reinvest,
            "current_nav": current_nav,
            "current_nav_date": current_nav_date,
            "purchase_transaction_mode": "DP",
            "settlement_type": "T1",
            "is_amc_active": True,
            "purchase_allowed": True,
            "redemption_allowed": True,
        }

        scheme, created = MutualFundsScheme.objects.update_or_create(
            amfi_code=scheme_code,
            defaults=defaults,
        )

        action = "Created" if created else "Updated"
        self.stdout.write(
            f"   {action:>7}  {scheme.amfi_code} – {scheme.scheme_name}"
        )