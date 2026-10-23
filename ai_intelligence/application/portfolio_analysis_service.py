# ai_intelligence/application/portfolio_analysis_service.py
"""
Application-level entry point for Phase 3. Builds a snapshot for the given
user and runs the deterministic analysis engine on it - NO LLM call here.
Narration (turning this into readable text) is a separate, later service, so
these numbers stay correct and testable independent of any model provider.
"""
from ai_intelligence.domain.schemas import PortfolioAnalysisResult
from ai_intelligence.portfolio.analysis_engine import analyze_portfolio
from ai_intelligence.portfolio.context_builder import build_portfolio_snapshot


def get_portfolio_analysis(user) -> PortfolioAnalysisResult:
    snapshot = build_portfolio_snapshot(user)
    return analyze_portfolio(snapshot)