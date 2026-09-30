# mutual_fund/api/serializers.py
from rest_framework import serializers

from mutual_fund.models import MutualFundReturnStat, MutualFundsScheme


class ReturnStatSerializer(serializers.ModelSerializer):
    """All computed screening numbers for one scheme. Nested under SchemeListSerializer.returns."""

    class Meta:
        model = MutualFundReturnStat
        fields = [
            "as_of_date", "latest_nav", "first_nav_date",
            "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_ytd", "ret_1y", "ret_3y", "ret_5y",
            "cagr_3y", "cagr_5y", "cagr_10y", "cagr_since_inception",
            "volatility_1y", "volatility_3y", "max_drawdown_1y", "max_drawdown_3y",
            "sharpe_3y", "sortino_3y",
            "high_52w", "high_52w_date", "low_52w", "low_52w_date", "calendar_returns",
            "pct_1y", "pct_3y", "pct_5y",
        ]


class SchemeListSerializer(serializers.ModelSerializer):
    """
    One row for the screener grid: the requested MutualFundsScheme fields plus the
    full MutualFundReturnStat block nested under "returns".

    Requires the view's queryset to `.select_related("fund_master", "fund_master__fund_house",
    "fund_master__category", "return_stat")` - otherwise every row triggers 3 extra queries.
    """
    fund_house = serializers.CharField(source="fund_master.fund_house.name", default=None, read_only=True)
    category = serializers.CharField(source="fund_master.category.name", default=None, read_only=True)
    returns = serializers.SerializerMethodField()

    class Meta:
        model = MutualFundsScheme
        fields = [
            "id", "fund_master", "fund_house", "category", "scheme_name",
            "fund_type", "option", "plans", "amfi_code",
            "stated_benchmark", "investment_objective", "fund_manager",
            "risk_level", "ranking", "rank", "launch_date",
            "current_nav", "current_nav_date", "nav_closed",
            "min_investment", "max_purchase_amount",
            "has_exit_load", "exit_load_value", "has_lock_in", "lock_in_period_days",
            "returns",
        ]

    def get_returns(self, obj):
        # getattr(..., None) instead of obj.return_stat directly: a scheme with no NAV
        # history yet (fresh NFO) has no MutualFundReturnStat row, and the reverse
        # OneToOne accessor raises DoesNotExist rather than returning None on its own.
        stat = getattr(obj, "return_stat", None)
        return ReturnStatSerializer(stat).data if stat else None