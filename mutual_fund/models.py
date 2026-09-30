from django.db import models
from django.db.models import JSONField

from core.models import BaseModel
from core.choices import FUND_TYPE_CHOICES, OPTION_CHOICES, PLAN_CHOICES, SCHEME_RISK_CHOICES, RTA_AGENT_CHOICES


class FundCategory(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_show = models.BooleanField(default=True)

    class Meta:
        db_table = "fund_category"
        ordering = ["name"]

    def __str__(self):
        return self.name


class FundSubCategory(BaseModel):
    category = models.ForeignKey(FundCategory, on_delete=models.PROTECT, related_name="subcategories")
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True, null=True)
    horizon = models.CharField(max_length=255, blank=True, null=True)
    is_show = models.BooleanField(default=True)

    class Meta:
        db_table = "fund_subcategory"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["category", "name"], name="unique_subcategory_per_category")
        ]

    def __str__(self):
        return f"{self.category.name} - {self.name}"


class MutualFundAMC(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    bse_amc_code = models.CharField(max_length=100, blank=True, null=True, unique=True)  # Maps to BSE 'AMC Code'
    website = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="amc_logos/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "mutual_fund_amc"
        ordering = ["name"]

    def __str__(self):
        return self.name


class MutualFundMaster(models.Model):
    fund_house = models.ForeignKey(MutualFundAMC, on_delete=models.PROTECT, related_name="fund_masters")
    category = models.ForeignKey(FundSubCategory, on_delete=models.PROTECT, related_name="fund_masters")
    master_name = models.CharField(max_length=255)
    launch_date = models.DateField(null=True, blank=True)
    investment_objective = models.TextField(null=True, blank=True)
    classification = models.CharField(max_length=100, null=True, blank=True)
    sector = models.CharField(max_length=100, null=True, blank=True)
    information = models.TextField(null=True, blank=True)
    show_on_site = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = "mutual_fund_master"
        ordering = ["master_name"]
        indexes = [
            models.Index(fields=["master_name"]),
            models.Index(fields=["fund_house"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return self.master_name

class MutualFundsScheme(models.Model):
    fund_master = models.ForeignKey(MutualFundMaster, on_delete=models.PROTECT, related_name="schemes")
    scheme_name = models.CharField(max_length=255)

    # ---------------- Scheme Classification ----------------
    fund_type = models.CharField(max_length=30, choices=FUND_TYPE_CHOICES, default="")
    option = models.CharField(max_length=30, choices=OPTION_CHOICES, null=True, blank=True)
    plans = models.CharField(max_length=30, choices=PLAN_CHOICES, null=True, blank=True)

    # ---------------- Core Identifiers ----------------
    amfi_code = models.CharField(max_length=100, unique=True, null=True, blank=True)
    bse_unique_no = models.IntegerField(unique=True, db_index=True)
    scheme_code = models.CharField(max_length=100, db_index=True)
    amc_scheme_code = models.CharField(max_length=100, null=True, blank=True)
    isin_code = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    isin_payout = models.CharField(max_length=12, null=True, blank=True, db_index=True)
    isin_reinvest = models.CharField(max_length=12, null=True, blank=True, db_index=True)

    # ---------------- RTA Information ----------------
    rta_code = models.CharField(max_length=100, null=True, blank=True)
    rta_scheme_code = models.CharField(max_length=100, null=True, blank=True)
    register_agent = models.CharField(max_length=30, choices=RTA_AGENT_CHOICES, null=True, blank=True)

    # ---------------- Scheme Information ----------------
    face_value = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    stated_benchmark = models.CharField(max_length=255, null=True, blank=True)
    investment_objective = models.TextField(null=True, blank=True)
    fund_manager = models.CharField(max_length=255, null=True, blank=True)
    managed_from = models.CharField(max_length=100, null=True, blank=True)
    risk_level = models.CharField(max_length=20, choices=SCHEME_RISK_CHOICES, null=True, blank=True)
    ranking = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(default=0)

    # ---------------- Scheme Dates ----------------
    launch_date = models.DateField(null=True, blank=True)
    nfo_start_date = models.DateField(null=True, blank=True)
    nfo_end_date = models.DateField(null=True, blank=True)
    redemption_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    reopening_date = models.DateField(null=True, blank=True)

    # ---------------- Current NAV ----------------
    current_nav = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    current_nav_date = models.DateField(null=True, blank=True)
    nav_closed = models.BooleanField(default=False)

    # ---------------- BSE Purchase Controls ----------------
    purchase_allowed = models.BooleanField(default=True)
    purchase_transaction_mode = models.CharField(max_length=10, null=True, blank=True, help_text="DP / D / P")
    min_investment = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    additional_investment = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    max_purchase_amount = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    purchase_amount_multiplier = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    purchase_cutoff_time = models.TimeField(null=True, blank=True)

    # ---------------- BSE Redemption Controls ----------------
    redemption_allowed = models.BooleanField(default=True)
    redemption_transaction_mode = models.CharField(max_length=10, null=True, blank=True)
    min_redemption_qty = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    redemption_qty_multiplier = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    max_redemption_qty = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    min_redemption_amount = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    max_redemption_amount = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    redemption_amount_multiple = models.DecimalField(max_digits=15, decimal_places=3, null=True, blank=True)
    redemption_cutoff_time = models.TimeField(null=True, blank=True)

    # ---------------- Operational Flags ----------------
    settlement_type = models.CharField(max_length=10, null=True, blank=True)
    is_amc_active = models.BooleanField(default=True)
    is_dividend_reinvestment = models.BooleanField(default=False)
    is_sip_allowed = models.BooleanField(default=False)
    is_stp_allowed = models.BooleanField(default=False)
    is_swp_allowed = models.BooleanField(default=False)
    is_switch_allowed = models.BooleanField(default=False)

    # ---------------- Exit Load / Lock-in ----------------
    has_exit_load = models.BooleanField(default=False)
    exit_load_value = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    has_lock_in = models.BooleanField(default=False)
    lock_in_period_days = models.IntegerField(default=0)

    # ---------------- Distribution / Partner ----------------
    channel_partner_code = models.CharField(max_length=50, null=True, blank=True)

    # ---------------- Visibility ----------------
    show_on_site = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mutual_fund_scheme"
        ordering = ["scheme_name"]

        indexes = [
            models.Index(fields=["scheme_name"]),
            models.Index(fields=["bse_unique_no"]),
            models.Index(fields=["scheme_code"]),
            models.Index(fields=["isin_code"]),
            models.Index(fields=["amfi_code"]),
            models.Index(fields=["fund_master"]),
        ]

    def __str__(self):
        return self.scheme_name

from django.db import models
from django.db.models import JSONField


class MutualFundPortfolioStat(models.Model):
    scheme = models.OneToOneField(MutualFundsScheme, on_delete=models.CASCADE, related_name="portfolio_stat")

    # ---------------- Debt Fund Metrics ----------------

    average_maturity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    modified_duration = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    yield_to_maturity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # ---------------- Size & Valuation ----------------

    aum = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    portfolio_turnover = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_earning = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_to_bookval = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # ---------------- Portfolio Data ----------------
    asset_allocation = JSONField(null=True, blank=True)
    market_cap_weightage = JSONField(null=True, blank=True)
    holdings = JSONField(null=True, blank=True)
    sectors = JSONField(null=True, blank=True)

    # ---------------- Descriptive Information ----------------
    scheme_category = models.CharField(max_length=255, null=True, blank=True)
    scheme_categorylabel = models.CharField(max_length=255, null=True, blank=True)
    scheme_structure = models.CharField(max_length=255, null=True, blank=True)
    scheme_risk = models.CharField(max_length=255, null=True, blank=True)
    benchmark_index = models.CharField(max_length=255, null=True, blank=True)
    exit_load_msg = models.TextField(null=True, blank=True)
    fund_manager = models.CharField(max_length=255, null=True, blank=True)

    # ---------------- 52 Week NAV ----------------
    _52_week_low_nav = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    _52_week_low_nav_date = models.DateField(null=True, blank=True)
    _52_week_high_nav = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    _52_week_high_nav_date = models.DateField(null=True, blank=True)

    # ---------------- Fund Information ----------------
    inception_date = models.DateField(null=True, blank=True)
    expense_ratio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = "mutual_fund_portfolio_stat"
        ordering = ["-updated"]

        indexes = [
            models.Index(fields=["updated"]),
        ]

    def __str__(self):
        return f"Stat - {self.scheme.scheme_name}"



from django.db import models


class MutualFundNAV(models.Model):
    scheme = models.ForeignKey("MutualFundsScheme", on_delete=models.CASCADE, related_name="navs")
    nav_date = models.DateField()
    nav = models.DecimalField(max_digits=15, decimal_places=4)
    # True = no real NAV published for this date (weekend / holiday / late feed); value duplicated
    # from the last real NAV. Overwritten automatically when the real NAV arrives.
    is_carry_forward = models.BooleanField(default=False)

    class Meta:
        db_table = "mutual_fund_nav"
        constraints = [
            models.UniqueConstraint(fields=["scheme", "nav_date"], name="uq_mf_nav_scheme_date"),
        ]
        indexes = [models.Index(fields=["nav_date"], name="ix_mf_nav_date")]


class MutualFundReturnStat(models.Model):
    scheme = models.OneToOneField("MutualFundsScheme", on_delete=models.CASCADE, related_name="return_stat")
    as_of_date = models.DateField(db_index=True)
    latest_nav = models.DecimalField(max_digits=15, decimal_places=4)
    first_nav_date = models.DateField(null=True, blank=True)

    ret_1w = models.FloatField(null=True, blank=True)
    ret_1m = models.FloatField(null=True, blank=True)
    ret_3m = models.FloatField(null=True, blank=True)
    ret_6m = models.FloatField(null=True, blank=True)
    ret_ytd = models.FloatField(null=True, blank=True)
    ret_1y = models.FloatField(null=True, blank=True)
    ret_3y = models.FloatField(null=True, blank=True)
    ret_5y = models.FloatField(null=True, blank=True)

    cagr_3y = models.FloatField(null=True, blank=True)
    cagr_5y = models.FloatField(null=True, blank=True)
    cagr_10y = models.FloatField(null=True, blank=True)
    cagr_since_inception = models.FloatField(null=True, blank=True)

    volatility_1y = models.FloatField(null=True, blank=True)
    volatility_3y = models.FloatField(null=True, blank=True)
    max_drawdown_1y = models.FloatField(null=True, blank=True)
    max_drawdown_3y = models.FloatField(null=True, blank=True)
    sharpe_3y = models.FloatField(null=True, blank=True)
    sortino_3y = models.FloatField(null=True, blank=True)

    high_52w = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    high_52w_date = models.DateField(null=True, blank=True)
    low_52w = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    low_52w_date = models.DateField(null=True, blank=True)
    calendar_returns = models.JSONField(null=True, blank=True)

    pct_1y = models.FloatField(null=True, blank=True)
    pct_3y = models.FloatField(null=True, blank=True)
    pct_5y = models.FloatField(null=True, blank=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mutual_fund_return_stat"
        indexes = [
            models.Index(fields=["-ret_1y"]),
            models.Index(fields=["-cagr_3y"]),
            models.Index(fields=["-cagr_5y"]),
            models.Index(fields=["volatility_3y"]),
        ]


class MutualFundNavSyncLog(models.Model):
    """One row per NAV date. Re-running the cron the same day updates the same row and bumps run_count."""
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("no_data", "No real NAV for date (holiday / weekend / not yet published) - carried forward"),
        ("failed", "Failed"),
    ]
    nav_date = models.DateField(unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    run_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    active_schemes = models.PositiveIntegerField(default=0)
    rows_in_feed = models.PositiveIntegerField(default=0)
    inserted_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    carried_forward_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    unmapped_count = models.PositiveIntegerField(default=0)
    skipped_closed_count = models.PositiveIntegerField(default=0)
    parse_error_count = models.PositiveIntegerField(default=0)
    newly_closed_count = models.PositiveIntegerField(default=0)
    total_closed = models.PositiveIntegerField(default=0)
    closed_but_reporting = models.PositiveIntegerField(default=0)

    stats_computed = models.PositiveIntegerField(default=0)
    stats_failed = models.PositiveIntegerField(default=0)
    stats_skipped_closed = models.PositiveIntegerField(default=0)

    missing_amfi_codes = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mutual_fund_nav_sync_log"
        ordering = ["-nav_date"]