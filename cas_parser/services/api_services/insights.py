# portfolio/services/insights.py
"""
Top Performers / Needs Attention.

ASSUMPTION - please confirm or correct (see response notes): this ranks holdings by
the SCHEME's own annualised return (MutualFundReturnStat.ret_1y, market-wide,
falling back to cagr_3y for a scheme too new to have a 1Y figure) - NOT a
personalised return based on when this investor actually bought in. If you want the
investor's own XIRR here instead, it needs the transaction sign-convention
clarification noted in the response.
"""
from cas_parser.services.api_services.holdings import market_value


def top_and_needs_attention(holdings, top_n=3):
    scored = []
    for h in holdings:
        if not h.scheme_id:
            continue
        stat = getattr(h.scheme, "return_stat", None)
        ann_return = (stat.ret_1y if stat and stat.ret_1y is not None
                     else (stat.cagr_3y if stat else None))
        if ann_return is None:
            continue
        scored.append({
            "scheme_id": h.scheme_id,
            "scheme_name": h.scheme.scheme_name,
            "plan": h.scheme.plans,
            "option": h.scheme.option,
            "value": round(float(market_value(h) or 0), 2),
            "annualised_return": round(ann_return, 2),
        })

    scored.sort(key=lambda r: r["annualised_return"], reverse=True)
    return {
        "top_performers": scored[:top_n],
        "needs_attention": sorted(scored, key=lambda r: r["annualised_return"])[:top_n],
    }
