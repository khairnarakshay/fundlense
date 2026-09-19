from django.contrib import admin
from django.utils.html import format_html

from mutual_fund.models import (
    FundCategory,
    FundSubCategory,
    MutualFundAMC,
    MutualFundMaster,
    MutualFundsScheme,
    MutualFundportfolioStat,
)


# ---------------------------------------------------------------------------
# Timestamp helpers
#   BaseModel children  → ("created_at", "updated_at")
#   Plain models        → ("created",   "updated")
# ---------------------------------------------------------------------------
def _audit_fields(created_name, updated_name):
    return created_name, updated_name


# ===========================================================================
# FundCategory
# ===========================================================================
@admin.register(FundCategory)
class FundCategoryAdmin(admin.ModelAdmin):
    list_display    = ("name", "is_show", "subcategory_count",
                       "created_at", "updated_at")
    list_filter     = ("is_show",)
    search_fields   = ("name", "description")
    ordering        = ("name",)
    readonly_fields = ("created_at", "updated_at",
                       "created_by", "updated_by")

    @admin.display(description="Sub‑categories")
    def subcategory_count(self, obj):
        return obj.subcategories.count()


# ===========================================================================
# FundSubCategory
# ===========================================================================
@admin.register(FundSubCategory)
class FundSubCategoryAdmin(admin.ModelAdmin):
    list_display        = ("name", "category", "horizon",
                           "is_show", "created_at")
    list_filter         = ("is_show", "category")
    search_fields       = ("name", "description", "category__name")
    autocomplete_fields = ("category",)
    ordering            = ("category__name", "name")
    readonly_fields     = ("created_at", "updated_at",
                           "created_by", "updated_by")


# ===========================================================================
# MutualFundAMC
# ===========================================================================
@admin.register(MutualFundAMC)
class MutualFundAMCAdmin(admin.ModelAdmin):
    list_display = (
        "name", "bse_amc_code", "is_active",
        "fund_master_count", "scheme_count", "logo_preview",
    )
    list_filter     = ("is_active",)
    search_fields   = ("name", "bse_amc_code")
    ordering        = ("name",)
    readonly_fields = ("logo_preview", "created_at", "updated_at",
                       "created_by", "updated_by")

    fieldsets = (
        ("Identity", {
            "fields": ("name", "bse_amc_code", "website",
                       "logo", "logo_preview")
        }),
        ("Status", {
            "fields": ("is_active",
                       "created_at", "updated_at",
                       "created_by", "updated_by")
        }),
    )

    @admin.display(description="Logo")
    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="height:32px;border-radius:4px;" />',
                obj.logo.url,
            )
        return "—"

    @admin.display(description="Masters")
    def fund_master_count(self, obj):
        return obj.fund_masters.count()

    @admin.display(description="Schemes")
    def scheme_count(self, obj):
        return MutualFundsScheme.objects.filter(
            fund_master__fund_house=obj
        ).count()


# ===========================================================================
# Inlines
# ===========================================================================
class MutualFundsSchemeInline(admin.TabularInline):
    model  = MutualFundsScheme
    extra  = 0
    fields = ("scheme_name", "plans", "option", "fund_type",
              "amfi_code", "bse_unique_no", "scheme_code",
              "isin_code", "is_amc_active")
    readonly_fields  = ("bse_unique_no",)
    show_change_link = True


class MutualFundportfolioStatInline(admin.StackedInline):
    model      = MutualFundportfolioStat
    extra      = 0
    max_num    = 1
    can_delete = False
    fields = ("nav_closed", "aum", "portfolio_turnover", "expense_ratio",
              "scheme_categorylabel", "scheme_risk",
              "fund_manager", "benchmark_index", "inception_date",
              "asset_allocation", "market_cap_weightage", "updated")
    readonly_fields  = ("updated",)
    show_change_link = True


# ===========================================================================
# MutualFundMaster  (plain model → created / updated)
# ===========================================================================
@admin.register(MutualFundMaster)
class MutualFundMasterAdmin(admin.ModelAdmin):
    list_display = ("master_name", "fund_house", "category",
                    "fund_manager", "show_on_site", "scheme_count")
    list_filter  = ("show_on_site", "fund_house", "category__category")
    search_fields = ("master_name", "fund_manager", "stated_benchmark")
    autocomplete_fields = ("fund_house", "category")
    ordering = ("master_name",)
    list_select_related = ("fund_house", "category")
    inlines = (MutualFundsSchemeInline, MutualFundportfolioStatInline)
    readonly_fields = ("scheme_count",)

    fieldsets = (
        ("Identity", {
            "fields": ("fund_house", "category", "master_name",
                       "classification", "sector")
        }),
        ("Dates", {
            "fields": ("launch_date", "nfo_dates",
                       "nfo_end_date", "redemption_date")
        }),
        ("Descriptive", {
            "fields": ("stated_benchmark", "investment_objective",
                       "fund_manager", "managed_from", "information")
        }),
        ("Publishing", {"fields": ("show_on_site", "scheme_count")}),
    )

    @admin.display(description="Schemes")
    def scheme_count(self, obj):
        return obj.schemes.count()


# ===========================================================================
# MutualFundsScheme  (plain model → created / updated)
# ===========================================================================
@admin.register(MutualFundsScheme)
class MutualFundsSchemeAdmin(admin.ModelAdmin):
    list_display = (
        "scheme_name", "fund_master", "plans", "option", "fund_type",
        "amfi_code", "bse_unique_no", "isin_code", "is_amc_active",
    )
    list_filter = (
        "plans", "option", "fund_type", "is_amc_active",
        "purchase_allowed", "redemption_allowed",
        "has_exit_load", "has_lock_in", "register_agent",
    )
    search_fields = (
        "scheme_name", "amfi_code", "scheme_code", "bse_unique_no",
        "isin_code", "rta_scheme_code", "amc_scheme_code",
        "fund_master__master_name",
    )
    autocomplete_fields = ("fund_master",)
    ordering        = ("scheme_name",)
    date_hierarchy  = "created"
    list_select_related = ("fund_master",)
    readonly_fields = ("created", "updated")

    fieldsets = (
        ("Parent", {"fields": ("fund_master", "scheme_name")}),
        ("Classification", {"fields": ("fund_type", "option", "plans",
                                       "risk_level", "ranking", "rank")}),
        ("BSE / AMFI identifiers", {
            "fields": ("amfi_code", "bse_unique_no", "scheme_code",
                       "amc_scheme_code", "isin_code")
        }),
        ("RTA info", {"fields": ("rta_code", "rta_scheme_code",
                                 "register_agent", "channel_partner_code")}),
        ("Purchase controls", {
            "fields": ("purchase_allowed", "purchase_transaction_mode",
                       "min_investment", "additional_investment",
                       "max_purchase_amount", "purchase_amount_multiplier",
                       "purchase_cutoff_time")
        }),
        ("Redemption controls", {
            "fields": ("redemption_allowed", "redemption_transaction_mode",
                       "min_redemption_qty", "redemption_qty_multiplier",
                       "max_redemption_qty",
                       "min_redemption_amount", "max_redemption_amount",
                       "redemption_amount_multiple",
                       "redemption_cutoff_time")
        }),
        ("Operational flags", {
            "fields": ("settlement_type", "is_amc_active",
                       "is_dividend_reinvestment",
                       "is_sip_allowed", "is_stp_allowed",
                       "is_swp_allowed", "is_switch_allowed")
        }),
        ("Lifecycle dates", {"fields": ("start_date", "end_date",
                                        "reopening_date", "face_value")}),
        ("Exit load & lock‑in", {
            "fields": ("has_exit_load", "exit_load_value",
                       "has_lock_in", "lock_in_period_days")
        }),
        ("Audit", {"fields": ("created", "updated")}),
    )


# ===========================================================================
# MutualFundportfolioStat  (plain model → created / updated)
# ===========================================================================
@admin.register(MutualFundportfolioStat)
class MutualFundportfolioStatAdmin(admin.ModelAdmin):
    list_display  = ("fund", "aum", "portfolio_turnover", "expense_ratio",
                     "scheme_categorylabel", "scheme_risk",
                     "nav_closed", "updated")
    list_filter   = ("nav_closed", "scheme_risk", "scheme_structure")
    search_fields = ("fund__master_name", "fund__fund_house__name",
                     "fund_manager", "benchmark_index",
                     "scheme_categorylabel")
    autocomplete_fields = ("fund",)
    ordering        = ("-updated",)
    readonly_fields = ("created", "updated")
    list_select_related = ("fund",)

    fieldsets = (
        ("Parent", {"fields": ("fund", "nav_closed")}),
        ("Size & valuation", {
            "fields": ("aum", "portfolio_turnover",
                       "price_earning", "price_to_bookval", "expense_ratio")
        }),
        ("Debt metrics", {
            "fields": ("avarage_maturity", "modified_duration",
                       "yield_to_maturity")
        }),
        ("Breakdowns (JSON)", {
            "fields": ("asset_allocation", "market_cap_weightage",
                       "holdings", "sectors"),
            "classes": ("collapse",),
        }),
        ("Descriptive", {
            "fields": ("scheme_category", "scheme_categorylabel",
                       "scheme_structure", "scheme_risk",
                       "benchmark_index", "fund_manager",
                       "exit_load_msg", "inception_date")
        }),
        ("52‑week NAV", {
            "fields": ("_52_week_low_nav", "_52_week_low_nav_date",
                       "_52_week_high_nav", "_52_week_high_nav_date")
        }),
        ("Audit", {"fields": ("created", "updated")}),
    )