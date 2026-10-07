# cas_parser/services/hashing.py
"""
Two different hashes, two different jobs:

  file_hash         - identifies the UPLOADED FILE. Lets us detect "you already
                       uploaded this exact PDF" and skip reprocessing it.

  transaction_hash   - identifies one REAL-WORLD TRANSACTION, independent of which
                       upload/holding row it ends up attached to. This is what makes
                       re-uploading an overlapping or older statement safe: the same
                       transaction parsed out of two different PDFs hashes the same,
                       so it's never double-counted on the dashboard. See
                       services/ingest.py for how this is checked across ALL of a
                       user's holdings for the same ISIN, not just the current one.
"""
import hashlib


def compute_file_hash(uploaded_file):
    """uploaded_file: a Django UploadedFile (request.FILES['file']). Reads in chunks,
    never loads the whole PDF into memory at once, and rewinds the file after hashing
    so it can still be saved to storage afterwards."""
    sha256 = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        sha256.update(chunk)
    uploaded_file.seek(0)
    return sha256.hexdigest()


def compute_transaction_hash(isin, folio_number, amc_name, txn_date, description,
                             amount, units, nav, balance, txn_type, dividend_rate):
    """
    Deliberately does NOT include holding_id or statement_id - those change on every
    re-upload even for the exact same transaction. Everything here comes straight off
    the parsed transaction + its parent scheme/folio, so the hash is stable across
    uploads for the same real-world transaction.
    """
    parts = [isin or "", folio_number or "", amc_name or "", str(txn_date or ""),
             (description or "").strip(), str(amount or ""), str(units or ""),
             str(nav or ""), str(balance or ""), (txn_type or "").strip(),
             str(dividend_rate or "")]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()