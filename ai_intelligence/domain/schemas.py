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
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """One turn in a conversation sent to an LLM provider."""
    role: MessageRole
    content: str


class GenerationParams(BaseModel):
    """Generation parameters a caller may override; each provider adapter
    translates these into whatever shape its underlying client expects."""
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
    timeout_seconds: int = Field(default=60, gt=0)
    stop: list[str] | None = None


class GenerationResult(BaseModel):
    """Normalized result from any provider - the orchestration layer never sees
    a provider-specific response object."""
    content: str
    provider: str
    model_id: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    raw: dict[str, Any] | None = None   # provider's raw response - populate only where tracing needs it


class ProviderCapability(str, Enum):
    TEXT_GENERATION = "text_generation"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"


class ProviderHealth(BaseModel):
    healthy: bool
    provider: str
    model_id: str
    checked_at: datetime
    detail: str | None = None


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