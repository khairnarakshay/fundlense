# ai_intelligence/application/chat_service.py
"""
Phase 4: single-turn portfolio-aware chat. No conversation persistence yet -
that's Phase 6. Every call is grounded fresh in the user's CURRENT
PortfolioAnalysisResult (Phase 3) - there is no stored/cached portfolio
snapshot sitting in a prompt somewhere going stale.
"""
from __future__ import annotations

from ai_intelligence.domain.exceptions import AIIntelligenceError
from ai_intelligence.domain.schemas import ChatMessage, GenerationParams, MessageRole
from ai_intelligence.llm.factory import get_llm_provider
from ai_intelligence.llm.interfaces import LLMProvider
from ai_intelligence.portfolio.analysis_engine import analyze_portfolio
from ai_intelligence.portfolio.context_builder import build_portfolio_snapshot
from ai_intelligence.prompts.system import BASE_SYSTEM_PROMPT, build_grounding_context

MAX_QUESTION_LENGTH = 2000


class ChatInputError(AIIntelligenceError):
    """Raised for invalid chat input (empty/too-long question) - views.py maps
    this to a 400, distinct from a provider/server failure."""


def ask_portfolio_question(user, question: str, provider: LLMProvider | None = None) -> dict:
    """
    provider: inject a fake/stub LLMProvider in tests instead of calling a real
    model - the dependency-injection point the brief asks for (Section 3:
    "Dependency injection or explicit factories for configurable AI
    components"). Defaults to the env-configured provider via the factory.

    Returns a plain dict (not a pydantic model) since this is the final shape
    handed straight to api_response() - see views.py.
    """
    question = (question or "").strip()
    if not question:
        raise ChatInputError("question must not be empty.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise ChatInputError(f"question is too long (max {MAX_QUESTION_LENGTH} characters).")

    snapshot = build_portfolio_snapshot(user)
    analysis = analyze_portfolio(snapshot)

    system_content = BASE_SYSTEM_PROMPT + "\n\n" + build_grounding_context(analysis)
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=system_content),
        ChatMessage(role=MessageRole.USER, content=question),
    ]

    llm = provider or get_llm_provider()
    result = llm.generate(messages, GenerationParams(max_tokens=600, temperature=0.1))

    return {
        "answer": result.content,
        "as_of": analysis.as_of.isoformat(),
        "warnings": [w.message for w in analysis.warnings],
        "not_computed": analysis.not_computed,
        "provider": result.provider,
        "model_id": result.model_id,
    }