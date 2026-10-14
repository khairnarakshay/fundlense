# portfolio/services/returns_by_category.py
"""
Matches the 'Returns by Category' panel's Allocation% and CAGR columns - both come
straight from our own MutualFundReturnStat (scheme-level market performance), no
transaction data needed. The XIRR column (the INVESTOR's own annualised return,
which differs from CAGR exactly because it accounts for when they actually bought)
is left as null - it needs the transaction sign-convention confirmation noted in
the response.
"""
from collections import defaultdict

from cas_parser.services.api_services.holdings import market_value


def returns_by_category(holdings):
    buckets = defaultdict(lambda: {"value": 0.0, "weighted_cagr": 0.0, "scheme_ids": set()})

    for h in holdings:
        if not h.scheme_id:
            continue
        value = market_value(h)
        if value is None:
            continue
        category = h.scheme.fund_master.category
        label = category.name if category else "Uncategorized"
        stat = getattr(h.scheme, "return_stat", None)
        cagr = stat.cagr_3y if stat else None

        bucket = buckets[label]
        bucket["value"] += float(value)
        bucket["scheme_ids"].add(h.scheme_id)
        if cagr is not None:
            bucket["weighted_cagr"] += float(value) * cagr

    grand_total = sum(b["value"] for b in buckets.values())
    result = []
    for label, bucket in sorted(buckets.items(), key=lambda kv: -kv[1]["value"]):
        result.append({
            "category": label,
            "fund_count": len(bucket["scheme_ids"]),
            "allocation_percent": round(bucket["value"] / grand_total * 100, 1) if grand_total else 0.0,
            "cagr_3y": round(bucket["weighted_cagr"] / bucket["value"], 2) if bucket["value"] else None,
            "xirr": None,   # pending - see response notes
        })
    return result
