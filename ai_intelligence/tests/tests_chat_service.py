# ai_intelligence/tests/test_chat_service.py
"""
Tests for Phase 4's chat service. Uses a FakeLLMProvider stub (no real network
call) injected via ask_portfolio_question's provider= parameter, and patches
build_portfolio_snapshot/analyze_portfolio so this stays fully DB-free - the
analysis engine itself is already covered separately in test_analysis_engine.py.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from ai_intelligence.application.chat_service import ChatInputError, ask_portfolio_question
from ai_intelligence.domain.schemas import (
    ConcentrationMetrics, DataCompletenessWarning, GenerationResult,
    PortfolioAnalysisResult, ProviderHealth,
)
from ai_intelligence.llm.interfaces import LLMProvider

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


class FakeLLMProvider(LLMProvider):
    """Records the messages it was called with, so tests can inspect exactly
    what grounding context reached the 'model'."""

    def __init__(self, response_text="This is a fake answer."):
        super().__init__(model_id="fake-model")
        self.response_text = response_text
        self.last_messages = None

    @property
    def provider_name(self):
        return "fake"

    def generate(self, messages, params=None):
        self.last_messages = messages
        return GenerationResult(content=self.response_text, provider="fake", model_id="fake-model")

    def health_check(self):
        return ProviderHealth(healthy=True, provider="fake", model_id="fake-model", checked_at=NOW)


def _full_analysis() -> PortfolioAnalysisResult:
    return PortfolioAnalysisResult(
        as_of=NOW, total_value=11000.0, total_cost=10000.0, total_gain=1000.0,
        total_gain_percent=10.0, holdings_count=2, expense_ratio_weighted=1.1,
        allocation_by_asset_type=[], allocation_by_amc=[],
        concentration=ConcentrationMetrics(top_holding_name="Fund A", top_holding_percent=60.0,
                                           top_amc_name="AMC X", top_amc_percent=60.0,
                                           herfindahl_index=5000.0, herfindahl_label="high concentration"),
        portfolio_weighted_volatility_1y=14.0,
        warnings=[], not_computed=["xirr", "sip_summary", "portfolio_overlap"],
    )


def _empty_analysis() -> PortfolioAnalysisResult:
    return PortfolioAnalysisResult(
        as_of=NOW, total_value=0.0, total_cost=0.0, total_gain=0.0, total_gain_percent=None,
        holdings_count=0, expense_ratio_weighted=None, allocation_by_asset_type=[],
        allocation_by_amc=[], concentration=ConcentrationMetrics(),
        portfolio_weighted_volatility_1y=None,
        warnings=[DataCompletenessWarning(code="no_holdings", message="No current holdings found for this user.")],
        not_computed=["xirr", "sip_summary", "portfolio_overlap"],
    )


class ChatInputValidationTests(SimpleTestCase):
    def test_empty_question_raises(self):
        with self.assertRaises(ChatInputError):
            ask_portfolio_question(user=object(), question="", provider=FakeLLMProvider())

    def test_whitespace_only_question_raises(self):
        with self.assertRaises(ChatInputError):
            ask_portfolio_question(user=object(), question="   ", provider=FakeLLMProvider())

    def test_too_long_question_raises(self):
        with self.assertRaises(ChatInputError):
            ask_portfolio_question(user=object(), question="x" * 3000, provider=FakeLLMProvider())


class ChatGroundingTests(SimpleTestCase):
    @patch("ai_intelligence.application.chat_service.analyze_portfolio")
    @patch("ai_intelligence.application.chat_service.build_portfolio_snapshot")
    def test_grounding_context_includes_verified_numbers(self, mock_snapshot, mock_analyze):
        mock_snapshot.return_value = object()
        mock_analyze.return_value = _full_analysis()
        fake = FakeLLMProvider()

        ask_portfolio_question(user=object(), question="What is my portfolio worth?", provider=fake)

        system_message = fake.last_messages[0].content
        self.assertIn("11000.0", system_message)       # total_value, verbatim
        self.assertIn("Fund A", system_message)          # top holding, verbatim
        self.assertIn("xirr", system_message)             # not_computed surfaced, so the model knows not to guess

    @patch("ai_intelligence.application.chat_service.analyze_portfolio")
    @patch("ai_intelligence.application.chat_service.build_portfolio_snapshot")
    def test_empty_portfolio_grounds_without_crashing(self, mock_snapshot, mock_analyze):
        mock_snapshot.return_value = object()
        mock_analyze.return_value = _empty_analysis()
        fake = FakeLLMProvider()

        result = ask_portfolio_question(user=object(), question="How is my portfolio doing?", provider=fake)

        self.assertIn("no holdings", fake.last_messages[0].content.lower())
        self.assertEqual(result["answer"], fake.response_text)

    @patch("ai_intelligence.application.chat_service.analyze_portfolio")
    @patch("ai_intelligence.application.chat_service.build_portfolio_snapshot")
    def test_response_shape(self, mock_snapshot, mock_analyze):
        mock_snapshot.return_value = object()
        mock_analyze.return_value = _full_analysis()
        fake = FakeLLMProvider(response_text="Your portfolio is worth 11000.")

        result = ask_portfolio_question(user=object(), question="value?", provider=fake)

        self.assertEqual(result["answer"], "Your portfolio is worth 11000.")
        self.assertEqual(result["provider"], "fake")
        self.assertEqual(result["model_id"], "fake-model")
        self.assertIn("xirr", result["not_computed"])
        self.assertEqual(result["as_of"], NOW.isoformat())