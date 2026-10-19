# portfolio/services/holdings.py
"""
'Current state' helpers shared by every dashboard API below.

Each CAS upload creates its own CASFolio/CASSchemeHolding snapshot (see
cas_parser/services/ingest.py's module docstring), so one real-world holding is
spread across several CASSchemeHolding rows over time (one per upload that reported
it). Every "what do I own right now" view needs just the LATEST snapshot per distinct
holding - that's what get_current_holdings() returns. Transaction-list views should
NOT use this - they query CASTransaction directly across all holdings, since
transactions for one holding can be split across several historical snapshot rows
(see cas-statement-parser notes on cross-upload transaction dedup).
"""
from cas_parser.models import CASSchemeHolding


def _holding_key(h):
    # ISIN uniquely identifies a holding across uploads. A handful of schemes may be
    # reported with no ISIN; fall back to (AMC, scheme name) for those.
    return h.isin or f"{h.folio.amc_name}|{h.scheme_name}"


def get_current_holdings(user, include_zero_units=False):
    """
    Returns a list[CASSchemeHolding]: the latest snapshot per distinct holding.
    include_zero_units=False (default) excludes fully-redeemed holdings - what the
    dashboard's "current holdings" views want. Pass True for a historical view that
    should include schemes the user no longer holds.
    """
    rows = (CASSchemeHolding.objects
           .filter(folio__statement__user=user)
           .select_related("folio", "folio__statement", "scheme",
                           "scheme__fund_master", "scheme__fund_master__fund_house",
                           "scheme__fund_master__category", "scheme__portfolio_stat",
                           "scheme__return_stat")
           .order_by("-folio__statement__statement_to", "-folio__statement__created_at"))
    print("row")
    latest_by_key = {}
    for h in rows:
        key = _holding_key(h)
        if key not in latest_by_key:          # first seen per key = latest, given the ordering above
            latest_by_key[key] = h

    holdings = list(latest_by_key.values())
    if not include_zero_units:
        holdings = [h for h in holdings if (units_held(h) or 0) > 0]
    return holdings


def units_held(h):
    return h.calculated_closing_units if h.calculated_closing_units is not None else h.closing_units


def latest_valuation(h):
    return h.valuations.order_by("-valuation_date").first()


def market_value(h):
    """Live value when the holding resolves to our own NAV master data, else falls
    back to the RTA-reported market value from the statement's own valuation block."""
    units = units_held(h)
    if h.scheme_id and h.scheme.current_nav is not None and units is not None:
        return units * h.scheme.current_nav
    val = latest_valuation(h)
    return val.market_value if val else None


def cost_basis(h):
    """RTA-reported cost, straight from the statement's own valuation - deliberately
    NOT recomputed from CASTransaction amounts, so this doesn't depend on the
    transaction_type sign conventions that are still pending confirmation (see the
    response notes)."""
    val = latest_valuation(h)
    return val.cost if val else None


def live_market_value(h):
    """Like market_value(), but re-resolves the scheme fresh via ISIN instead of
    trusting h.scheme_id - the FK stored on this holding row at ingestion time,
    which can be stale if this particular holding was first uploaded before its
    scheme existed in mutual_fund master data (see value_history.py's FIX note for
    the full explanation; same bug, same fix, applied here for the summary API's
    "live" current value)."""
    from cas_parser.services.scheme_resolver import resolve_scheme

    units = units_held(h)
    if units is None:
        return None
    scheme = resolve_scheme(h.isin, h.amfi_code)
    if scheme and scheme.current_nav is not None:
        return units * scheme.current_nav
    return None