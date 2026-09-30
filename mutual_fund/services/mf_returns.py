# mutual_fund/services/mf_returns.py
import logging
from bisect import bisect_right
from datetime import date, timedelta
from math import sqrt

import numpy as np
from dateutil.relativedelta import relativedelta
from django.db import connection

from mutual_fund.models import MutualFundNAV, MutualFundReturnStat
from mutual_fund.services.nav_utils import WINDOW_DAYS, eligible_scheme_qs

logger = logging.getLogger(__name__)

RISK_FREE = 0.065
TRADING_DAYS = 252

PERIODS = {
    "1w": relativedelta(days=7), "1m": relativedelta(months=1), "3m": relativedelta(months=3),
    "6m": relativedelta(months=6), "1y": relativedelta(years=1), "3y": relativedelta(years=3),
    "5y": relativedelta(years=5), "10y": relativedelta(years=10),
}


def nav_on_or_before(dates, navs, target, window=WINDOW_DAYS):
    i = bisect_right(dates, target) - 1
    if i < 0 or (target - dates[i]).days > window:
        return None
    return dates[i], navs[i]


def _pct(end, start):
    return (end / start - 1) * 100


def _cagr(end, start, days):
    return ((end / start) ** (365.0 / days) - 1) * 100 if days > 0 else None


def _max_drawdown(arr):
    peak = np.maximum.accumulate(arr)
    return float(((arr / peak) - 1).min() * 100)


def compute_stats(dates, navs):
    """dates ascending list[date]; navs list[float] (all > 0). Returns dict of MutualFundReturnStat fields."""
    if not dates:
        return None
    end_date, end_nav = dates[-1], navs[-1]
    out = {"as_of_date": end_date, "latest_nav": end_nav, "first_nav_date": dates[0]}

    for key, delta in PERIODS.items():
        hit = nav_on_or_before(dates, navs, end_date - delta)
        if not hit:
            continue
        s_date, s_nav = hit
        days = (end_date - s_date).days
        if key in ("1w", "1m", "3m", "6m", "1y", "3y", "5y"):
            out[f"ret_{key}"] = _pct(end_nav, s_nav)
        if key in ("3y", "5y", "10y"):
            out[f"cagr_{key}"] = _cagr(end_nav, s_nav, days)

    hit = nav_on_or_before(dates, navs, date(end_date.year - 1, 12, 31))
    if hit:
        out["ret_ytd"] = _pct(end_nav, hit[1])

    span = (end_date - dates[0]).days
    if span >= 365:
        out["cagr_since_inception"] = _cagr(end_nav, navs[0], span)

    cal = {}
    for y in range(dates[0].year, end_date.year + 1):
        e = nav_on_or_before(dates, navs, date(y, 12, 31)) if y < end_date.year else (end_date, end_nav)
        s = nav_on_or_before(dates, navs, date(y - 1, 12, 31))
        if e and s:
            cal[str(y)] = round(_pct(e[1], s[1]), 2)
    out["calendar_returns"] = cal or None

    def window_arr(years):
        start = end_date - relativedelta(years=years)
        i = bisect_right(dates, start)
        if i >= len(dates) - 20 or dates[0] > start + timedelta(days=WINDOW_DAYS):
            return None
        return np.array(navs[i:], dtype=float)

    for yrs in (1, 3):
        arr = window_arr(yrs)
        if arr is None:
            continue
        rets = np.diff(np.log(arr))
        out[f"volatility_{yrs}y"] = float(rets.std(ddof=1) * sqrt(TRADING_DAYS) * 100)
        out[f"max_drawdown_{yrs}y"] = _max_drawdown(arr)
        if yrs == 3:
            rf_daily = RISK_FREE / TRADING_DAYS
            excess = rets - rf_daily
            sd = rets.std(ddof=1)
            downside = rets[rets < rf_daily] - rf_daily
            if sd > 0:
                out["sharpe_3y"] = float(excess.mean() / sd * sqrt(TRADING_DAYS))
            if len(downside) > 1 and (downside ** 2).mean() > 0:
                out["sortino_3y"] = float(excess.mean() / np.sqrt((downside ** 2).mean()) * sqrt(TRADING_DAYS))

    i = bisect_right(dates, end_date - timedelta(days=365))
    w_dates, w_navs = dates[i:], navs[i:]
    if w_navs:
        hi, lo = int(np.argmax(w_navs)), int(np.argmin(w_navs))
        out.update(high_52w=w_navs[hi], high_52w_date=w_dates[hi],
                   low_52w=w_navs[lo], low_52w_date=w_dates[lo])
    return out


def compute_and_store_stats(log, target_date, include_closed=False):
    """
    Recompute MutualFundReturnStat for eligible, non-closed schemes (called at the end of sync_daily_nav).
    Closed schemes are skipped -> their old stat row stays frozen.
    One bad scheme never stops the run. Returns (computed, failed, skipped_closed).
    """
    computed = failed = skipped_closed = 0
    base_qs = eligible_scheme_qs()
    if not include_closed:
        skipped_closed = base_qs.filter(nav_closed=True).count()
        base_qs = base_qs.filter(nav_closed=False)

    cutoff = target_date - relativedelta(years=10, days=15)   # drop for full inception history

    for scheme_id in base_qs.values_list("id", flat=True).iterator():
        try:
            rows = list(MutualFundNAV.objects
                        .filter(scheme_id=scheme_id, nav_date__gte=cutoff, is_carry_forward=False)  # real NAVs only
                        .order_by("nav_date").values_list("nav_date", "nav"))
            if not rows:
                continue
            dates = [r[0] for r in rows]
            navs = [float(r[1]) for r in rows]
            stats = compute_stats(dates, navs)
            if stats:
                MutualFundReturnStat.objects.update_or_create(scheme_id=scheme_id, defaults=stats)
                computed += 1
        except Exception:                                # noqa: BLE001
            failed += 1
            logger.exception("stats failed for scheme_id=%s", scheme_id)

    # Category percentile pass (non-closed schemes only)
    try:
        with connection.cursor() as cur:
            for col, pct in (("ret_1y", "pct_1y"), ("cagr_3y", "pct_3y"), ("cagr_5y", "pct_5y")):
                cur.execute(f"""
                    UPDATE mutual_fund_return_stat r SET {pct} = x.p FROM (
                      SELECT rs.id, 100 * PERCENT_RANK() OVER (
                               PARTITION BY m.category_id ORDER BY rs.{col}) AS p
                      FROM mutual_fund_return_stat rs
                      JOIN mutual_fund_scheme s ON s.id = rs.scheme_id
                      JOIN mutual_fund_master m ON m.id = s.fund_master_id
                      WHERE rs.{col} IS NOT NULL AND s.nav_closed = FALSE
                    ) x WHERE r.id = x.id""")
    except Exception:                                    # noqa: BLE001
        logger.exception("percentile pass failed")

    log.stats_computed, log.stats_failed, log.stats_skipped_closed = computed, failed, skipped_closed
    log.save(update_fields=["stats_computed", "stats_failed", "stats_skipped_closed"])
    return computed, failed, skipped_closed