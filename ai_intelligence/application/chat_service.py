# ai_intelligence/application/chat_service.py
"""
Phase 4: single-turn portfolio-aware chat. No conversation persistence yet -
that's Phase 6. Every call is grounded fresh in the user's CURRENT
PortfolioAnalysisResult (Phase 3).

Uses LangChain's own message types (SystemMessage/HumanMessage) and chat
model interface (.invoke()) directly - no parallel custom LLM abstraction.
The only thing this app adds on top of LangChain is: (1) building the
grounding context from verified portfolio data, and (2) translating whatever
LangChain/the underlying provider raises into OUR domain exceptions, so
views.py can map failures to specific HTTP status codes consistently.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ai_intelligence.domain.exceptions import AIIntelligenceError, LLMProviderError
from ai_intelligence.llm.factory import get_chat_model
from ai_intelligence.portfolio.analysis_engine import analyze_portfolio
from ai_intelligence.portfolio.context_builder import build_portfolio_snapshot
from ai_intelligence.prompts.system import BASE_SYSTEM_PROMPT, build_grounding_context

MAX_QUESTION_LENGTH = 2000


class ChatInputError(AIIntelligenceError):
    """Raised for invalid chat input (empty/too-long question) - views.py maps
    this to a 400, distinct from a provider/server failure."""


def ask_portfolio_question(user, question: str, chat_model=None) -> dict:
    """
    chat_model: inject a fake/stub object (anything with an .invoke(messages)
    method returning something with a .content attribute) in tests instead of
    calling a real model - the dependency-injection point the brief asks for.
    Defaults to the env-configured LangChain chat model via the factory.
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
        SystemMessage(content=system_content),
        HumanMessage(content=question)
    ]

    model = chat_model or get_chat_model()
    try:
        ai_message = model.invoke(messages)
    except Exception as exc:                                # noqa: BLE001 - normalize whatever LangChain/the
        # underlying provider raises (network error, rate limit, timeout, bad
        # response) into our own exception type, so views.py has one thing to
        # catch instead of needing to know every possible provider exception.
        raise LLMProviderError(f"Chat model call failed: {exc}") from exc

    return {
        "answer": ai_message.content,
        "as_of": analysis.as_of.isoformat(),
        "warnings": [w.message for w in analysis.warnings],
        "not_computed": analysis.not_computed,
    }