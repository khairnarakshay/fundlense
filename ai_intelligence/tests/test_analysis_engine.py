# ai_intelligence/tests/test_analysis_engine.py
"""
Tests for the deterministic analysis engine - pure functions, hand-built
PortfolioSnapshot fixtures, no database and no LLM involved at all.
"""
from datetime import date, datetime, timedelta, timezone

from django.test import SimpleTestCase

from ai_intelligence.domain.schemas import HoldingSnapshot, PortfolioSnapshot
from ai_intelligence.portfolio.analysis_engine import analyze_portfolio

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def _holding(**overrides) -> HoldingSnapshot:
    defaults = dict(
        isin="INF000A00000", scheme_name="Test Fund", amc_name="Test AMC",
        category="Equity", units=100.0, market_value=10000.0, cost_basis=9000.0,
        is_scheme_resolved=True, nav_date=date(2026, 10, 21),
        expense_ratio=1.0, ret_1y=12.0, cagr_3y=15.0, volatility_1y=18.0,
    )
    defaults.update(overrides)
    return HoldingSnapshot(**defaults)


def _snapshot(holdings: list[HoldingSnapshot]) -> PortfolioSnapshot:
    total_value = sum(h.market_value for h in holdings)
    total_cost = sum(h.cost_basis or 0 for h in holdings)
    unresolved = sum(1 for h in holdings if not h.is_scheme_resolved)
    return PortfolioSnapshot(
        as_of=NOW, holdings=holdings, total_value=total_value, total_cost=total_cost,
        holdings_count=len(holdings), unresolved_holdings_count=unresolved,
    )


class EmptyPortfolioTests(SimpleTestCase):
    def test_empty_portfolio_returns_zeroed_result_with_warning(self):
        result = analyze_portfolio(_snapshot([]))
        self.assertEqual(result.holdings_count, 0)
        self.assertEqual(result.total_value, 0.0)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0].code, "no_holdings")
        self.assertIn("xirr", result.not_computed)


class BasicMetricsTests(SimpleTestCase):
    def test_single_holding_gain_and_percent(self):
        result = analyze_portfolio(_snapshot([_holding(market_value=11000.0, cost_basis=10000.0)]))
        self.assertEqual(result.total_value, 11000.0)
        self.assertEqual(result.total_cost, 10000.0)
        self.assertEqual(result.total_gain, 1000.0)
        self.assertEqual(result.total_gain_percent, 10.0)

    def test_zero_cost_gives_none_gain_percent_not_division_error(self):
        result = analyze_portfolio(_snapshot([_holding(market_value=5000.0, cost_basis=0.0)]))
        self.assertIsNone(result.total_gain_percent)

    def test_expense_ratio_is_value_weighted(self):
        holdings = [
            _holding(scheme_name="A", market_value=8000.0, cost_basis=8000.0, expense_ratio=1.0),
            _holding(scheme_name="B", market_value=2000.0, cost_basis=2000.0, expense_ratio=2.0),
        ]
        result = analyze_portfolio(_snapshot(holdings))
        # (8000*1.0 + 2000*2.0) / 10000 = 1.2
        self.assertEqual(result.expense_ratio_weighted, 1.2)


class UnresolvedHoldingTests(SimpleTestCase):
    def test_unresolved_holding_excluded_from_value_but_cost_still_counted(self):
        holdings = [
            _holding(scheme_name="Resolved", market_value=10000.0, cost_basis=9000.0),
            _holding(scheme_name="Unresolved", is_scheme_resolved=True, market_value=0.0, cost_basis=5000.0),
        ]
        # deliberately mark the second one unresolved AFTER construction-style fix:
        holdings[1] = _holding(scheme_name="Unresolved", is_scheme_resolved=False,
                               market_value=0.0, cost_basis=5000.0)
        snapshot = _snapshot(holdings)
        result = analyze_portfolio(snapshot)

        self.assertEqual(result.total_value, 10000.0)                # unresolved contributes no value
        self.assertEqual(result.total_cost, 9000.0 + 5000.0)         # but its cost IS counted
        warning_codes = {w.code for w in result.warnings}
        self.assertIn("unresolved_schemes", warning_codes)


class StaleNavTests(SimpleTestCase):
    def test_stale_nav_flagged(self):
        holding = _holding(nav_date=date(2026, 10, 1))   # 21 days before NOW -> stale
        result = analyze_portfolio(_snapshot([holding]))
        warning_codes = {w.code for w in result.warnings}
        self.assertIn("stale_nav", warning_codes)

    def test_fresh_nav_not_flagged(self):
        holding = _holding(nav_date=date(2026, 10, 20))   # 2 days before NOW -> fresh
        result = analyze_portfolio(_snapshot([holding]))
        warning_codes = {w.code for w in result.warnings}
        self.assertNotIn("stale_nav", warning_codes)


class AllocationAndConcentrationTests(SimpleTestCase):
    def test_allocation_by_asset_type_and_amc(self):
        holdings = [
            _holding(scheme_name="A", amc_name="AMC1", category="Equity", market_value=6000.0, cost_basis=6000.0),
            _holding(scheme_name="B", amc_name="AMC2", category="Debt", market_value=4000.0, cost_basis=4000.0),
        ]
        result = analyze_portfolio(_snapshot(holdings))
        by_category = {a.label: a.percent for a in result.allocation_by_asset_type}
        self.assertEqual(by_category["Equity"], 60.0)
        self.assertEqual(by_category["Debt"], 40.0)

        by_amc = {a.label: a.percent for a in result.allocation_by_amc}
        self.assertEqual(by_amc["AMC1"], 60.0)
        self.assertEqual(by_amc["AMC2"], 40.0)

    def test_concentration_single_holding_is_maximal(self):
        result = analyze_portfolio(_snapshot([_holding(market_value=10000.0, cost_basis=10000.0)]))
        self.assertEqual(result.concentration.top_holding_percent, 100.0)
        # HHI for a single 100% holding = 100^2 = 10000, the maximum possible value
        self.assertEqual(result.concentration.herfindahl_index, 10000.0)
        self.assertEqual(result.concentration.herfindahl_label, "high concentration")

    def test_concentration_even_split_is_low_hhi(self):
        holdings = [_holding(scheme_name=f"Fund{i}", amc_name=f"AMC{i}",
                             market_value=2500.0, cost_basis=2500.0) for i in range(4)]
        result = analyze_portfolio(_snapshot(holdings))
        # four equal 25% holdings -> HHI = 4 * 25^2 = 2500
        self.assertEqual(result.concentration.herfindahl_index, 2500.0)


class VolatilityTests(SimpleTestCase):
    def test_volatility_weighted_and_labeled_as_proxy(self):
        holdings = [
            _holding(scheme_name="A", market_value=8000.0, cost_basis=8000.0, volatility_1y=10.0),
            _holding(scheme_name="B", market_value=2000.0, cost_basis=2000.0, volatility_1y=20.0),
        ]
        result = analyze_portfolio(_snapshot(holdings))
        # (8000*10 + 2000*20) / 10000 = 12.0
        self.assertEqual(result.portfolio_weighted_volatility_1y, 12.0)
        warning_codes = {w.code for w in result.warnings}
        self.assertIn("volatility_is_weighted_average", warning_codes)

    def test_no_volatility_data_gives_none_not_zero(self):
        result = analyze_portfolio(_snapshot([_holding(volatility_1y=None)]))
        self.assertIsNone(result.portfolio_weighted_volatility_1y)
        warning_codes = {w.code for w in result.warnings}
        self.assertNotIn("volatility_is_weighted_average", warning_codes)


class NotComputedListTests(SimpleTestCase):
    def test_not_computed_list_present_even_for_full_portfolio(self):
        result = analyze_portfolio(_snapshot([_holding()]))
        self.assertEqual(set(result.not_computed), {"xirr", "sip_summary", "portfolio_overlap"})