# portfolio/services/allocation.py
"""Breakdowns that only need current holdings' value - no transaction data involved,
so nothing here depends on the transaction_type question in the response notes."""
from collections import defaultdict

from cas_parser.services.api_services.holdings import market_value


def _bucket_by(holdings, key_fn):
    totals = defaultdict(float)
    for h in holdings:
        value = market_value(h)
        if value is None:
            continue
        totals[key_fn(h)] += float(value)

    grand_total = sum(totals.values())
    return [
        {
            "label": label,
            "value": round(value, 2),
            "percent": round(value / grand_total * 100, 1) if grand_total else 0.0,
        }
        for label, value in sorted(totals.items(), key=lambda kv: -kv[1])
    ]


def by_amc(holdings):
    def key_fn(h):
        if h.scheme_id and h.scheme.fund_master.fund_house_id:
            return h.scheme.fund_master.fund_house.name
        return h.folio.amc_name or "Unknown AMC"
    return _bucket_by(holdings, key_fn)


def by_asset_type(holdings):
    """Equity / Debt / Hybrid / ... from the RESOLVED scheme's own fund_type choice.
    An unresolved holding (no match in our scheme master data) goes to
    "Unclassified" rather than guessing - deliberately no "Over/Under target" badge
    here, since that needs a target allocation from the financial-planning module
    you said to skip."""
    def key_fn(h):
        if h.scheme_id and h.scheme.fund_type:
            return h.scheme.get_fund_type_display()
        return "Unclassified"
    return _bucket_by(holdings, key_fn)
