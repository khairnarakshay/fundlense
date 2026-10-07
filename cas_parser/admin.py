from django.contrib import admin
from .models import (
    CASStatement,
    CASFolio,
    CASSchemeHolding,
    CASValuation,
    CASTransaction,
)


# --- Inlines for nested relationships ---

class CASValuationInline(admin.TabularInline):
    model = CASValuation
    extra = 0
    fields = ("valuation_date", "nav", "cost", "market_value")
    readonly_fields = ("valuation_date",)


class CASTransactionInline(admin.TabularInline):
    model = CASTransaction
    extra = 0
    fields = ("transaction_date", "transaction_type", "amount", "units", "nav", "balance")
    readonly_fields = ("transaction_date", "transaction_hash")


class CASSchemeHoldingInline(admin.TabularInline):
    model = CASSchemeHolding
    extra = 0
    fields = ("scheme_name", "isin", "amfi_code", "closing_units", "is_scheme_resolved")
    readonly_fields = ("scheme_name", "isin", "amfi_code")
    show_change_link = True


class CASFolioInline(admin.StackedInline):
    model = CASFolio
    extra = 0
    fields = ("folio_number", "amc_name", "investor_name", "investor_pan")
    readonly_fields = ("folio_number", "amc_name")
    show_change_link = True


# --- Model Admin Registrations ---

@admin.register(CASStatement)
class CASStatementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "statement_type",
        "investor_name",
        "investor_pan",
        "statement_from",
        "statement_to",
        "processing_status",
        "processed_at",
    )
    list_filter = ("statement_type", "processing_status", "statement_from")
    search_fields = ("user__username", "user__email", "investor_name", "investor_pan", "file_name")
    readonly_fields = ("file_hash", "raw_data", "processed_at")
    inlines = [CASFolioInline]

    fieldsets = (
        ("User & Meta", {"fields": ("user", "statement_type")}),
        ("Timeline", {"fields": ("statement_from", "statement_to", "processed_at")}),
        ("Investor Details", {"fields": ("investor_name", "investor_pan")}),
        ("File Info", {"fields": ("source_file", "file_name", "file_hash")}),
        ("Processing State", {"fields": ("processing_status", "processing_message", "parser_version")}),
        ("Raw Payload", {"classes": ("collapse",), "fields": ("raw_data",)}),
    )


@admin.register(CASFolio)
class CASFolioAdmin(admin.ModelAdmin):
    list_display = ("id", "folio_number", "amc_name", "investor_name", "investor_pan", "statement")
    list_filter = ("amc_name", "kyc_status")
    search_fields = ("folio_number", "amc_name", "investor_name", "investor_pan")
    readonly_fields = ("raw_data",)
    inlines = [CASSchemeHoldingInline]


@admin.register(CASSchemeHolding)
class CASSchemeHoldingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "scheme_name",
        "folio",
        "isin",
        "amfi_code",
        "closing_units",
        "is_scheme_resolved",
    )
    list_filter = ("is_scheme_resolved", "asset_type", "rta_name")
    search_fields = ("scheme_name", "isin", "amfi_code", "rta_code", "folio__folio_number")
    readonly_fields = ("raw_data",)
    inlines = [CASValuationInline, CASTransactionInline]


@admin.register(CASValuation)
class CASValuationAdmin(admin.ModelAdmin):
    list_display = ("id", "holding", "valuation_date", "nav", "cost", "market_value")
    list_filter = ("valuation_date",)
    search_fields = ("holding__scheme_name", "holding__isin")
    readonly_fields = ("raw_data",)


@admin.register(CASTransaction)
class CASTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "holding",
        "transaction_date",
        "transaction_type",
        "amount",
        "units",
        "nav",
        "balance",
    )
    list_filter = ("transaction_type", "transaction_date")
    search_fields = ("holding__scheme_name", "description", "transaction_hash")
    readonly_fields = ("transaction_hash", "raw_data")
