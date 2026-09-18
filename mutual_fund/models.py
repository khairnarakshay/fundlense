from django.db import models
from core.models import BaseModel
from core.choices import FUND_TYPE_CHOICES, OPTION_CHOICES, PLAN_CHOICES, SCHEME_RISK_CHOICES,RTA_AGENT_CHOICES
# Create your models here.
class FundCategory(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_show = models.BooleanField(default=True)

    class Meta:
        db_table = "fund_category"
        ordering = ["rank", "name"]

    def __str__(self):
        return self.name

class FundSubCategory(BaseModel):
    category = models.ForeignKey(FundCategory, on_delete=models.PROTECT, related_name="subcategories")
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True, null=True)
    horizon = models.CharField(max_length=255, blank=True, null=True)
    is_show = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fund_subcategory"
        ordering = ["rank", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                name="unique_subcategory_per_category"
            )
        ]

    def __str__(self):
        return f"{self.category.name} - {self.name}"



class MutualFundAMC(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    website = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="amc_logos/", blank=True, null=True)
    is_active = models.BooleanField(default=True)


    class Meta:
        db_table = "mutual_fund_amc"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ==========================================
# 1. THE PARENT FUND MASTER
# ==========================================
class MutualFundMaster(models.Model):
    """
    Represents the main pool of money.
    These fields are identical for both Direct and Regular versions of a fund.
    """
    fund_house = models.ForeignKey(MutualFundAMC, on_delete=models.PROTECT, related_name="fund_masters")
    category = models.ForeignKey(FundSubCategory, on_delete=models.PROTECT, related_name="fund_masters")
    master_name = models.CharField(max_length=255)  # e.g. "Parag Parikh Flexi Cap Fund"

    # Shared historical or descriptive attributes
    launch_date = models.DateField(null=True, blank=True)
    nfo_dates = models.DateField(null=True, blank=True)
    nfo_end_date = models.DateField(null=True, blank=True)
    redemption_date = models.DateField(null=True, blank=True)
    stated_benchmark = models.CharField(max_length=255, null=True, blank=True)
    investment_objective = models.TextField(null=True, blank=True)
    fund_manager = models.CharField(max_length=255, null=True, blank=True)
    managed_From = models.CharField(max_length=100, null=True, blank=True)

    # Classification / UI triggers shared by the whole umbrella fund
    classification = models.CharField(max_length=100, null=True, blank=True)
    sector = models.CharField(max_length=100, null=True, blank=True)  # e.g. Pharma (if sectoral)
    information = models.TextField(null=True, blank=True)
    showonsite = models.BooleanField(default=True)

    class Meta:
        db_table = "mutual_fund_master"

    def __str__(self):
        return self.master_name


# ==========================================
# 2. THE INVESTABLE TRANSACTIONAL SCHEME
# ==========================================
class MutualFundsScheme(models.Model):
    """
    Represents the actual transactable entity you buy.
    Each row has unique AMFI/ISIN codes and distinct transaction limits.
    """
    fund_master = models.ForeignKey(MutualFundMaster, on_delete=models.PROTECT, related_name="schemes")
    scheme_name = models.CharField(max_length=255)  # e.g., "Parag Parikh Flexi Cap Fund - Direct - Growth"

    # Plan Options
    fund_Type = models.CharField(max_length=3, choices=FUND_TYPE_CHOICES, default="", verbose_name="Fund Type")
    option = models.CharField(max_length=3, choices=OPTION_CHOICES, blank=True, null=True, verbose_name="Option")
    plans = models.CharField(max_length=3, choices=PLAN_CHOICES, blank=True, null=True)

    # Unique Regulated System IDs
    amfi_code = models.CharField(max_length=100, unique=True)
    scheme_code = models.CharField(max_length=100, null=True, blank=True)  # Separated AMC Scheme code
    isin_code = models.CharField(max_length=100, null=True, blank=True)
    isin_payout = models.CharField(max_length=100, null=True, blank=True)
    isin_reinvest = models.CharField(max_length=100, null=True, blank=True)

    # RTA structural details
    rta_code = models.CharField(max_length=100, null=True, blank=True)
    rta_scheme_code = models.CharField(max_length=100, null=True, blank=True)
    rta_scheme_code_payout = models.CharField(max_length=100, null=True, blank=True)
    register_agent = models.CharField(max_length=3, choices=RTA_AGENT_CHOICES, blank=True, null=True)

    # Risk and Value Metrics
    face_value = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    risk_level = models.CharField(max_length=20, choices=SCHEME_RISK_CHOICES, null=True, blank=True)
    ranking = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(default=0)

    # Financial & Purchase Rules (Direct and Regular have completely different limits)
    available_for_investment = models.BooleanField(default=True)
    min_investment = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    additional_investment = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    is_sip_allowed = models.BooleanField(default=False)
    min_sip_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    exit_load = models.TextField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mutual_fund_scheme"
        ordering = ["scheme_name"]
        indexes = [
            models.Index(fields=["scheme_name"]),
            models.Index(fields=["amfi_code"]),
            models.Index(fields=["scheme_code"]),
            models.Index(fields=["isin_code"]),
            models.Index(fields=["available_for_investment"]),
        ]

    def __str__(self):
        return self.scheme_name


# ==========================================
# 3. PORTFOLIO STATISTICS (TIME-SERIES)
# ==========================================
class MutualFundPortfolioStat(models.Model):
    """
    All portfolio details are preserved.
    By linking to FundMaster, we capture these stats once for all sub-schemes.
    """
    fund_master = models.ForeignKey(MutualFundMaster, on_delete=models.PROTECT, related_name="portfolio_statistics")
    as_on_date = models.DateField(null=True, blank=True)

    # Asset Allocation Weights
    equity = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    debt = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    others = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    asset_allocation = models.JSONField(default=dict, blank=True)
    market_cap_weightage = models.JSONField(default=dict, blank=True)

    # Debt Maturities Metrics
    avarage_maturity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    modified_duration = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    yield_to_maturity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)

    # Fund Performance Data
    aum = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    portfolio_turnover = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    price_earning = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    price_to_bookval = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    expense_ratio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # 52 Week Tracking Metrics
    _52_week_low_nav = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    _52_week_low_nav_date = models.DateField(null=True, blank=True)
    _52_week_high_nav = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    _52_week_high_nav_date = models.DateField(null=True, blank=True)

    # JSON Arrays & Meta Records
    holdings = models.JSONField(default=list, blank=True)
    sectors = models.JSONField(default=dict, blank=True)
    nav_closed = models.BooleanField(default=False)
    raw_data = models.JSONField(default=dict, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mutual_fund_portfolio_stat"
        ordering = ["-as_on_date", "-updated"]
        constraints = [
            models.UniqueConstraint(
                fields=["fund_master", "as_on_date"],
                name="unique_master_portfolio_date",
            ),
        ]
        indexes = [
            models.Index(fields=["fund_master"]),
            models.Index(fields=["as_on_date"]),
            models.Index(fields=["fund_master", "as_on_date"]),
        ]

    def __str__(self):
        return f"{self.fund_master.master_name} Portfolio Statistics"

