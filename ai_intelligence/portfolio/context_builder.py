# ai_intelligence/portfolio/context_builder.py
"""
Builds a typed PortfolioSnapshot from portfolio.services - the ONLY file in
the ai_intelligence app that touches Django models/querysets for portfolio
data. Nothing downstream (analysis_engine, and later the graphs/chat layer)
ever sees a CASSchemeHolding or MutualFundsScheme instance directly - only
this DTO (brief Section 3).

Reuses portfolio.services.holdings exactly as built for the portfolio app's
own summary API - does not recompute units/value/cost itself.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ai_intelligence.domain.schemas import HoldingSnapshot, PortfolioSnapshot
from portfolio.services.api_services.holdings import cost_basis, get_current_holdings, live_market_value, market_value


def _snapshot_holding(h) -> HoldingSnapshot:
    value = live_market_value(h) or market_value(h) or 0
    cost = cost_basis(h)
    scheme = h.scheme if h.scheme_id else None
    return_stat = getattr(scheme, "return_stat", None) if scheme else None
    portfolio_stat = getattr(scheme, "portfolio_stat", None) if scheme else None

    category = None
    if scheme and scheme.fund_master_id and scheme.fund_master.category_id:
        category = scheme.fund_master.category.name

    if scheme and scheme.fund_master_id and scheme.fund_master.fund_house_id:
        amc_name = scheme.fund_master.fund_house.name
    else:
        amc_name = h.folio.amc_name or "Unknown AMC"

    units = h.calculated_closing_units if h.calculated_closing_units is not None else h.closing_units

    return HoldingSnapshot(
        isin=h.isin,
        scheme_name=h.scheme_name,
        amc_name=amc_name,
        category=category,
        units=float(units or 0),
        market_value=float(value),
        cost_basis=float(cost) if cost is not None else None,
        is_scheme_resolved=bool(h.scheme_id),
        nav_date=scheme.current_nav_date if scheme else None,
        expense_ratio=float(portfolio_stat.expense_ratio) if portfolio_stat and portfolio_stat.expense_ratio is not None else None,
        ret_1y=return_stat.ret_1y if return_stat else None,
        cagr_3y=return_stat.cagr_3y if return_stat else None,
        volatility_1y=return_stat.volatility_1y if return_stat else None,
    )


def build_portfolio_snapshot(user) -> PortfolioSnapshot:
    """
    user: the authenticated User instance (request.user) - caller's
    responsibility to have already verified ownership/authentication before
    this is called. This function itself always scopes to the given user via
    get_current_holdings(), the same function the portfolio app's own summary
    API uses.
    """
    holdings = get_current_holdings(user)
    snapshot_holdings = [_snapshot_holding(h) for h in holdings]

    total_value = sum(h.market_value for h in snapshot_holdings)
    total_cost = sum(h.cost_basis or 0 for h in snapshot_holdings)
    unresolved = sum(1 for h in snapshot_holdings if not h.is_scheme_resolved)

    return PortfolioSnapshot(
        as_of=datetime.now(timezone.utc),
        holdings=snapshot_holdings,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        holdings_count=len(snapshot_holdings),
        unresolved_holdings_count=unresolved,
    )