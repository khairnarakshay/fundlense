# cas_parser/services/ingest.py
"""
Turns a parsed CAS JSON payload into CASFolio / CASSchemeHolding / CASValuation /
CASTransaction rows for one CASStatement.

Verified against a real casparser output sample. Shape:
  top-level: "statement_period": {"from","to"}, "folios": [...],
             "investor_info": {"name","email","address","mobile"}  (ONE block, not per-folio),
             "cas_type": "DETAILED" | "SUMMARY", "file_type": "CAMS"|"KARVY"|"CDSL"|"NSDL"|...,
             "parse_warnings": [...]
  folio:     "folio", "amc", "name" (investor name - NOT "investor_name"), "PAN", "KYC", "PANKYC",
             "schemes": [...]
  scheme:    "scheme", "advisor", "rta_code", "rta", "type", "isin", "amfi", "nominees" (list),
             "open", "close", "close_calculated" (numbers as STRINGS, e.g. "0.162"),
             "valuation": {"date","nav","cost","value"}, "transactions": [...]
  txn:       "date","description","amount","units","nav","balance","type","dividend_rate","gift_folio"
             - amount/units/nav/balance are strings and are frequently explicit JSON null
               (not just absent) for non-unit rows like stamp duty / STT / MISC entries.
"""
import logging

from django.db import transaction
from django.utils import timezone

from cas_parser.services.dates import parse_date
from cas_parser.services.hashing import compute_transaction_hash
from cas_parser.services.scheme_resolver import resolve_scheme

logger = logging.getLogger(__name__)

# casparser's own "file_type" is authoritative over whatever the client guessed when
# uploading (statement_type in the upload request) - a CAMS/KARVY/KFINTECH source is
# always a combined "CAS" statement; CDSL/NSDL sources map to their own choice.
FILE_TYPE_TO_STATEMENT_TYPE = {
    "CAMS": "CAS", "KARVY": "CAS", "KFINTECH": "CAS",
    "CDSL": "CDSL", "NSDL": "NSDL",
}


class CASImportError(Exception):
    """Raised for conditions we want the API view to turn into a specific HTTP status
    (bad password, no transaction data) rather than a generic 500."""

    def __init__(self, message, code="parse_failed"):
        super().__init__(message)
        self.message = message
        self.code = code            # "bad_password" | "summary_statement" | "parse_failed"


def _run_casparser(pdf_path, password):
    import json

    import casparser

    try:
        raw_json = casparser.read_cas_pdf(pdf_path, password, output="json")
    except Exception as exc:                              # noqa: BLE001 - casparser's exception types aren't
        # part of its stable public API, so we classify by message text instead of
        # import-ing internal exception classes that may rename across versions.
        text = str(exc).lower()
        if "password" in text or "decrypt" in text:
            raise CASImportError("Incorrect PDF password.", code="bad_password") from exc
        raise CASImportError(f"Unable to read this PDF: {exc}", code="parse_failed") from exc

    try:
        return json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise CASImportError(f"casparser returned an unexpected format: {exc}", code="parse_failed") from exc


def _count_transactions(parsed):
    return sum(
        len(scheme.get("transactions") or [])
        for folio in (parsed.get("folios") or [])
        for scheme in (folio.get("schemes") or [])
    )


def process_cas_statement(statement, password):
    """
    statement: an already-saved CASStatement (status PENDING, source_file saved).
    Returns (ok: bool, message: str, http_status: int). Never raises - every failure
    path updates `statement` with a status and a user-facing message and returns False.
    http_status lets the API view respond without re-deriving the reason for failure.
    """
    from cas_parser.models import CASFolio, CASSchemeHolding, CASTransaction, CASValuation

    statement.processing_status = statement.ProcessingStatus.PROCESSING
    statement.save(update_fields=["processing_status"])

    try:
        parsed = _run_casparser(statement.source_file.path, password)
    except CASImportError as exc:
        statement.processing_status = statement.ProcessingStatus.FAILED
        statement.processing_message = exc.message
        statement.save(update_fields=["processing_status", "processing_message"])
        status_code = 400 if exc.code == "bad_password" else 422
        return False, exc.message, status_code
    except Exception as exc:                                # noqa: BLE001 - last-resort guard
        logger.exception("Unexpected error parsing CAS statement id=%s", statement.pk)
        statement.processing_status = statement.ProcessingStatus.FAILED
        statement.processing_message = f"Unexpected error: {exc}"
        statement.save(update_fields=["processing_status", "processing_message"])
        return False, statement.processing_message, 500

    statement.raw_data = parsed

    folios = parsed.get("folios") or []
    # casparser flags this itself via "cas_type" - trust that first, and fall back to
    # counting transactions in case an older casparser version doesn't set the flag.
    is_summary = parsed.get("cas_type") == "SUMMARY" or _count_transactions(parsed) == 0
    if is_summary:
        statement.processing_status = statement.ProcessingStatus.FAILED
        statement.processing_message = (
            "This statement does not contain transaction details. It looks like a "
            "Summary Statement - please download and upload a Detailed Statement "
            "(with transactions) from CAMS / KFintech / CDSL / NSDL instead."
        )
        statement.save(update_fields=["raw_data", "processing_status", "processing_message"])
        return False, statement.processing_message, 422

    period = parsed.get("statement_period") or {}
    statement.statement_from = parse_date(period.get("from"))
    statement.statement_to = parse_date(period.get("to"))

    investor_info = parsed.get("investor_info") or {}
    statement.investor_name = investor_info.get("name") or (folios[0].get("name") if folios else "") or ""
    statement.investor_pan = (folios[0].get("PAN") if folios else "") or ""

    mapped_type = FILE_TYPE_TO_STATEMENT_TYPE.get((parsed.get("file_type") or "").upper())
    if mapped_type:
        statement.statement_type = mapped_type

    warnings = parsed.get("parse_warnings") or []
    if warnings:
        statement.processing_message = "Parser warnings: " + "; ".join(str(w) for w in warnings)

    try:
        import casparser
        statement.parser_version = getattr(casparser, "__version__", "")
    except ImportError:
        pass

    counts = {"folios": 0, "schemes": 0, "valuations": 0, "transactions_new": 0, "transactions_skipped": 0}

    try:
        with transaction.atomic():
            for folio_data in folios:
                folio_number = folio_data.get("folio") or ""
                amc_name = folio_data.get("amc") or ""

                folio_obj, _ = CASFolio.objects.update_or_create(
                    statement=statement, folio_number=folio_number, amc_name=amc_name,
                    defaults={
                        # "or ''" everywhere below: casparser emits explicit JSON null (not just a
                        # missing key) for several of these, and these are non-nullable CharFields.
                        "investor_name": folio_data.get("name") or "",
                        "investor_pan": folio_data.get("PAN") or "",
                        "kyc_status": folio_data.get("KYC") or "",
                        "pan_kyc_status": folio_data.get("PANKYC") or "",
                        "raw_data": folio_data,
                    },
                )
                counts["folios"] += 1

                for scheme_data in folio_data.get("schemes") or []:
                    _ingest_scheme(statement, folio_obj, folio_number, amc_name, scheme_data, counts,
                                   CASSchemeHolding, CASValuation, CASTransaction)

            statement.processing_status = statement.ProcessingStatus.COMPLETED
            statement.processing_message = (
                f"Imported {counts['folios']} folio(s), {counts['schemes']} scheme(s), "
                f"{counts['transactions_new']} new transaction(s) "
                f"({counts['transactions_skipped']} already recorded from a previous upload)."
            )
            statement.processed_at = timezone.now()
            statement.save(update_fields=[
                "raw_data", "statement_from", "statement_to", "investor_name", "investor_pan",
                "statement_type", "parser_version", "processing_status", "processing_message",
                "processed_at",
            ])
    except Exception as exc:                                 # noqa: BLE001
        logger.exception("Failed storing CAS statement id=%s", statement.pk)
        # transaction.atomic() already rolled back any partial folio/holding/transaction writes.
        statement.processing_status = statement.ProcessingStatus.FAILED
        statement.processing_message = f"Failed while saving parsed data: {exc}"
        statement.save(update_fields=["processing_status", "processing_message"])
        return False, statement.processing_message, 500

    return True, statement.processing_message, 201


def _ingest_scheme(statement, folio_obj, folio_number, amc_name, scheme_data, counts,
                   CASSchemeHolding, CASValuation, CASTransaction):
    isin = scheme_data.get("isin") or ""
    amfi_code = scheme_data.get("amfi") or ""
    scheme_name = scheme_data.get("scheme") or ""

    holding, _ = CASSchemeHolding.objects.update_or_create(
        folio=folio_obj, isin=isin, scheme_name=scheme_name,
        defaults={
            "advisor": scheme_data.get("advisor") or "",
            "rta_code": scheme_data.get("rta_code") or "",
            "rta_name": scheme_data.get("rta") or "",
            "asset_type": scheme_data.get("type") or "",
            "amfi_code": amfi_code,
            # open/close/close_calculated arrive as numeric strings (e.g. "0.162") - Django's
            # DecimalField converts a well-formed string on save, so no explicit cast needed.
            "opening_units": scheme_data.get("open"),
            "closing_units": scheme_data.get("close"),
            "calculated_closing_units": scheme_data.get("close_calculated"),
            "nominees": scheme_data.get("nominees") or [],
            "raw_data": scheme_data,
        },
    )
    counts["schemes"] += 1

    matched = resolve_scheme(isin, amfi_code)
    if matched and holding.scheme_id != matched.id:
        holding.scheme = matched
        holding.is_scheme_resolved = True
        holding.save(update_fields=["scheme", "is_scheme_resolved"])

    val = scheme_data.get("valuation") or {}
    val_date = parse_date(val.get("date"))
    if val_date:
        CASValuation.objects.update_or_create(
            holding=holding, valuation_date=val_date,
            defaults={
                "nav": val.get("nav"),
                "cost": val.get("cost"),
                "market_value": val.get("value") or val.get("market_value"),
                "raw_data": val,
            },
        )
        counts["valuations"] += 1

    # ---- transaction dedupe across ALL of this user's holdings for this ISIN ----
    # Not just this holding: a re-uploaded / overlapping statement creates a brand new
    # holding row (see module docstring in the model file), so checking only the
    # current holding would let the same real transaction in twice under a new upload.
    user_id = statement.user_id
    existing_hashes = set(
        CASTransaction.objects
        .filter(holding__isin=isin, holding__folio__statement__user_id=user_id)
        .values_list("transaction_hash", flat=True)
    ) if isin else set()

    new_rows = []
    for txn in scheme_data.get("transactions") or []:
        txn_date = parse_date(txn.get("date"))
        h = compute_transaction_hash(
            isin, folio_number, amc_name, txn_date, txn.get("description"),
            txn.get("amount"), txn.get("units"), txn.get("nav"), txn.get("balance"),
            txn.get("type"), txn.get("dividend_rate"),
        )
        if h in existing_hashes:
            counts["transactions_skipped"] += 1
            continue
        existing_hashes.add(h)                               # guards against dupes within this same payload
        new_rows.append(CASTransaction(
            # amount/units/nav/balance: numeric strings or explicit null - both save fine on
            # these nullable DecimalFields. description/type/gift_folio are non-nullable
            # CharFields/TextField, so "or ''" guards against the explicit-null rows (MISC,
            # stamp duty entries sometimes carry null here).
            holding=holding, transaction_date=txn_date, description=txn.get("description") or "",
            amount=txn.get("amount"), units=txn.get("units"), nav=txn.get("nav"),
            balance=txn.get("balance"), transaction_type=txn.get("type") or "",
            dividend_rate=txn.get("dividend_rate"), gift_folio=txn.get("gift_folio") or "",
            transaction_hash=h, raw_data=txn,
        ))

    if new_rows:
        CASTransaction.objects.bulk_create(new_rows, batch_size=1000, ignore_conflicts=True)
        counts["transactions_new"] += len(new_rows)