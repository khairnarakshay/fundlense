from django.contrib import admin
from .models import (
    FundCategory,
    FundSubCategory,
    MutualFundAMC,
    MutualFundMaster,
    MutualFundsScheme,
    MutualFundPortfolioStat, MutualFundNAV, MutualFundReturnStat,
)


# -----------------------------------------------------------------------------
# INLINES
# -----------------------------------------------------------------------------

class MutualFundsSchemeInline(admin.TabularInline):
    """Lists related individual schemes directly inside the Fund Master panel."""
    model = MutualFundsScheme
    extra = 0
    fields = ("scheme_name", "isin_code", "amfi_code", "current_nav", "show_on_site")
    readonly_fields = ("scheme_name", "isin_code", "amfi_code", "current_nav")
    show_change_link = True


class MutualFundPortfolioStatInline(admin.StackedInline):
    """Embeds detailed portfolio metrics inside the respective Scheme editor."""
    model = MutualFundPortfolioStat
    can_delete = False
    verbose_name_plural = "Portfolio Statistics & Allocations"
    fieldsets = (
        ("Metrics & Performance", {
            "fields": ("average_maturity", "modified_duration", "yield_to_maturity", "expense_ratio", "inception_date")
        }),
        ("Size & Valuation", {
            "fields": ("aum", "portfolio_turnover", "price_earning", "price_to_bookval")
        }),
        ("Structural Classifications", {
            "fields": ("scheme_category", "scheme_categorylabel", "scheme_structure", "scheme_risk", "benchmark_index")
        }),
        ("Exit Conditions", {
            "fields": ("exit_load_msg", "fund_manager")
        }),
        ("52 Week NAV Bounds", {
            "fields": (("_52_week_low_nav", "_52_week_low_nav_date"), ("_52_week_high_nav", "_52_week_high_nav_date"))
        }),
        ("Raw Portfolio Breakdown (JSON)", {
            "classes": ("collapse",),
            "fields": ("asset_allocation", "market_cap_weightage", "holdings", "sectors")
        }),
    )


# -----------------------------------------------------------------------------
# ADMIN CONFIGURATIONS
# -----------------------------------------------------------------------------

@admin.register(FundCategory)
class FundCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_show")
    list_filter = ("is_show",)
    search_fields = ("name",)  # Required for autocomplete_fields in FundSubCategoryAdmin


@admin.register(FundSubCategory)
class FundSubCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "horizon", "is_show")
    list_filter = ("is_show", "category", "horizon")
    search_fields = ("name", "category__name")  # Required for autocomplete_fields in MutualFundMasterAdmin


@admin.register(MutualFundAMC)
class MutualFundAMCAdmin(admin.ModelAdmin):
    list_display = ("name", "bse_amc_code", "website", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "bse_amc_code")  # Required for autocomplete_fields in MutualFundMasterAdmin


@admin.register(MutualFundMaster)
class MutualFundMasterAdmin(admin.ModelAdmin):
    list_display = ("master_name", "fund_house", "category", "launch_date", "show_on_site")
    list_filter = ("show_on_site", "fund_house", "category")
    search_fields = ("master_name", "fund_house__name", "category__name")
    autocomplete_fields = ("fund_house", "category")  # Leverages search_fields of parents
    inlines = [MutualFundsSchemeInline]
    readonly_fields = ("created", "updated")


@admin.register(MutualFundsScheme)
class MutualFundsSchemeAdmin(admin.ModelAdmin):
    inlines = [MutualFundPortfolioStatInline]
    autocomplete_fields = ("fund_master",)

    list_display = (
        "scheme_name",
        "fund_master",
        "isin_code",
        "amfi_code",
        "bse_unique_no",
        "current_nav",
        "show_on_site",
    )
    list_filter = (
        "fund_type",
        "option",
        "plans",
        "show_on_site",
        "purchase_allowed",
        "redemption_allowed",
        "register_agent",
        "risk_level",
    )
    search_fields = (
        "scheme_name",
        "isin_code",
        "amfi_code",
        "bse_unique_no",
        "scheme_code",
        "fund_master__master_name",
    )
    readonly_fields = ("created", "updated")

    fieldsets = (
        ("Core Mapping", {
            "fields": ("fund_master", "scheme_name", "show_on_site")
        }),
        ("Categorisation & Identifiers", {
            "fields": (
                "fund_type", "option", "plans",
                "isin_code", "amfi_code", "bse_unique_no",
                "scheme_code", "amc_scheme_code"
            )
        }),
        ("RTA Properties", {
            "fields": ("register_agent", "rta_code", "rta_scheme_code")
        }),
        ("Investment Profiles", {
            "fields": (
                "face_value", "stated_benchmark", "investment_objective",
                "fund_manager", "managed_from", "risk_level", "ranking", "rank"
            )
        }),
        ("Timeline & Milestones", {
            "fields": ("launch_date", "nfo_start_date", "nfo_end_date", "start_date", "end_date", "redemption_date",
                       "reopening_date")
        }),
        ("NAV Valuation", {
            "fields": ("current_nav", "current_nav_date", "nav_closed")
        }),
        ("BSE Purchase Matrix", {
            "fields": (
                "purchase_allowed", "purchase_transaction_mode", "min_investment",
                "additional_investment", "max_purchase_amount",
                "purchase_amount_multiplier", "purchase_cutoff_time"
            )
        }),
        ("BSE Redemption Matrix", {
            "fields": (
                "redemption_allowed", "redemption_transaction_mode", "min_redemption_qty",
                "redemption_qty_multiplier", "max_redemption_qty", "min_redemption_amount",
                "max_redemption_amount", "redemption_amount_multiple", "redemption_cutoff_time"
            )
        }),
        ("Triggers & Actions", {
            "fields": (
                "settlement_type", "is_amc_active", "is_dividend_reinvestment",
                "is_sip_allowed", "is_stp_allowed", "is_swp_allowed", "is_switch_allowed"
            )
        }),
        ("Lock-ins & Threshold Penalties", {
            "fields": ("has_exit_load", "exit_load_value", "has_lock_in", "lock_in_period_days", "channel_partner_code")
        }),
        ("Audits", {
            "classes": ("collapse",),
            "fields": ("created", "updated")
        }),
    )


@admin.register(MutualFundPortfolioStat)
class MutualFundPortfolioStatAdmin(admin.ModelAdmin):
    list_display = ("scheme", "aum", "expense_ratio", "updated")
    search_fields = ("scheme__scheme_name", "scheme__isin_code")
    autocomplete_fields = ("scheme",)
    readonly_fields = ("created", "updated")




@admin.register(MutualFundNAV)
class MutualFundNAVAdmin(admin.ModelAdmin):
    list_display = ("scheme", "nav_date", "nav", "is_carry_forward")
    list_filter = ("is_carry_forward", "nav_date", "scheme")
    search_fields = ("scheme__name",)  # Assumes MutualFundsScheme has a 'name' field
    date_hierarchy = "nav_date"
    ordering = ("-nav_date", "scheme")
    list_per_page = 50

    # Optimization to avoid N+1 queries in admin list view
    def get_queryset(self, request):
        return super().get_queryset(request).select_related("scheme")


@admin.register(MutualFundReturnStat)
class MutualFundReturnStatAdmin(admin.ModelAdmin):
    list_display = ("scheme", "as_of_date", "latest_nav", "ret_1y", "ret_3y", "ret_5y")
    list_filter = ("as_of_date", "scheme")
    search_fields = ("scheme__name",)
    date_hierarchy = "as_of_date"
    ordering = ("scheme",)

    # Grouped fields inside the edit form for better UI layout
    fieldsets = (
        (
            "Core Information",
            {"fields": ("scheme", "as_of_date", "latest_nav", "first_nav_date")},
        ),
        (
            "Short Term Returns",
            {"fields": ("ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_ytd")},
        ),
        ("Long Term Returns (Absolute & CAGR)", {"fields": ("ret_1y", "ret_3y", "ret_5y", "cagr_3y", "cagr_5y", "cagr_10y", "cagr_since_inception")}),
        (
            "Risk Metrics",
            {
                "fields": (
                    "volatility_1y",
                    "volatility_3y",
                    "max_drawdown_1y",
                    "max_drawdown_3y",
                    "sharpe_3y",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("scheme")