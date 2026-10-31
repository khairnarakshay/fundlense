# ai_intelligence/portfolio/analysis_engine.py
"""
Deterministic portfolio analysis. NO LLM call anywhere in this file - every
number here is computed directly from the PortfolioSnapshot DTO. This is the
authoritative source of truth; a later narration step explains these numbers
in readable text but never overrides or invents them (brief Sections 6, 14).

Pure functions, no Django/DB access - fully unit-testable with hand-built
PortfolioSnapshot objects, independent of the real database.
"""
from __future__ import annotations

from collections import defaultdict

from ai_intelligence.domain.schemas import (
    AllocationItem, ConcentrationMetrics, DataCompletenessWarning,
    HoldingAnalysis, HoldingSnapshot, PortfolioAnalysisResult, PortfolioSnapshot,
)

STALE_NAV_DAYS = 7   # same lookback convention used throughout mutual_fund

# Standard HHI concentration bands (0-10000 scale: sum of squared percentage
# shares). These are the commonly cited DOJ/FTC market-concentration bands,
# applied here to portfolio holding concentration as a clearly-labeled proxy -
# NOT a claim that portfolio concentration and market concentration are the
# same kind of risk.
_HHI_LOW = 1500
_HHI_HIGH = 2500

# Metrics the brief asks for that this version deliberately does NOT compute,
# and why - kept in one place so get_portfolio_analysis() output always lists
# them explicitly rather than silently omitting them.
_NOT_COMPUTED = {
    "xirr": "needs confirmed sign conventions for every CASTransaction.transaction_type",
    "sip_summary": "needs confirmed SIP vs lump-sum transaction_type/description classification",
    "portfolio_overlap": "needs MutualFundPortfolioStat.holdings populated with a confirmed JSON shape",
}


def _bucket(holdings: list[HoldingSnapshot], key_fn, value_fn) -> list[AllocationItem]:
    totals: dict[str, float] = defaultdict(float)
    for h in holdings:
        totals[key_fn(h)] += value_fn(h)
    grand_total = sum(totals.values())
    return [
        AllocationItem(label=label, value=round(v, 2),
                       percent=round(v / grand_total * 100, 1) if grand_total else 0.0)
        for label, v in sorted(totals.items(), key=lambda kv: -kv[1])
    ]


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _holding_rows(holdings: list[HoldingSnapshot], total_value: float) -> list[HoldingAnalysis]:
    """
    One row per holding, largest value first. A holding with no live price
    (unresolved scheme) gets weight/gain = None rather than a misleading 0.
    gain_percent is None when cost is 0 or unknown - never a division error.
    """
    rows: list[HoldingAnalysis] = []
    for h in holdings:
        priced = h.is_scheme_resolved and bool(h.market_value)
        weight = round(h.market_value / total_value * 100, 1) if priced and total_value else None
        gain = round(h.market_value - h.cost_basis, 2) if priced and h.cost_basis is not None else None
        gain_percent = round(gain / h.cost_basis * 100, 2) if gain is not None and h.cost_basis else None
        rows.append(HoldingAnalysis(
            scheme_name=h.scheme_name, isin=h.isin, amc_name=h.amc_name, category=h.category,
            market_value=round(h.market_value, 2), weight_percent=weight,
            cost_basis=_round_or_none(h.cost_basis), gain=gain, gain_percent=gain_percent,
            ret_1y=_round_or_none(h.ret_1y), cagr_3y=_round_or_none(h.cagr_3y),
            expense_ratio=_round_or_none(h.expense_ratio), is_scheme_resolved=h.is_scheme_resolved,
        ))
    rows.sort(key=lambda r: r.market_value, reverse=True)
    return rows


def _herfindahl_index(percentages: list[float]) -> float:
    return round(sum(p ** 2 for p in percentages), 1)


def _herfindahl_label(hhi: float) -> str:
    if hhi < _HHI_LOW:
        return "low concentration (well diversified)"
    if hhi < _HHI_HIGH:
        return "moderate concentration"
    return "high concentration"


def _empty_result(snapshot: PortfolioSnapshot) -> PortfolioAnalysisResult:
    return PortfolioAnalysisResult(
        as_of=snapshot.as_of, total_value=0.0, total_cost=0.0, total_gain=0.0,
        total_gain_percent=None, holdings_count=0, expense_ratio_weighted=None,
        allocation_by_asset_type=[], allocation_by_amc=[],
        concentration=ConcentrationMetrics(),
        portfolio_weighted_volatility_1y=None,
        warnings=[DataCompletenessWarning(code="no_holdings",
                                          message="No current holdings found for this user.")],
        not_computed=sorted(_NOT_COMPUTED),
    )


def analyze_portfolio(snapshot: PortfolioSnapshot) -> PortfolioAnalysisResult:
    """
    Runs every deterministic check and metric against one PortfolioSnapshot.
    Holdings with no resolved scheme are excluded from value-based metrics
    (we have no live NAV for them) but their cost IS still counted - their
    units/cost are real, known facts even without a scheme match.
    """
    if snapshot.holdings_count == 0:
        return _empty_result(snapshot)

    warnings: list[DataCompletenessWarning] = []

    if snapshot.unresolved_holdings_count:
        unresolved_names = [h.scheme_name for h in snapshot.holdings if not h.is_scheme_resolved]
        warnings.append(DataCompletenessWarning(
            code="unresolved_schemes",
            message=(f"{snapshot.unresolved_holdings_count} holding(s) could not be matched to our "
                     f"scheme master data, so they're excluded from value-based metrics below."),
            affected_schemes=unresolved_names,
        ))

    priced_holdings = [h for h in snapshot.holdings if h.market_value and h.is_scheme_resolved]

    stale = [h.scheme_name for h in priced_holdings
            if h.nav_date and (snapshot.as_of.date() - h.nav_date).days > STALE_NAV_DAYS]
    if stale:
        warnings.append(DataCompletenessWarning(
            code="stale_nav",
            message=f"NAV for {len(stale)} holding(s) is more than {STALE_NAV_DAYS} days old.",
            affected_schemes=stale,
        ))

    total_value = sum(h.market_value for h in priced_holdings)
    total_cost = sum(h.cost_basis or 0 for h in snapshot.holdings)
    total_gain = total_value - total_cost
    total_gain_percent = round(total_gain / total_cost * 100, 2) if total_cost else None

    expense_base = sum(h.market_value for h in priced_holdings if h.expense_ratio is not None)
    expense_ratio_weighted = (
        round(sum(h.market_value * h.expense_ratio for h in priced_holdings if h.expense_ratio is not None)
             / expense_base, 2)
        if expense_base else None
    )

    allocation_by_asset_type = _bucket(priced_holdings, lambda h: h.category or "Unclassified",
                                       lambda h: h.market_value)
    allocation_by_amc = _bucket(priced_holdings, lambda h: h.amc_name, lambda h: h.market_value)

    concentration = ConcentrationMetrics()
    if priced_holdings and total_value:
        top_holding = max(priced_holdings, key=lambda h: h.market_value)
        concentration.top_holding_name = top_holding.scheme_name
        concentration.top_holding_percent = round(top_holding.market_value / total_value * 100, 1)

        amc_totals: dict[str, float] = defaultdict(float)
        for h in priced_holdings:
            amc_totals[h.amc_name] += h.market_value
        top_amc_name, top_amc_value = max(amc_totals.items(), key=lambda kv: kv[1])
        concentration.top_amc_name = top_amc_name
        concentration.top_amc_percent = round(top_amc_value / total_value * 100, 1)

        percentages = [h.market_value / total_value * 100 for h in priced_holdings]
        concentration.herfindahl_index = _herfindahl_index(percentages)
        concentration.herfindahl_label = _herfindahl_label(concentration.herfindahl_index)

    vol_base = sum(h.market_value for h in priced_holdings if h.volatility_1y is not None)
    portfolio_weighted_volatility_1y = (
        round(sum(h.market_value * h.volatility_1y for h in priced_holdings if h.volatility_1y is not None)
             / vol_base, 2)
        if vol_base else None
    )
    if portfolio_weighted_volatility_1y is not None:
        warnings.append(DataCompletenessWarning(
            code="volatility_is_weighted_average",
            message=("portfolio_weighted_volatility_1y is a holding-value-weighted average of each "
                     "fund's OWN volatility, not true portfolio volatility - that would require "
                     "correlation between funds, which isn't computed here."),
        ))

    return PortfolioAnalysisResult(
        as_of=snapshot.as_of,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_gain=round(total_gain, 2),
        total_gain_percent=total_gain_percent,
        holdings_count=snapshot.holdings_count,
        expense_ratio_weighted=expense_ratio_weighted,
        allocation_by_asset_type=allocation_by_asset_type,
        allocation_by_amc=allocation_by_amc,
        concentration=concentration,
        portfolio_weighted_volatility_1y=portfolio_weighted_volatility_1y,
        warnings=warnings,
        not_computed=sorted(_NOT_COMPUTED),
        holdings=_holding_rows(snapshot.holdings, total_value),
    )