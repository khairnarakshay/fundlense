# ai_intelligence/domain/schemas.py
"""
Typed data-transfer objects for the AI intelligence layer.

These are the ONLY shapes that should cross between Django services and the
LLM/graph layer - no raw Django model instances or querysets should ever be
passed into a provider or a graph node. Keeping this boundary typed is what
Section 3 of the project brief means by "AI services should consume explicitly
defined data-transfer objects... instead of querying arbitrary database
records." Portfolio-specific DTOs (snapshot, analysis result) are added in
Phase 3 alongside the deterministic analysis engine that produces them - this
file only has the provider-facing shapes needed for Phase 2.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Message types (ChatMessage/role, etc.) are intentionally NOT defined here -
# langchain_core.messages.SystemMessage/HumanMessage/AIMessage are used
# directly throughout this app instead of a parallel custom type. See
# llm/factory.py and application/chat_service.py.


# ---------------------------------------------------------------------------
# Phase 3: deterministic portfolio analysis DTOs
# ---------------------------------------------------------------------------

class HoldingSnapshot(BaseModel):
    """One current holding, flattened out of CASSchemeHolding + its resolved
    MutualFundsScheme (if any) - built by portfolio/context_builder.py, the
    ONLY place in this app that touches Django models for portfolio data."""
    isin: str
    scheme_name: str
    amc_name: str
    category: str | None = None
    units: float
    market_value: float
    cost_basis: float | None = None
    is_scheme_resolved: bool
    nav_date: Any = None             # date | None - left as Any to avoid a hard date import here
    expense_ratio: float | None = None
    ret_1y: float | None = None
    cagr_3y: float | None = None
    volatility_1y: float | None = None


class PortfolioSnapshot(BaseModel):
    """Everything the deterministic analysis engine needs - nothing more. This
    is the typed boundary between Django/portfolio services and the AI layer's
    own analysis code (brief Section 3)."""
    as_of: datetime
    holdings: list[HoldingSnapshot]
    total_value: float
    total_cost: float
    holdings_count: int
    unresolved_holdings_count: int


class AllocationItem(BaseModel):
    label: str
    value: float
    percent: float


class ConcentrationMetrics(BaseModel):
    top_holding_name: str | None = None
    top_holding_percent: float | None = None
    top_amc_name: str | None = None
    top_amc_percent: float | None = None
    herfindahl_index: float | None = None   # 0-10000 scale, sum of squared % shares
    herfindahl_label: str | None = None


class DataCompletenessWarning(BaseModel):
    """A specific, named reason the analysis below is incomplete or should be
    read with caution - never silent, per brief Section 6: 'Do not fabricate
    missing metrics or imply that a portfolio is fully analyzed when important
    data is unavailable.'"""
    code: str
    message: str
    affected_schemes: list[str] = Field(default_factory=list)


class HoldingAnalysis(BaseModel):
    """One holding's row in the deterministic analysis. ret_1y / cagr_3y are the
    FUND's own market performance (MutualFundReturnStat), NOT this investor's
    personal return - personal XIRR is not computed yet (see not_computed)."""
    scheme_name: str
    isin: str
    amc_name: str
    category: str | None = None
    market_value: float
    weight_percent: float | None = None      # None when the holding has no live price
    cost_basis: float | None = None
    gain: float | None = None
    gain_percent: float | None = None
    ret_1y: float | None = None
    cagr_3y: float | None = None
    expense_ratio: float | None = None
    is_scheme_resolved: bool


class PortfolioAnalysisResult(BaseModel):
    """Output of the deterministic analysis engine. Every field here is
    computed directly from a PortfolioSnapshot - nothing is LLM-generated.
    `not_computed` explicitly lists metrics the brief asks for that this
    version does NOT produce, and why - see analysis_engine.py."""
    as_of: datetime
    total_value: float
    total_cost: float
    total_gain: float
    total_gain_percent: float | None
    holdings_count: int
    expense_ratio_weighted: float | None
    allocation_by_asset_type: list[AllocationItem]
    allocation_by_amc: list[AllocationItem]
    concentration: ConcentrationMetrics
    portfolio_weighted_volatility_1y: float | None
    warnings: list[DataCompletenessWarning]
    not_computed: list[str]
    holdings: list[HoldingAnalysis] = Field(default_factory=list)


class PortfolioReportNarrative(BaseModel):
    """The LLM-written sections of the dashboard report. Every number in these
    strings must be copied from PortfolioAnalysisResult - the model is told not
    to calculate anything itself (prompts/portfolio_report.py)."""
    overview: str
    performance: str
    allocation_and_diversification: str
    concentration_and_risk: str
    cost_observations: str
    data_quality_notes: str
    points_to_review: list[str]