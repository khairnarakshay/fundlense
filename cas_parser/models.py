from django.conf import settings
from django.db import models
from core.models import BaseModel

class CASStatement(BaseModel):
    """
    Stores an uploaded Consolidated Account Statement and its complete
    parsed response for auditability and future data extraction.
    """

    class StatementType(models.TextChoices):
        CAS = "CAS", "CAS"
        CDSL = "CDSL", "CDSL"
        NSDL = "NSDL", "NSDL"
        UNKNOWN = "UNKNOWN", "Unknown"

    class ProcessingStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        PARTIAL = "PARTIAL", "Partially Completed"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cas_statements")
    statement_type = models.CharField(max_length=20, choices=StatementType.choices, default=StatementType.CAS)
    statement_from = models.DateField(null=True, blank=True)
    statement_to = models.DateField(null=True, blank=True)
    investor_name = models.CharField(max_length=255, blank=True)
    investor_pan = models.CharField(max_length=10, blank=True, db_index=True)
    source_file = models.FileField(upload_to="cas_statements/%Y/%m/", null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)
    parser_version = models.CharField(max_length=100, blank=True)
    processing_status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING, db_index=True)
    processing_message = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cas_statement"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "file_hash"], name="unique_user_cas_file_hash"),
        ]

    def __str__(self):
        """Return a readable representation of the uploaded statement."""
        return f"{self.investor_name or self.user} - {self.statement_from} to {self.statement_to}"

class CASFolio(BaseModel):
    """
    Stores folio-level information extracted from a CAS statement.
    A folio belongs to one CAS statement and may contain multiple schemes.
    """

    statement = models.ForeignKey(CASStatement, on_delete=models.CASCADE, related_name="folios")
    folio_number = models.CharField(max_length=100, db_index=True)
    amc_name = models.CharField(max_length=255, blank=True)
    investor_name = models.CharField(max_length=255, blank=True)
    investor_pan = models.CharField(max_length=10, blank=True, db_index=True)
    kyc_status = models.CharField(max_length=50, blank=True)
    pan_kyc_status = models.CharField(max_length=50, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cas_folio"
        ordering = ["amc_name", "folio_number"]
        constraints = [
            models.UniqueConstraint(fields=["statement", "folio_number", "amc_name"], name="unique_statement_folio_amc"),
        ]

    def __str__(self):
        """Return the folio number and AMC name."""
        return f"{self.amc_name} - {self.folio_number}"

class CASSchemeHolding(BaseModel):
    """
    Stores an investor's holding of a mutual fund scheme within a CAS folio.
    The linked scheme is nullable to support schemes not yet present in the
    mutual fund master database.
    """

    folio = models.ForeignKey(CASFolio, on_delete=models.CASCADE, related_name="scheme_holdings")
    scheme = models.ForeignKey("mutual_fund.MutualFundsScheme", on_delete=models.SET_NULL, null=True, blank=True, related_name="cas_holdings")
    scheme_name = models.CharField(max_length=500)
    advisor = models.CharField(max_length=100, blank=True)
    rta_code = models.CharField(max_length=100, blank=True)
    rta_name = models.CharField(max_length=100, blank=True)
    asset_type = models.CharField(max_length=100, blank=True)
    isin = models.CharField(max_length=20, blank=True, db_index=True)
    amfi_code = models.CharField(max_length=50, blank=True, db_index=True)
    opening_units = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    closing_units = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    calculated_closing_units = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    nominees = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    is_scheme_resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "cas_scheme_holding"
        ordering = ["scheme_name"]
        constraints = [
            models.UniqueConstraint(fields=["folio", "isin", "scheme_name"], name="unique_folio_scheme_isin"),
        ]
        indexes = [
            models.Index(fields=["folio", "scheme_name"]),
            models.Index(fields=["isin", "amfi_code"]),
        ]

    def __str__(self):
        """Return the scheme name and associated folio."""
        return f"{self.scheme_name} - {self.folio.folio_number}"

class CASValuation(BaseModel):
    """
    Stores valuation snapshots reported by the CAS for a scheme holding.
    Multiple valuation records may exist for the same holding over time.
    """

    holding = models.ForeignKey(CASSchemeHolding, on_delete=models.CASCADE, related_name="valuations")
    valuation_date = models.DateField()
    nav = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    cost = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    market_value = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cas_valuation"
        ordering = ["-valuation_date"]
        constraints = [
            models.UniqueConstraint(fields=["holding", "valuation_date"], name="unique_holding_valuation_date"),
        ]

    def __str__(self):
        """Return the holding and valuation date."""
        return f"{self.holding.scheme_name} - {self.valuation_date}"

class CASTransaction(BaseModel):
    """
    Stores every transaction reported for a CAS scheme holding, including
    transactions that do not contain units or NAV such as stamp duty taxes.
    """

    holding = models.ForeignKey(CASSchemeHolding, on_delete=models.CASCADE, related_name="transactions")
    transaction_date = models.DateField()
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    units = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    nav = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    balance = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    transaction_type = models.CharField(max_length=100, blank=True, db_index=True)
    dividend_rate = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    gift_folio = models.CharField(max_length=100, blank=True)
    transaction_hash = models.CharField(max_length=64, db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "cas_transaction"
        ordering = ["transaction_date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["holding", "transaction_hash"], name="unique_holding_transaction_hash"),
        ]
        indexes = [
            models.Index(fields=["holding", "transaction_date"]),
            models.Index(fields=["transaction_type", "transaction_date"]),
        ]

    def __str__(self):
        """Return the transaction type and transaction date."""
        return f"{self.transaction_type} - {self.transaction_date}"

