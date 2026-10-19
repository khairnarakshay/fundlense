# portfolio/services/value_history.py
"""
Two separate graphs, both built here - all their shared helpers live in this one
file on purpose (not split across several small service files):

  get_value_series(user, period, scheme_ids)
      CURRENT VALUE over time: at each response date, units held (as of that date)
      x that scheme's NAV (as of that date), summed across schemes.

  get_invested_series(user, period, scheme_ids)
      INVESTED AMOUNT over time: at each response date, the running sum of
      transaction `amount` up to and including that date. No NAV involved.

Both walk the same rule for which dates appear: every date a selected transaction
occurred within the chosen period, PLUS the period's start date, PLUS today - never
skipped, so a purchase on the 14th or a redemption on the 20th always shows up as
its own point.

Historical NAV lookup has no cutoff: if a scheme has no NAV row for a given date
(holiday/weekend), we walk back to the most recent earlier NAV row and use that,
however far back it is - never a window cap, never skipped.

FIX (this version): get_value_series was returning 0.0 for every point. Cause: unit
timelines were built from `holding.scheme_id` - the scheme FK stored on each
CASSchemeHolding row AT INGESTION TIME. A transaction attached to an OLDER holding
(from an upload processed before a scheme existed in your mutual_fund master data)
keeps an unresolved `scheme_id` forever, even after that scheme is imported later -
ingestion resolves a holding's scheme ONCE, on upload, and never retries it. Since
most of a user's transaction history sits on these older, possibly-stale holding
rows (see cas-statement-parser notes on cross-upload dedup), almost every unit
ended up excluded, netting 0.0. Fixed by re-resolving each distinct ISIN to a
scheme fresh, at request time, instead of trusting the stored FK.

ASSUMPTION, please confirm: both `units` and `amount` on CASTransaction come signed
from casparser already (negative for redemption/switch-out, positive for purchase/
SIP/switch-in - matched the sample data you shared earlier), so both series sum
them as-is, charges/tax rows included.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from cas_parser.models import CASTransaction
from cas_parser.services.scheme_resolver import resolve_scheme
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


def _resolve_isin_to_scheme_id(transactions):
    """Fresh, request-time resolution per distinct ISIN in this transaction set -
    deliberately ignores each row's stored holding.scheme_id. See the FIX note in
    the module docstring for why that stored value can be stale."""
    isin_amfi = {}
    for t in transactions:
        isin = t.holding.isin
        if isin and isin not in isin_amfi:
            isin_amfi[isin] = t.holding.amfi_code

    isin_to_scheme_id = {}
    for isin, amfi_code in isin_amfi.items():
        scheme = resolve_scheme(isin, amfi_code)
        if scheme:
            isin_to_scheme_id[isin] = scheme.id
    return isin_to_scheme_id


def _build_unit_timelines(transactions):
    """isin -> (dates[], cumulative_units[]), ascending. Keyed by ISIN, not by
    holding.scheme_id - see the FIX note above."""
    per_isin = defaultdict(list)
    for t in transactions:
        isin = t.holding.isin
        if not isin or t.units is None:
            continue
        per_isin[isin].append((t.transaction_date, float(t.units)))

    timelines = {}
    for isin, rows in per_isin.items():
        rows.sort(key=lambda r: r[0])
        dates, cum_units, running = [], [], 0.0
        for d, units in rows:
            running += units
            dates.append(d)
            cum_units.append(running)
        timelines[isin] = (dates, cum_units)
    return timelines


def _units_as_of(dates, cum_units, as_of):
    i = bisect_right(dates, as_of) - 1
    return cum_units[i] if i >= 0 else 0.0


def _nav_as_of(scheme_id, as_of, nav_cache):
    """nav_cache: scheme_id -> (dates[], navs[]) - each scheme's FULL NAV history is
    fetched once and reused for every plot date. No cap on how far back we look: if
    there's no NAV row for `as_of` exactly, we take the latest row before it,
    however far back that is. None only when there's no NAV row on or before
    `as_of` at all (the scheme didn't exist yet)."""
    if scheme_id not in nav_cache:
        rows = list(MutualFundNAV.objects
                   .filter(scheme__isin_code=scheme_id, is_carry_forward=False)
                   .order_by("nav_date").values_list("nav_date", "nav"))
        nav_cache[scheme_id] = ([r[0] for r in rows], [float(r[1]) for r in rows])
    dates, navs = nav_cache[scheme_id]
    i = bisect_right(dates, as_of) - 1
    return navs[i] if i >= 0 else None


def get_value_series(user, period, scheme_ids=None):
    """Returns (series, excluded_fund_names).
    series = [{"date": date, "value": float}, ...]
    excluded_fund_names = scheme names in scope whose ISIN doesn't resolve to any
    MutualFundsScheme - no NAV to price them with, so they're missing from series."""
    today = date.today()
    transactions = _get_scope_transactions(user, scheme_ids)
    start = _period_start(period, transactions, today)
    points = _plot_dates(transactions, start, today)

    timelines = _build_unit_timelines(transactions)
    isin_to_scheme_id = _resolve_isin_to_scheme_id(transactions)
    nav_cache = {}

    series = []
    for d in points:
        total = 0.0
        for isin, (dates, cum_units) in timelines.items():
            units = _units_as_of(dates, cum_units, d)
            if units <= 0:
                continue
            scheme_id = isin_to_scheme_id.get(isin)
            if not scheme_id:
                continue
            nav = _nav_as_of(scheme_id, d, nav_cache)
            if nav is not None:
                total += units * nav
        series.append({"date": d, "value": round(total, 2)})

    excluded_fund_names = sorted({
        t.holding.scheme_name for t in transactions
        if t.holding.isin not in isin_to_scheme_id
    })
    return series, excluded_fund_names


def get_invested_series(user, period, scheme_ids=None):
    """Returns [{"date": date, "invested": float}, ...] - cumulative signed amount,
    no NAV, every transaction included (unresolved holdings too, since this needs
    no scheme match at all - unaffected by the staleness bug above)."""
    today = date.today()
    transactions = _get_scope_transactions(user, scheme_ids)
    start = _period_start(period, transactions, today)
    points = _plot_dates(transactions, start, today)

    amount_dates, cum_amounts, running = [], [], 0.0
    for t in transactions:
        if t.amount is not None:
            running += float(t.amount)
        amount_dates.append(t.transaction_date)
        cum_amounts.append(running)

    series = []
    for d in points:
        i = bisect_right(amount_dates, d) - 1
        series.append({"date": d, "invested": round(cum_amounts[i], 2) if i >= 0 else 0.0})
    return series



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

def _parse_period(request):
    period = (request.data.get("period") or "1Y").strip()
    return "All" if period.lower() == "all" else period.upper()

