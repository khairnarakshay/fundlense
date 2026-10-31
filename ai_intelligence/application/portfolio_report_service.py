# ai_intelligence/application/portfolio_report_service.py
"""
Dashboard portfolio report: the deterministic analysis (Phase 3) plus an
LLM-written narrative of it, in one response.

Division of labour, per the project's hard rule that math is never done by the
model: analysis_engine.py computes every number; the LLM only WRITES ABOUT
those numbers, and is told not to calculate anything itself.

Caching: a dashboard reloads often, and every uncached load would be an LLM
call. The narrative is cached per USER + a hash of the analysis data and the
prompt text, so (a) it is regenerated automatically when the portfolio data
changes or the prompt is edited, and (b) one user's cached report can never
be served to another - the user's pk is part of the key.
"""
from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

from ai_intelligence.domain.exceptions import LLMProviderError
from ai_intelligence.domain.policies import DISCLAIMER
from ai_intelligence.domain.schemas import PortfolioAnalysisResult, PortfolioReportNarrative
from ai_intelligence.llm.factory import get_chat_model
from ai_intelligence.portfolio.analysis_engine import analyze_portfolio
from ai_intelligence.portfolio.context_builder import build_portfolio_snapshot
from ai_intelligence.prompts.portfolio_report import REPORT_INSTRUCTIONS, build_report_messages

CACHE_TTL_SECONDS = 6 * 60 * 60


def _cache_key(user, analysis: PortfolioAnalysisResult) -> str:
    # as_of changes on every request, so it is excluded - otherwise the hash would
    # never repeat and the cache would never hit.
    payload = json.dumps(analysis.model_dump(mode="json", exclude={"as_of"}), sort_keys=True)
    digest = hashlib.sha256((REPORT_INSTRUCTIONS + payload).encode("utf-8")).hexdigest()
    return f"ai:portfolio_report:{user.pk}:{digest}"


def generate_portfolio_report(user, chat_model=None, use_cache: bool = True) -> dict:
    """
    Returns {"analysis": {...}, "narrative": {...} | None, "cached": bool, "disclaimer": str}.
    chat_model: inject a stub in tests (needs .with_structured_output(schema)
    returning something with .invoke(messages)).
    """
    snapshot = build_portfolio_snapshot(user)
    analysis = analyze_portfolio(snapshot)

    result = {
        "analysis": analysis.model_dump(mode="json"),
        "narrative": None,
        "cached": False,
        "disclaimer": DISCLAIMER,
    }

    # Nothing to write about - skip the LLM call entirely rather than spend a
    # request narrating an empty portfolio.
    if analysis.holdings_count == 0:
        return result

    key = _cache_key(user, analysis)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            result["narrative"] = cached
            result["cached"] = True
            return result

    messages = build_report_messages(analysis)
    model = chat_model or get_chat_model()
    try:
        narrative = model.with_structured_output(PortfolioReportNarrative).invoke(messages)
        if isinstance(narrative, dict):
            narrative = PortfolioReportNarrative(**narrative)
        if narrative is None:
            raise ValueError("model returned no structured output")
    except Exception as exc:                                # noqa: BLE001 - normalize provider/parse failures
        raise LLMProviderError(f"Portfolio report generation failed: {exc}") from exc

    narrative_dict = narrative.model_dump()
    if use_cache:
        cache.set(key, narrative_dict, CACHE_TTL_SECONDS)
    result["narrative"] = narrative_dict
    return result