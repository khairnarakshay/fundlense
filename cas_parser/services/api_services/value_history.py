# portfolio/services/value_history.py
"""
Portfolio "Value over time" and "Invested over time" graphs.

Both graphs share the same set of plot dates: every distinct date a selected
transaction occurred within the chosen period, plus the period's own start date
(so the chart opens at a real value even if nothing was transacted exactly then)
and today (always the final point, priced at today's NAV).

VALUE series: at each plot date, cumulative units held per scheme (built from the
FULL transaction history, not just the window - so holdings bought before the
window still count) x that scheme's NAV as of that date, summed across schemes.
Only resolved schemes (scheme_id set) can appear here - there's no historical NAV
for a holding we couldn't match to our own scheme master data.

INVESTED series: at each plot date, the running sum of transaction `amount`, signed,
up to and including that date. No NAV involved, so unresolved holdings ARE included.

ASSUMPTION, please confirm: both `units` and `amount` on CASTransaction come signed
from casparser already (negative for redemption/switch-out, positive for purchase/
SIP/switch-in - this matched the sample data you shared earlier). Every transaction
is summed as-is here, stamp duty/STT/TDS rows included, exactly as described
("take the transactions... sum up them") - nothing is excluded by transaction_type.
If you want charges/tax rows left out of the INVESTED line specifically, say so and
I'll add that filter - it's a one-line change in _build_invested_series below.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from cas_parser.models import CASTransaction
from mutual_fund.models import MutualFundNAV

NAV_WINDOW_DAYS = 7      # same lookback tolerance used by the mutual_fund return-stat calculations

PERIOD_DELTAS = {
    "1W": relativedelta(weeks=1), "1M": relativedelta(months=1), "3M": relativedelta(months=3),
    "6M": relativedelta(months=6), "1Y": relativedelta(years=1), "3Y": relativedelta(years=3),
    "5Y": relativedelta(years=5),
}


def _get_scope_transactions(user, scheme_ids=None):
    qs = (CASTransaction.objects
         .filter(holding__folio__statement__user=user)
         .select_related("holding", "holding__scheme")
         .order_by("transaction_date", "id"))
    if scheme_ids:
        qs = qs.filter(holding__scheme_id__in=scheme_ids)
    return list(qs)


def _period_start(period, transactions, today):
    if period == "All":
        return transactions[0].transaction_date if transactions else today
    delta = PERIOD_DELTAS.get(period)
    if delta is None:
        raise ValueError(f"Unknown period: {period!r} - expected one of "
                         f"{sorted(PERIOD_DELTAS)} or 'All'")
    return today - delta


def _plot_dates(transactions, start, today):
    in_window = {t.transaction_date for t in transactions if start <= t.transaction_date <= today}
    return sorted({start, *in_window, today})


def _build_unit_timelines(transactions):
    """scheme_id -> (dates[], cumulative_units[]), ascending - resolved schemes only."""
    per_scheme = defaultdict(list)
    for t in transactions:
        scheme_id = t.holding.scheme_id
        if not scheme_id or t.units is None:
            continue
        per_scheme[scheme_id].append((t.transaction_date, float(t.units)))

    timelines = {}
    for scheme_id, rows in per_scheme.items():
        rows.sort(key=lambda r: r[0])
        dates, cum_units, running = [], [], 0.0
        for d, units in rows:
            running += units
            dates.append(d)
            cum_units.append(running)
        timelines[scheme_id] = (dates, cum_units)
    return timelines


def _units_as_of(dates, cum_units, as_of):
    i = bisect_right(dates, as_of) - 1
    return cum_units[i] if i >= 0 else 0.0


def _nav_as_of(scheme_id, as_of, nav_cache):
    """nav_cache: scheme_id -> (dates[], navs[]) - fetched ONCE per scheme (full
    history, no date filter), then bisected locally for every plot date. Fetching
    with an as_of-bound filter and caching that would be wrong: a later, larger
    as_of in the same series would silently miss NAV rows the first call excluded."""
    if scheme_id not in nav_cache:
        rows = list(MutualFundNAV.objects
                   .filter(scheme_id=scheme_id, is_carry_forward=False)
                   .order_by("nav_date").values_list("nav_date", "nav"))
        nav_cache[scheme_id] = ([r[0] for r in rows], [float(r[1]) for r in rows])
    dates, navs = nav_cache[scheme_id]
    i = bisect_right(dates, as_of) - 1
    if i < 0 or (as_of - dates[i]).days > NAV_WINDOW_DAYS:
        return None
    return navs[i]


def get_portfolio_history(user, period, scheme_ids=None):
    """
    Returns (value_series, invested_series, excluded_fund_names):
      value_series    = [{"date": date, "value": float}, ...]
      invested_series = [{"date": date, "invested": float}, ...]
      excluded_fund_names = scheme names in scope that have no resolved
                            MutualFundsScheme match, so they're missing from
                            value_series (but ARE included in invested_series).
    """
    today = date.today()
    transactions = _get_scope_transactions(user, scheme_ids)
    start = _period_start(period, transactions, today)
    points = _plot_dates(transactions, start, today)

    timelines = _build_unit_timelines(transactions)
    nav_cache = {}
    value_series = []
    for d in points:
        total = 0.0
        for scheme_id, (dates, cum_units) in timelines.items():
            units = _units_as_of(dates, cum_units, d)
            if units <= 0:
                continue
            nav = _nav_as_of(scheme_id, d, nav_cache)
            if nav is not None:
                total += units * nav
        value_series.append({"date": d, "value": round(total, 2)})

    amount_dates, cum_amounts, running = [], [], 0.0
    for t in transactions:
        if t.amount is not None:
            running += float(t.amount)
        amount_dates.append(t.transaction_date)
        cum_amounts.append(running)

    invested_series = []
    for d in points:
        i = bisect_right(amount_dates, d) - 1
        invested_series.append({"date": d, "invested": round(cum_amounts[i], 2) if i >= 0 else 0.0})

    excluded_fund_names = sorted({t.holding.scheme_name for t in transactions if not t.holding.scheme_id})
    return value_series, invested_series, excluded_fund_names



