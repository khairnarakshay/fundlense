"""
Monthly portfolio-statistics sync.

Reads schemes from the Upvaly FinAPI per AMC and updates:
    * MutualFundMaster.fund_manager
    * MutualFundsScheme  (has_exit_load, exit_load_value, is_amc_active)
    * MutualFundportfolioStat (all portfolio / fundamental / risk fields)

A scheme is matched to the API by its `amfi_code == schemeCode`.
A stats row is keyed by `fund_master` (one row per fund, not per plan).
"""
import json
import logging
from urllib.parse import quote

import requests
from django.db import connection, transaction
from django.utils import timezone

from mutual_fund.models import (
    MutualFundAMC,
    MutualFundMaster,
    MutualFundsScheme,
    MutualFundportfolioStat,
)
from mutual_fund.utils.coerce import (
    coerce_for_field,
    coerce_dict_for_model,
    sql_cast_for_field,
)

logger = logging.getLogger(__name__)

from django.db import models as dj_models
# ===========================================================================
# Low-level: bulk CASE-WHEN UPDATE
# ===========================================================================
def _bulk_case_update(model_cls, id_payload_pairs):
    """
    id_payload_pairs: list of (pk, {field_name: python_value})
    Executes ONE SQL UPDATE using CASE WHEN per field.

    Important: the whole CASE expression is cast to the target column
    type (e.g. ::numeric, ::jsonb, ::date, ::boolean). Without this
    Postgres infers 'text' whenever a NULL branch is mixed with a
    parameter branch, and then rejects the assignment.
    """
    if not id_payload_pairs:
        return 0

    table = model_cls._meta.db_table
    all_ids = list({pk for pk, _ in id_payload_pairs})

    # union of all fields across all payloads
    all_fields = set()
    for _, payload in id_payload_pairs:
        all_fields.update(payload.keys())

    params = []
    set_clauses = []

    for fname in all_fields:
        field = model_cls._meta.get_field(fname)
        cast = sql_cast_for_field(field)              # '', '::numeric', '::jsonb', ...
        is_json = isinstance(field, dj_models.JSONField)

        case_parts = []
        for pk, payload in id_payload_pairs:
            if fname not in payload:
                continue

            value = payload[fname]

            if value is None:
                # Always cast NULL too — keeps the CASE internally consistent
                case_parts.append(f"WHEN id = %s THEN NULL{cast}")
                params.append(pk)
                continue

            if is_json:
                if not isinstance(value, str):
                    value = json.dumps(value)
                case_parts.append(f"WHEN id = %s THEN %s{cast}")
                params.append(pk)
                params.append(value)
            else:
                case_parts.append(f"WHEN id = %s THEN %s{cast}")
                params.append(pk)
                params.append(value)

        # ⬇⬇⬇ THE FIX — cast the entire CASE expression ⬇⬇⬇
        case_sql = "CASE " + " ".join(case_parts) + " END"
        if cast:
            set_clauses.append(f"{fname} = ({case_sql}){cast}")
        else:
            set_clauses.append(f"{fname} = {case_sql}")

    params.extend(all_ids)
    sql = f"""
        UPDATE {table}
        SET {', '.join(set_clauses)}
        WHERE id IN ({','.join(['%s'] * len(all_ids))})
    """

    with connection.cursor() as cur:
        cur.execute(sql, params)

    return len(all_ids)

def dj_models_json_like():
    from django.db import models as dj_models
    return (dj_models.JSONField,)


# ===========================================================================
# STEP 1 — create missing portfolio stats
# ===========================================================================
def sync_missing_portfolio_stats(command, verbose=False, specific_amc=None):
    """
    Create a MutualFundportfolioStat row for every MutualFundMaster that
    does not yet have one. nav_closed seeded from scheme.is_amc_active.
    """
    total_created = 0

    amcs = MutualFundAMC.objects.filter(is_active=True).order_by("name")
    if specific_amc:
        amcs = amcs.filter(name__icontains=specific_amc)

    for amc in amcs:
        if verbose:
            command.stdout.write(f"\nCreating missing stats for AMC: {amc.name}")

        master_ids      = set(MutualFundMaster.objects
                              .filter(fund_house=amc)
                              .values_list("id", flat=True))
        have_stat_ids   = set(MutualFundportfolioStat.objects
                              .filter(fund__fund_house=amc)
                              .values_list("fund_id", flat=True))
        missing_ids     = master_ids - have_stat_ids

        if not missing_ids:
            if verbose:
                command.stdout.write(
                    f"  All {len(master_ids)} masters already have stats"
                )
            continue

        now = timezone.now()
        bulk = []
        for master in MutualFundMaster.objects.filter(id__in=missing_ids):
            sample = master.schemes.first()
            stat = MutualFundportfolioStat(
                fund=master,
                nav_closed=not (sample.is_amc_active if sample else True),
                asset_allocation={},
                market_cap_weightage={},
                holdings=[],
                sectors=[],
            )
            stat.created = now
            stat.updated = now
            bulk.append(stat)

        if bulk:
            MutualFundportfolioStat.objects.bulk_create(bulk, batch_size=500)
            total_created += len(bulk)
            if verbose:
                command.stdout.write(
                    command.style.SUCCESS(f"  Created {len(bulk)} stats for {amc.name}")
                )

    command.stdout.write(
        command.style.SUCCESS(f"Total portfolio stats created: {total_created}")
    )
    return total_created


# ===========================================================================
# STEP 2 — populate one stat row from one API scheme
# ===========================================================================
def populate_portfolio_stat_from_scheme(stat, scheme, *, log=None):
    portfolio    = scheme.get("portfolio") or {}
    asset        = portfolio.get("assetAllocation") or {}
    market_cap   = portfolio.get("marketCapWeightage") or {}
    holdings     = scheme.get("holdings") or []
    sectors      = scheme.get("sectors") or []
    fundamentals = scheme.get("fundamentals") or {}

    # ---------- raw values (everything that will be coerced) -------------
    raw = {
        "avarage_maturity":       fundamentals.get("averageMaturity"),
        "modified_duration":      fundamentals.get("modifiedDuration"),
        "yield_to_maturity":      fundamentals.get("yieldToMaturity"),
        "aum":                    scheme.get("aum"),
        "portfolio_turnover":     scheme.get("portfolioTurnover"),
        "price_earning":          portfolio.get("priceEarning"),
        "price_to_bookval":       portfolio.get("priceToBook"),
        "expense_ratio":          scheme.get("expenseRatio"),
        "_52_week_low_nav":       scheme.get("52WeekLowNav"),
        "_52_week_low_nav_date":  scheme.get("52WeekLowNavDate"),
        "_52_week_high_nav":      scheme.get("52WeekHighNav"),
        "_52_week_high_nav_date": scheme.get("52WeekHighNavDate"),
        "fund_manager":           scheme.get("schemeFundManagers"),
        "exit_load_msg":          scheme.get("exitLoadMessage"),
        "scheme_category":        scheme.get("schemeCategory"),
        "scheme_categorylabel":   scheme.get("schemeCategoryLabel"),
        "scheme_structure":       scheme.get("schemeStructure"),
        "scheme_risk":            scheme.get("schemeRisk"),
        "benchmark_index":        scheme.get("benchmarkIndex"),
        "inception_date":         scheme.get("inceptionDate"),
    }

    coerced = coerce_dict_for_model(MutualFundportfolioStat, raw, log=log)
    for fname, value in coerced.items():
        setattr(stat, fname, value)

    # ---------- JSON blobs — stored as-is --------------------------------
    stat.asset_allocation     = asset or {}
    stat.market_cap_weightage = market_cap or {}
    stat.holdings             = holdings or []
    stat.sectors              = sectors or []

    return stat

def _persist_portfolio_stats(updates):
    if not updates:
        return 0

    fields = [
        # numeric
        "avarage_maturity", "modified_duration", "yield_to_maturity",
        "aum", "portfolio_turnover", "price_earning", "price_to_bookval",
        "expense_ratio",
        "_52_week_low_nav", "_52_week_high_nav",
        # dates (stored as DateField now)
        "_52_week_low_nav_date", "_52_week_high_nav_date", "inception_date",
        # text
        "scheme_category", "scheme_categorylabel", "scheme_structure",
        "scheme_risk", "benchmark_index",
        "exit_load_msg", "fund_manager",
        # json
        "asset_allocation", "market_cap_weightage", "holdings", "sectors",
        # timestamp
        "updated",
    ]

    now = timezone.now()
    payloads = []
    for obj in updates:
        payload = {f: getattr(obj, f, None) for f in fields}
        payload["updated"] = now
        payloads.append((obj.id, payload))

    return _bulk_case_update(MutualFundportfolioStat, payloads)

# ===========================================================================
# STEP 3 — master + scheme updates
# ===========================================================================
def update_master_from_api(api_data, scheme_map):
    """
    Update MutualFundMaster.fund_manager from API (one master may be
    referenced by many schemes; we take the latest non-empty value).
    """
    now = timezone.now()
    payloads = {}  # master_id -> {fund_manager, updated}

    for scheme in api_data:
        api_code = str(scheme.get("schemeCode", "")).strip()
        db_scheme = scheme_map.get(api_code)
        if not db_scheme:
            continue

        master = db_scheme.fund_master
        raw = {
            "fund_manager": scheme.get("schemeFundManagers"),
            "updated":      now,
        }
        print("raw",raw)

        coerced = coerce_dict_for_model(MutualFundMaster, raw)
        if "fund_manager" not in coerced:
            continue

        current = payloads.get(master.id)
        if current is None or master.fund_manager != coerced["fund_manager"]:
            payloads[master.id] = {
                "fund_manager": coerced["fund_manager"],
                "updated":      now,
            }

    if not payloads:
        return 0
    return _bulk_case_update(MutualFundMaster, list(payloads.items()))


def update_schemes_from_api(api_data, scheme_map):
    """
    Update MutualFundsScheme for every scheme returned by the API:
        * is_amc_active = True
        * has_exit_load / exit_load_value from exitLoad / exitLoadMessage
    """
    now = timezone.now()
    payloads = {}  # scheme_id -> payload

    for scheme in api_data:
        api_code = str(scheme.get("schemeCode", "")).strip()
        db_scheme = scheme_map.get(api_code)
        if not db_scheme:
            continue

        exit_load     = scheme.get("exitLoad")
        exit_load_msg = scheme.get("exitLoadMessage")

        raw = {
            "exit_load_value": exit_load,
            "is_amc_active":   True,
            "updated":         now,
        }
        coerced = coerce_dict_for_model(MutualFundsScheme, raw)
        coerced["has_exit_load"] = bool(
            (exit_load not in (None, "", 0, "0", "0.00"))
            or exit_load_msg
        )

        changed = any(getattr(db_scheme, k) != v for k, v in coerced.items())
        if changed:
            payloads[db_scheme.id] = coerced

    if not payloads:
        return 0
    return _bulk_case_update(MutualFundsScheme, list(payloads.items()))


def deactivate_missing_schemes(api_scheme_codes, scheme_map):
    """Any scheme not in the API response is set is_amc_active=False."""
    now = timezone.now()
    payloads = []
    for code, db_scheme in scheme_map.items():
        if code not in api_scheme_codes and db_scheme.is_amc_active:
            payloads.append(
                (
                    db_scheme.id,
                    {"is_amc_active": False, "updated": now},
                )
            )
    return _bulk_case_update(MutualFundsScheme, payloads)


def reactivate_api_schemes(api_scheme_codes, scheme_map):
    """Schemes returned by the API that were previously inactive."""
    now = timezone.now()
    payloads = []
    for code, db_scheme in scheme_map.items():
        if code in api_scheme_codes and not db_scheme.is_amc_active:
            payloads.append(
                (
                    db_scheme.id,
                    {"is_amc_active": True, "updated": now},
                )
            )
    return _bulk_case_update(MutualFundsScheme, payloads)


# ===========================================================================
# STEP 4 — main orchestrator
# ===========================================================================
def _scheme_map_for_amc(amc):
    qs = (
        MutualFundsScheme.objects
        .select_related("fund_master")
        .filter(fund_master__fund_house=amc, amfi_code__isnull=False)
    )
    return {str(s.amfi_code).strip(): s for s in qs if s.amfi_code}


def _stat_map_for_amc(amc):
    qs = (
        MutualFundportfolioStat.objects
        .select_related("fund")
        .filter(fund__fund_house=amc)
    )
    return {str(st.fund.amfi_code).strip(): st
            for st in qs
            if st.fund and st.fund.amfi_code}


# ===========================================================================
# STEP 4 — main orchestrator
# ===========================================================================


def _diagnose_amc(amc, scheme_map, master_stat, api_data, command, verbose):
    """
    Print the master/stat/scheme overlap for one AMC so you can see
    exactly why stat_updates might come back empty.
    """
    masters_with_schemes = set(
        MutualFundMaster.objects
        .filter(fund_house=amc, schemes__isnull=False)
        .values_list("id", flat=True)
    )
    masters_with_stats = {st.fund_id for st in master_stat.values()}

    orphan_stats = masters_with_stats - masters_with_schemes
    covered      = masters_with_schemes & masters_with_stats

    msg = (
        f"  [{amc.name}] schemes={len(scheme_map)} "
        f"api={len(api_data)} "
        f"masters_with_schemes={len(masters_with_schemes)} "
        f"masters_with_stats={len(masters_with_stats)} "
        f"overlap={len(covered)} "
        f"orphan_stats={len(orphan_stats)}"
    )
    command.stdout.write(msg)

    if orphan_stats:
        command.stdout.write(command.style.WARNING(
            f"  ⚠ {len(orphan_stats)} stat rows point at masters "
            f"with no schemes — these will never be matched by the API. "
            f"Run sync_missing_portfolio_stats or reconcile them."
        ))

    if not covered:
        command.stdout.write(command.style.ERROR(
            "  ✖ zero overlap between stat-masters and scheme-masters "
            "→ stat_updates will be empty for this AMC."
        ))

    return covered, orphan_stats


def sync_portfolio_statistics(command, api_url, verbose=False, specific_amc=None):
    total_amc   = 0
    success_amc = 0
    failed_amc  = 0
    total_updated  = 0
    total_closed   = 0
    total_reopened = 0

    amcs = MutualFundAMC.objects.filter(is_active=True).order_by("name")
    if specific_amc:
        amcs = amcs.filter(name__icontains=specific_amc)
    total_amcs = amcs.count()

    for amc in amcs:
        total_amc += 1
        if verbose:
            command.stdout.write("\n" + "=" * 60)
            command.stdout.write(f"Processing AMC: {amc.name}")
            command.stdout.write("=" * 60)

        try:
            # 1. API call ---------------------------------------------------
            url = api_url.format(quote(amc.name))
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("statusCode") != 200:
                failed_amc += 1
                if verbose:
                    command.stdout.write(command.style.ERROR(
                        f"  API statusCode={payload.get('statusCode')}"
                    ))
                continue
            api_data = payload.get("data") or []
            print("api_data",api_data)
            if not isinstance(api_data, list):
                failed_amc += 1
                if verbose:
                    command.stdout.write(command.style.ERROR(
                        "  API data is not a list"
                    ))
                continue

            if verbose:
                command.stdout.write(f"Received {len(api_data)} schemes from API")

            # 2. Local maps -------------------------------------------------
            scheme_map = _scheme_map_for_amc(amc)
            master_stat = {
                st.fund_id: st
                for st in MutualFundportfolioStat.objects
                    .select_related("fund")
                    .filter(fund__fund_house=amc)
            }

            # 2b. Diagnostic funnel ----------------------------------------
            if verbose:
                _diagnose_amc(amc, scheme_map, master_stat, api_data,
                              command, verbose)

            # 3. API codes --------------------------------------------------
            api_scheme_codes = {
                str(s.get("schemeCode", "")).strip()
                for s in api_data
                if s.get("schemeCode")
            }

            # 4. Build stat updates (dedupe by stat.id) ---------------------
            stat_updates = {}
            touched_masters = set()

            skip_no_db_scheme = 0
            skip_no_master    = 0
            skip_no_stat      = 0

            for scheme in api_data:
                api_code = str(scheme.get("schemeCode", "")).strip()
                db_scheme = scheme_map.get(api_code)
                if not db_scheme:
                    skip_no_db_scheme += 1
                    continue

                master = db_scheme.fund_master
                if master is None:
                    skip_no_master += 1
                    if verbose:
                        command.stdout.write(command.style.WARNING(
                            f"  skip {api_code} / {db_scheme.scheme_name}: "
                            f"no fund_master"
                        ))
                    continue

                stat = master_stat.get(master.id)
                if stat is None:
                    skip_no_stat += 1
                    if verbose:
                        command.stdout.write(command.style.WARNING(
                            f"  skip {api_code} / {db_scheme.scheme_name}: "
                            f"master {master.id} ({master.master_name}) "
                            f"has no stat row"
                        ))
                    continue

                populate_portfolio_stat_from_scheme(stat, scheme, log=logger.warning)
                stat.updated = timezone.now()
                stat_updates[stat.id] = stat
                touched_masters.add(master.id)

            if verbose:
                command.stdout.write(
                    f"  funnel: db_scheme_miss={skip_no_db_scheme} "
                    f"no_master={skip_no_master} "
                    f"no_stat={skip_no_stat} "
                    f"→ stat_updates={len(stat_updates)}"
                )

            if not stat_updates and api_data:
                command.stdout.write(command.style.WARNING(
                    f"  ⚠ {amc.name}: built 0 stat updates from "
                    f"{len(api_data)} API schemes"
                ))

            # 5. Persist in a single transaction ---------------------------
            now = timezone.now()
            closed_this   = 0
            reopened_this = 0

            with transaction.atomic():
                update_master_from_api(api_data, scheme_map)
                update_schemes_from_api(api_data, scheme_map)

                reopened_this = reactivate_api_schemes(api_scheme_codes, scheme_map)
                closed_this   = deactivate_missing_schemes(api_scheme_codes, scheme_map)

                # Sync stat.nav_closed from scheme.is_amc_active
                stat_nav_payload = []
                for stat in master_stat.values():
                    sample = MutualFundsScheme.objects.filter(
                        fund_master_id=stat.fund_id
                    ).first()
                    if not sample:
                        continue
                    desired = not sample.is_amc_active
                    if stat.nav_closed != desired:
                        stat_nav_payload.append(
                            (stat.id, {"nav_closed": desired, "updated": now})
                        )
                if stat_nav_payload:
                    _bulk_case_update(MutualFundportfolioStat, stat_nav_payload)

                # Write portfolio-stat payloads
                if stat_updates:
                    count = _persist_portfolio_stats(list(stat_updates.values()))
                    total_updated += count

            total_closed   += closed_this
            total_reopened += reopened_this
            success_amc    += 1

            command.stdout.write(
                f"{amc.name}: "
                f"API={len(api_data)} "
                f"DB-matched={len(api_data) - skip_no_db_scheme} "
                f"Updated={len(stat_updates)} "
                f"Closed={closed_this} "
                f"Reopened={reopened_this}"
            )

        except Exception as exc:
            failed_amc += 1
            logger.exception(f"Error for {amc.name}: {exc}")
            if verbose:
                command.stdout.write(
                    command.style.ERROR(f"{amc.name} -> Error: {exc}")
                )
            continue

    command.stdout.write(f"Progress: {success_amc}/{total_amcs} AMCs completed")

    return {
        "total_amc":      total_amc,
        "success_amc":    success_amc,
        "failed_amc":     failed_amc,
        "total_updated":  total_updated,
        "total_closed":   total_closed,
        "total_reopened": total_reopened,
    }