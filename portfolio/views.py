# cas_parser/api/views.py
import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.utils import timezone
from cas_parser.models import CASStatement, CASTransaction, CASSchemeHolding
from cas_parser.services.get_invested_schems import get_invested_schemes
from portfolio.services.api_services.value_history import get_portfolio_history, get_invested_series, _parse_period, \
    get_value_series
from core.pagination import paginate
from core.response import api_response   # reuse the same {st, msg, data} envelope everywhere
from portfolio.services.api_services.allocation import by_amc, by_asset_type
from portfolio.services.api_services.holdings import cost_basis, get_current_holdings, market_value, live_market_value
from portfolio.services.api_services.insights import top_and_needs_attention
from portfolio.services.api_services.returns_by_category import returns_by_category

logger = logging.getLogger(__name__)
def _iter_user_transactions(user, **extra_filters):
    qs = (
        CASTransaction.objects
        .filter(holding__folio__statement__user=user, **extra_filters)
        .select_related("holding__folio")
        .order_by("transaction_date", "id")
    )
    seen = set()
    for tx in qs.iterator():
        key = (
            tx.transaction_hash or f"id:{tx.id}",
            tx.holding.folio.folio_number,
            tx.holding.folio.amc_name,
        )
        if key in seen:
            continue
        seen.add(key)
        yield tx


# ===========================================================================
# XIRR
# ===========================================================================
_IGNORE_KEYWORDS = (
    "stamp duty", "stamp", "gst", "reversal", "rejection",
    "reinvest", "dividend reinvest", "idcw reinvest",
)
_DIVIDEND_KEYWORDS = ("dividend", "idcw", "payout")


def _classify_cashflow(tx):
    """
    Signed cash flow from the investor's perspective:
        negative  → outflow  (money invested by user)
        positive  → inflow   (money returned to user)
         0.0      → ignore   (reinvestment / charges / reversals)

    Units sign is the primary classifier in CAS data — it's the most reliable
    signal because amounts are usually positive in the raw CAS for both
    purchases and redemptions.  Keyword fallbacks only handle dividend
    payouts (which carry units == 0 but are a genuine inflow).
    """
    text = f"{(tx.transaction_type or '').lower()} {(tx.description or '').lower()}"
    amount = float(tx.amount or 0)
    units = float(tx.units or 0)

    # Dividend reinvestment / IDCW reinvestment: user received units but no
    # cash left or entered their bank account → no net cash flow.
    # Stamp duty / GST / STT / reversals: fees or corrections → no cash flow.
    if any(k in text for k in _IGNORE_KEYWORDS):
        return 0.0

    # Pure dividend payout (or "Dividend" without "reinvest") → inflow.
    if any(k in text for k in _DIVIDEND_KEYWORDS):
        return abs(amount) if amount else 0.0

    if amount == 0:
        return 0.0

    # Units-driven classification (also correctly nets switch-out / switch-in
    # pairs to zero across the portfolio, since +X in one scheme cancels
    # -X in another).
    if units > 0:
        return -abs(amount)   # purchase / SIP → outflow
    if units < 0:
        return abs(amount)    # redemption → inflow

    # units == 0, non-dividend → charge / tax → ignore
    return 0.0


def _xnpv(rate, cashflows):
    if rate <= -1:
        return float("inf")
    d0 = cashflows[0][0]
    return sum(cf / (1.0 + rate) ** ((d - d0).days / 365.0) for d, cf in cashflows)


def _compute_xirr(cashflows):
    """Bisection solver. Returns annualized % (e.g. 12.5) or None."""
    if not cashflows:
        return None
    if not (any(cf < 0 for _, cf in cashflows) and any(cf > 0 for _, cf in cashflows)):
        return None  # XIRR undefined without both directions

    cashflows = sorted(cashflows, key=lambda x: x[0])

    low, high = -0.9999, 1.0
    f_low = _xnpv(low, cashflows)
    f_high = _xnpv(high, cashflows)

    if f_low * f_high > 0:
        for high_try in (10.0, 50.0, 100.0, 1000.0):
            f_high = _xnpv(high_try, cashflows)
            if f_low * f_high <= 0:
                high = high_try
                break
        else:
            return None  # no sign change → no meaningful IRR

    for _ in range(200):
        mid = (low + high) / 2
        f_mid = _xnpv(mid, cashflows)
        if abs(f_mid) < 1e-7:
            return round(mid * 100, 2)
        if f_low * f_mid < 0:
            high = mid
        else:
            low = mid
            f_low = f_mid

    return round(((low + high) / 2) * 100, 2)


def get_portfolio_xirr(user, current_value):
    """
    XIRR over the investor's full cash-flow history + today's portfolio
    value as the terminal inflow.

    `current_value` should be the live (ISIN-resolved) portfolio value.
    If the portfolio has been fully redeemed, pass 0 and the function will
    compute the realized return from flows alone.
    """
    cashflows = []
    for tx in _iter_user_transactions(user):
        cf = _classify_cashflow(tx)
        if cf != 0.0:
            cashflows.append((tx.transaction_date, cf))

    if current_value and current_value > 0:
        cashflows.append((timezone.now().date(), float(current_value)))

    return _compute_xirr(cashflows)


# ===========================================================================
# SIP detection
# ===========================================================================
def get_sip_summary(user):
    """
    Detect active SIPs from recurring purchase patterns.

    An "active SIP" per holding is defined as:
      • ≥ 2 purchase-like transactions in the last 120 days,
      • spanning ≥ 2 distinct year-months (proves a recurring pattern),
      • whose latest transaction is within 45 days (proves still active).

    Because CAS doesn't always tag transactions as "SIP" explicitly, the
    detection is pattern-based.  A lumpsum spread over a few months could
    theoretically be misread — but the 3-month lookback + distinct-month
    requirement is a reasonable balance.

    Returns (monthly_sip_total, active_sip_funds):
      • monthly_sip_total  — sum of average transaction amounts across
                             every active SIP holding.
      • active_sip_funds   — count of DISTINCT schemes (not holdings) with
                             an active SIP, so the same scheme held under
                             multiple folios is counted once.
    """
    today = timezone.now().date()
    lookback_start = today - timedelta(days=120)

    by_holding = defaultdict(list)
    for tx in _iter_user_transactions(
        user,
        transaction_date__gte=lookback_start,
        units__gt=0,
    ):
        # Exclude non-purchase rows that can carry positive units
        text = f"{(tx.transaction_type or '').lower()} {(tx.description or '').lower()}"
        if any(k in text for k in ("reinvest", "dividend", "idcw", "stamp", "reversal")):
            continue
        if not tx.amount or float(tx.amount) <= 0:
            continue
        by_holding[tx.holding_id].append(tx)

    active_holding_amounts = {}    # holding_id → avg monthly amount
    for holding_id, txs in by_holding.items():
        if len(txs) < 2:
            continue
        latest = max(t.transaction_date for t in txs)
        if (today - latest).days > 45:
            continue
        months = {(t.transaction_date.year, t.transaction_date.month) for t in txs}
        if len(months) < 2:
            continue
        amounts = [float(t.amount) for t in txs]
        active_holding_amounts[holding_id] = sum(amounts) / len(amounts)

    monthly_sip_total = round(sum(active_holding_amounts.values()), 2)

    if not active_holding_amounts:
        return monthly_sip_total, 0

    # Dedupe to distinct schemes for the count
    active_funds = set()
    for holding_id, scheme_id, isin in (
        CASSchemeHolding.objects
        .filter(id__in=active_holding_amounts.keys())
        .values_list("id", "scheme_id", "isin")
    ):
        if scheme_id:
            active_funds.add(("scheme", scheme_id))
        else:
            active_funds.add(("isin", isin or f"holding:{holding_id}"))

    return monthly_sip_total, len(active_funds)


# ===========================================================================
# API View
# ===========================================================================
class PortfolioSummaryAPIView(APIView):
    """
    GET /api/portfolio/summary/
    Powers the top-left value/invested/gain/holdings/expense-ratio cards.

    real_xirr
        Annualized XIRR (%) computed from every cash flow the investor has
        made (purchases = outflow, redemptions + dividend payouts = inflow,
        dividend reinvestment & stamp duty = ignored) plus today's live
        portfolio value as the terminal inflow.  Units sign is the primary
        classifier, not transaction_type text, so switch-ins/outs correctly
        net to zero across the portfolio.  Returns None when not computable
        (fewer than 2 flows, or no sign change).

    monthly_sip_total / active_sip_funds
        Detected from recurring purchase transactions — see get_sip_summary().
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            holdings = get_current_holdings(request.user)
            total_value = total_cost = total_live_value = 0.0
            expense_weighted, expense_weight_base = 0.0, 0.0

            for h in holdings:
                value = float(market_value(h) or 0)
                live_value = float(live_market_value(h) or 0)   # fresh ISIN-resolved, today's NAV
                cost = float(cost_basis(h) or 0)
                total_value += value
                total_live_value += live_value
                total_cost += cost
                stat = getattr(h.scheme, "portfolio_stat", None) if h.scheme_id else None
                if stat and stat.expense_ratio is not None:
                    expense_weighted += value * float(stat.expense_ratio)
                    expense_weight_base += value

            gain = total_value - total_cost
            gain_percent = (gain / total_cost * 100) if total_cost else None

            current_gain = total_live_value - total_cost
            current_gain_percent = (current_gain / total_cost * 100) if total_cost else None

            expense_ratio = (expense_weighted / expense_weight_base) if expense_weight_base else None

            # ---- NEW: XIRR against live value (fallback to stored value) ----
            terminal_value = total_live_value or total_value
            real_xirr = get_portfolio_xirr(request.user, terminal_value)

            # ---- NEW: SIP summary ------------------------------------------
            monthly_sip_total, active_sip_funds = get_sip_summary(request.user)
            print(f"Monthly SIP Total: {monthly_sip_total}, Active SIP Funds: {active_sip_funds}")
            now = timezone.now()
            data = {
                "portfolio_value": round(total_value, 2),
                "total_gain": round(gain, 2),
                "total_gain_percent": round(gain_percent, 2) if gain_percent is not None else None,
                "current_portfolio_value": round(total_live_value, 2),
                "current_total_gain": round(current_gain, 2),
                "current_total_gain_percent": round(current_gain_percent, 2) if current_gain_percent is not None else None,
                "invested": round(total_cost, 2),
                "holdings_count": len(holdings),
                "expense_ratio": round(expense_ratio, 2) if expense_ratio is not None else None,
                "real_xirr": real_xirr,
                "monthly_sip_total": monthly_sip_total,
                "active_sip_funds": active_sip_funds,
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


class PortfolioInvestedSchemesAPIView(APIView):
    """
    POST /api/portfolio/invested-schemes/

    Returns the unique list of mutual-fund schemes the authenticated user
    has invested in.  The same scheme held under multiple folios or multiple
    CAS statements appears only once.

    Each item: {scheme_id, scheme_name, isin, amfi_code}
    `scheme_id` is null when the holding is not yet resolved against
    MutualFundsScheme.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            invested_schemes = get_invested_schemes(request.user)
        except ValueError as exc:
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception(
                "invested schemes lookup failed for user_id=%s", request.user.id
            )
            return api_response(
                500, "Something went wrong while fetching invested schemes"
            )

        data = {"invested_schemes": invested_schemes}
        return api_response(200, "Data fetched successfully", data=data)