# cas_parser/api/views.py
import logging
from django.db.models import Count, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.utils import timezone
from cas_parser.models import CASStatement, CASTransaction
from portfolio.services.api_services.value_history import get_portfolio_history, get_invested_series, _parse_period, \
    get_value_series
from core.pagination import paginate
from core.response import api_response   # reuse the same {st, msg, data} envelope everywhere
from portfolio.services.api_services.allocation import by_amc, by_asset_type
from portfolio.services.api_services.holdings import cost_basis, get_current_holdings, market_value, live_market_value
from portfolio.services.api_services.insights import top_and_needs_attention
from portfolio.services.api_services.returns_by_category import returns_by_category

logger = logging.getLogger(__name__)

class PortfolioSummaryAPIView(APIView):
    """
    GET /api/portfolio/summary/
    Powers the top-left value/invested/gain/holdings/expense-ratio cards.

    real_xirr, monthly_sip_total, active_sip_funds are returned as null - each needs
    the transaction_type / sign-convention confirmation noted in the response, not
    built blind to avoid shipping a wrong number on a fintech dashboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            holdings = get_current_holdings(request.user)
            total_value = total_cost = total_live_value = 0.0
            expense_weighted, expense_weight_base = 0.0, 0.0

            for h in holdings:
                value = float(market_value(h) or 0)
                live_value = float(live_market_value(h) or 0)  # fresh ISIN-resolved, today's NAV
                cost = float(cost_basis(h) or 0)
                total_value += value
                total_live_value += live_value
                total_cost += cost
                stat = getattr(h.scheme, "portfolio_stat", None) if h.scheme_id else None
                if stat and stat.expense_ratio is not None:
                    expense_weighted += value * float(stat.expense_ratio)
                    expense_weight_base += value
                print("--"*50)
                print("H",h)
                print("amfi_code","    ","isin")
                print(h.amfi_code,"    " ,h.isin)
                print("value", value)
                print("live_value", live_value)
                print("cost", cost)
                print("--" * 50)

            gain = total_value - total_cost
            gain_percent = (gain / total_cost * 100) if total_cost else None

            current_gain = total_live_value - total_cost  # NEW - based on live value
            current_gain_percent = (current_gain / total_cost * 100) if total_cost else None

            expense_ratio = (expense_weighted / expense_weight_base) if expense_weight_base else None

            now = timezone.now()
            data = {
                "portfolio_value": round(total_value, 2),  # kept - original meaning/calc
                "total_gain": round(gain, 2),  # kept - original meaning/calc
                "total_gain_percent": round(gain_percent, 2) if gain_percent is not None else None,
                # NEW: current holdings' live value - units held x TODAY's NAV, scheme
                # re-resolved fresh per ISIN rather than trusting each holding's stored
                # scheme_id (see live_market_value in holdings.py for why that matters).
                "current_portfolio_value": round(total_live_value, 2),
                "current_total_gain": round(current_gain, 2),
                "current_total_gain_percent": round(current_gain_percent,
                                                    2) if current_gain_percent is not None else None,
                "invested": round(total_cost, 2),
                "holdings_count": len(holdings),
                "expense_ratio": round(expense_ratio, 2) if expense_ratio is not None else None,
                "real_xirr": None,
                "monthly_sip_total": None,
                "active_sip_funds": None,
                # mutual funds publish one NAV per day (T-1, released the next morning),
                # so "as of now" reflects the latest AVAILABLE NAV, not a live intraday price.
                "as_of_date": now.date(),
                "as_of_time": now,
            }
        except Exception:  # noqa: BLE001
            logger.exception("portfolio summary failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building the portfolio summary")

        return api_response(200, "Data fetched successfully", data=data)


class AllocationAPIView(APIView):
    """
    GET /api/portfolio/allocation/
    Powers "Allocation" (by asset type, no Over/Under badge) and "By AMC".
    by_market_cap is null - see response notes on MutualFundPortfolioStat.market_cap_weightage.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            holdings = get_current_holdings(request.user)
            data = {
                "by_asset_type": by_asset_type(holdings),
                "by_amc": by_amc(holdings),
                "by_market_cap": None,
            }
        except Exception:  # noqa: BLE001
            logger.exception("allocation failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building allocation data")

        return api_response(200, "Data fetched successfully", data=data)


class ReturnsByCategoryAPIView(APIView):
    """GET /api/portfolio/returns-by-category/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            data = returns_by_category(get_current_holdings(request.user))
        except Exception:  # noqa: BLE001
            logger.exception("returns-by-category failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building returns by category")

        return api_response(200, "Data fetched successfully", data=data)


class InsightsAPIView(APIView):
    """GET /api/portfolio/insights/ - Top Performers / Needs Attention."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            data = top_and_needs_attention(get_current_holdings(request.user))
        except Exception  as e :  # noqa: BLE001
            logger.exception("insights failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building insights")

        return api_response(200, "Data fetched successfully", data=data)


class TransactionsAPIView(APIView):
    """
    POST /api/portfolio/transactions/
    body: {
        "month": 9, "year": 2026,                 # optional
        "from_date": "2026-09-01", "to_date": "...",  # optional, overrides month/year
        "scheme_id": 12,                           # optional - our resolved MutualFundsScheme id
        "transaction_type": "PURCHASE",            # optional - exact casparser type value
        "search": "Bandhan",                       # optional - matches the fund name
        "page_no": 1, "page_size": 20
    }
    Queries CASTransaction directly across ALL of the user's holdings - not just the
    latest snapshot - since a holding's transactions can be split across several
    historical CASSchemeHolding rows from different uploads (see holdings.py).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            qs = (CASTransaction.objects
                  .filter(holding__folio__statement__user=request.user)
                  .select_related("holding", "holding__scheme", "holding__folio"))

            from_date, to_date = request.data.get("from_date"), request.data.get("to_date")
            month, year = request.data.get("month"), request.data.get("year")
            if from_date:
                qs = qs.filter(transaction_date__gte=from_date)
            if to_date:
                qs = qs.filter(transaction_date__lte=to_date)
            elif month and year:
                qs = qs.filter(transaction_date__year=year, transaction_date__month=month)

            scheme_id = request.data.get("scheme_id")
            if scheme_id:
                qs = qs.filter(holding__scheme_id=scheme_id)

            txn_type = request.data.get("transaction_type")
            if txn_type:
                qs = qs.filter(transaction_type=txn_type)

            search = (request.data.get("search") or "").strip()
            if search:
                qs = qs.filter(holding__scheme_name__icontains=search)

            # Total for the filtered set as a whole, not just this page - matches the
            # "MONTHLY TOTAL" row in the UI, which sums the full month, not one page of it.
            total_amount = qs.aggregate(total=Sum("amount"))["total"]

            qs = qs.order_by("-transaction_date", "-id")
            rows, pagination = paginate(qs, request.data)
            results = [_serialize_transaction(t) for t in rows]
        except (ValueError, TypeError) as exc:  # bad date / page params
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("transactions list failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while fetching transactions")

        data = {"results": results, "total_amount": float(total_amount) if total_amount is not None else 0.0}
        return api_response(200, "Data fetched successfully", data=data, pagination=pagination)


def _serialize_transaction(t):
    scheme = t.holding.scheme
    return {
        "id": t.id,
        "fund_name": t.holding.scheme_name,
        "plan": scheme.plans if scheme else None,
        "option": scheme.option if scheme else None,
        "amc_name": t.holding.folio.amc_name,
        "date": t.transaction_date,
        "description": t.description,
        "transaction_type": t.transaction_type,
        "amount": float(t.amount) if t.amount is not None else None,
        "units": float(t.units) if t.units is not None else None,
        "nav": float(t.nav) if t.nav is not None else None,
        "balance": float(t.balance) if t.balance is not None else None,
    }



class PortfolioValueHistoryAPIView(APIView):
    """
    POST /api/portfolio/value-history/
    body: {"period": "1Y", "scheme_ids": [12, 15]}
      period: one of 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y, All (case-insensitive)
      scheme_ids: optional - our resolved MutualFundsScheme ids. Omit for all holdings;
                  pass one or more to scope both graphs to just those schemes.

    Returns both the VALUE graph (current worth over time, NAV-based) and the
    INVESTED graph (cumulative amount put in, no NAV) in one response, since they
    share the same underlying transaction fetch and plot dates - see
    services/value_history.py for exactly how each is computed, and the
    assumption about signed amount/units that's worth confirming.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        period = (request.data.get("period") or "1Y").strip()
        period_key = "All" if period.lower() == "all" else period.upper()
        scheme_isin = request.data.get("scheme_isin") or None

        try:
            value_series, invested_series, excluded = get_portfolio_history(
                request.user, period_key, scheme_isin)
            print("value_series:", value_series)
            print("invested_series:", invested_series)

        except ValueError as exc:  # unknown period code
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("value history failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building the portfolio value graph")

        data = {
            "period": period_key,
            "value_series": value_series,
            "invested_series": invested_series,
            # funds in scope with no resolved scheme match - present in invested_series
            # (no NAV needed) but missing from value_series (can't be priced). Empty
            # list means every selected fund was fully priced.
            "excluded_from_value_graph": excluded,
        }
        return api_response(200, "Data fetched successfully", data=data)


class PortfolioInvestedValueAPIView(APIView):
    """
    POST /api/portfolio/value-history/invested-value/
    body: {"period": "1Y", "scheme_ids": [12, 15]}
      same parameters as the current-value endpoint above.

    INVESTED AMOUNT over time - the running sum of transaction amount, no NAV
    involved, so unresolved holdings are included here even if they're missing
    from the current-value graph.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        period_key = _parse_period(request)
        scheme_ids = request.data.get("scheme_ids") or None

        try:
            invested_series = get_invested_series(request.user, period_key, scheme_ids)
        except ValueError as exc:
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("invested value history failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building the invested value graph")

        data = {"period": period_key, "invested_series": invested_series}
        return api_response(200, "Data fetched successfully", data=data)


class PortfolioCurrentValueAPIView(APIView):
    """
    POST /api/portfolio/value-history/current-value/
    body: {"period": "1Y", "scheme_ids": [12, 15]}
      period: one of 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y, All (case-insensitive)
      scheme_ids: optional - our resolved MutualFundsScheme ids. Omit for all holdings;
                  pass one or more to scope the graph to just those schemes.

    CURRENT VALUE over time - units held x NAV, both as of each response date. See
    services/value_history.py for exactly how this is computed, the historical-NAV
    lookback rule, and the ISIN re-resolution fix for the 0.0 bug.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        period_key = _parse_period(request)
        scheme_ids = request.data.get("scheme_ids") or None

        try:
            value_series, excluded = get_value_series(request.user, period_key, scheme_ids)
        except ValueError as exc:  # unknown period code
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("current value history failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while building the current value graph")

        data = {
            "period": period_key,
            "value_series": value_series,
            # funds in scope whose ISIN doesn't resolve to a scheme - no NAV to price
            # them with, so missing from value_series. Empty list = everything priced.
            "excluded_from_value_graph": excluded,
        }
        return api_response(200, "Data fetched successfully", data=data)
