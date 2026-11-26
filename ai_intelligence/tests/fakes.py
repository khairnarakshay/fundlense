# ai_intelligence/tests/fakes.py
"""Shared test doubles. Nothing here touches the network or a real model."""
from datetime import datetime, timezone

from django.contrib.auth import get_user_model

from ai_intelligence.domain.schemas import ConcentrationMetrics, HoldingAnalysis, PortfolioAnalysisResult

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


class _Message:
    def __init__(self, content):
        self.content = content


class ScriptedChatModel:
    """
    Stands in for a LangChain chat model (duck-typed: .invoke / .with_structured_output).
    `answers`: replies in order; the LAST one repeats forever.
    `responder`: optional callable(messages) -> str, takes priority (lets a test answer the
    summarizer differently from the chat itself).
    `structured`: object (or callable(messages)) returned by .with_structured_output(...).invoke().
    Every call is recorded for assertions.
    """

    def __init__(self, answers=("OK",), responder=None, structured=None):
        self._answers = list(answers)
        self.responder = responder
        self.structured = structured
        self.fail_with = None
        self.structured_fail_with = None
        self.calls: list = []
        self.structured_calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.fail_with:
            raise self.fail_with
        if self.responder:
            return _Message(self.responder(messages))
        answer = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        return _Message(answer)

    def with_structured_output(self, schema):
        parent = self

        class _Runner:
            def invoke(self, messages):
                parent.structured_calls.append(messages)
                if parent.structured_fail_with:
                    raise parent.structured_fail_with
                return parent.structured(messages) if callable(parent.structured) else parent.structured

        return _Runner()


def make_user(username: str):
    return get_user_model().objects.create_user(username=username, password="pw-for-tests")


def make_analysis(total_value=11000.0, holdings_count=2) -> PortfolioAnalysisResult:
    holdings = [HoldingAnalysis(scheme_name="Fund A", isin="INF000000001", amc_name="AMC X", category="Large Cap",
                                market_value=6000.0, weight_percent=60.0, cost_basis=5000.0, gain=1000.0,
                                gain_percent=20.0, is_scheme_resolved=True)] if holdings_count else []
    return PortfolioAnalysisResult(
        as_of=NOW, total_value=total_value, total_cost=10000.0, total_gain=total_value - 10000.0,
        total_gain_percent=10.0, holdings_count=holdings_count, expense_ratio_weighted=None,
        allocation_by_asset_type=[], allocation_by_amc=[], concentration=ConcentrationMetrics(),
        portfolio_weighted_volatility_1y=None, warnings=[], not_computed=["xirr"], holdings=holdings)