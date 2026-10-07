# cas_parser/services/scheme_resolver.py
"""Match a CAS-reported scheme (ISIN / AMFI code) to our own mutual_fund master data."""
from django.db.models import Q


def resolve_scheme(isin, amfi_code):
    """
    Returns a MutualFundsScheme instance or None. Tries ISIN first (growth/payout/
    reinvest variants all point at the same underlying scheme row in most master-data
    imports), then falls back to amfi_code. A holding that doesn't resolve is NOT an
    error - CASSchemeHolding.scheme is nullable exactly for this case (e.g. a closed /
    merged scheme not present in current master data); it just won't be enriched with
    our own current_nav / return_stat on the dashboard until the scheme master catches up.
    """
    from mutual_fund.models import MutualFundsScheme   # local import avoids an app-load-order dependency

    isin = (isin or "").strip()
    amfi_code = (amfi_code or "").strip()

    if isin:
        scheme = (MutualFundsScheme.objects
                 .filter(Q(isin_code=isin) | Q(isin_payout=isin) | Q(isin_reinvest=isin))
                 .first())
        if scheme:
            return scheme

    if amfi_code:
        return MutualFundsScheme.objects.filter(amfi_code=amfi_code).first()

    return None