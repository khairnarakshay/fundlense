r"""
Import / sync the BSE StAR MF "Scheme Master Details" file (SCHMSTRDET_*.txt)
into ``MutualFundsScheme``.

    python manage.py import_bse_scheme_master /path/to/SCHMSTRDET_19092026.txt
    python manage.py import_bse_scheme_master /path/to/SCHMSTRDET_19092026.txt --dry-run
    python manage.py import_bse_scheme_master /path/to/file.txt --default-subcategory 12

Duplicate protection
--------------------
Every row is keyed on ``bse_unique_no`` (the BSE "Unique No" column, which is
UNIQUE in the table).  The command is a safe upsert:

* Unique No not in DB        -> row is created
* Unique No already in DB    -> only the file-driven columns that actually
                                changed are updated (nothing changes -> no write)
* Same Unique No twice in the file -> the last occurrence wins (warning logged)

So you can run it with the same file, or with every new daily file, as often
as you like.

What it does NOT touch
----------------------
AMC / FundCategory / FundSubCategory rows are never created or modified.
Columns that are not in the BSE file (amfi_code, risk_level, ranking, rank,
face_value ...) are never overwritten on existing schemes.
"""
import csv
import logging
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

LOGGER_NAME = "bse_scheme_import"
logger = logging.getLogger(LOGGER_NAME)

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# Optional aliases used when the file value is not literally one of your
# *_CHOICES keys/labels.  Add to these if the run summary lists unmatched values.
PLAN_ALIASES = {"normal": ["Regular", "Regular Plan"], "direct": ["Direct Plan"]}
RTA_ALIASES = {"karvy": ["KFintech", "KFin"], "cams": ["CAMS"]}
OPTION_ALIASES = {
    "growth": ["Growth Option"],
    "idcwpayout": ["Dividend Payout", "Payout", "IDCW"],
    "idcwreinvestment": ["Dividend Reinvestment", "Reinvestment", "IDCW"],
    "idcw": ["Dividend"],
}


# --------------------------------------------------------------------------- #
# Small parsing helpers
# --------------------------------------------------------------------------- #
def _norm_header(h):
    """'Redemption Amount – Maximum' / 'Redemption Amount - Maximum' -> same key."""
    return re.sub(r"[\s\-\u2010-\u2015]+", " ", (h or "").strip()).upper()


def _s(v):
    return (v or "").strip()


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _dec(v, col):
    v = _s(v)
    if v == "":
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        raise ValueError(f"{col}: invalid number {v!r}")


def _date(v, col):
    """BSE dates look like 'Nov  5 2013' (note the double space)."""
    v = _s(v)
    if not v:
        return None
    try:
        mon, day, year = v.split()
        return datetime(int(year), MONTHS[mon[:3].upper()], int(day)).date()
    except (ValueError, KeyError):
        raise ValueError(f"{col}: invalid date {v!r}")


def _time(v, col):
    v = _s(v)
    if not v:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"{col}: invalid time {v!r}")


def _flag(v, true_values=("Y", "1")):
    return _s(v).upper() in true_values


# --------------------------------------------------------------------------- #
# Scheme-name splitting:  "<FUND NAME> - REGULAR PLAN - IDCW PAYOUT"
#                          ^ master_name   ^ plan/option tail
# Only *trailing* plan/option words are stripped, so a fund called
# "... REGULAR SAVINGS FUND" or "... GROWTH OPPORTUNITIES FUND" is safe.
# --------------------------------------------------------------------------- #
_FREQ = r"(?:MONTHLY|QUARTERLY|WEEKLY|DAILY|ANNUAL|YEARLY|HALF[\s-]?YEARLY|FORTNIGHTLY|PERIODIC|BI[\s-]?WEEKLY)"
_TRAILING = re.compile(
    r"(?:[\s\-\u2010-\u2015/]*(?:"
    r"(?:DIRECT|REGULAR|NORMAL)(?:\s+PLAN)?"
    r"|GROWTH(?:\s+(?:OPTION|PLAN))?"
    rf"|(?:{_FREQ}\s+)?(?:(?:IDCW|DIVIDEND)(?:\s+(?:PAYOUT|PAY\s?OUT|REINVESTMENT|REINVEST|SWEEP))?|PAYOUT|REINVESTMENT)(?:\s+OPTION)?"
    r"|BONUS(?:\s+OPTION)?"
    r"|OPTION"
    r")|[\-\u2010-\u2015]\s*PLAN)\s*$",
    re.I,
)


def split_scheme_name(name):
    """Return (master_name, option_tail)."""
    name = " ".join(name.split())
    base = name
    while True:
        new = _TRAILING.sub("", base)
        if new == base:
            break
        base = new
    base = base.rstrip(" -\u2013\u2014/")
    if not base:  # whole name looked like an option word - keep it as is
        return name, ""
    return base, name[len(base):]


_CLOSE_ENDED = re.compile(
    r"\bFMP\b|FIXED\s+(?:MATURITY|TERM|HORIZON|DURATION)|CLOSE[D]?[\s-]?ENDED|CAPITAL\s+PROTECTION|\bSERIES\b", re.I)
_INTERVAL = re.compile(r"\bINTERVAL\b", re.I)


def derive_fund_type(name):
    """
    The BSE file has NO open/closed-ended column (its 'Scheme Type' is EQUITY/DEBT/...),
    so this is inferred from the scheme name: FMP / Fixed Maturity / Series / ... ->
    CLOSE_ENDED, 'Interval' -> INTERVAL, everything else -> OPEN_ENDED.
    Edit here if you want different behaviour.
    """
    if _INTERVAL.search(name):
        return "INTERVAL"
    if _CLOSE_ENDED.search(name):
        return "CLOSE_ENDED"
    return "OPEN_ENDED"


def option_from_tail(tail):
    t = tail.upper()
    if not t.strip(" -"):
        return None
    if "GROWTH" in t:
        return "Growth"
    if "BONUS" in t:
        return "Bonus"
    if "REINVEST" in t:
        return "IDCW Reinvestment"
    if "PAYOUT" in t or "PAY OUT" in t:
        return "IDCW Payout"
    if "IDCW" in t or "DIVIDEND" in t:
        return "IDCW"
    return None


# --------------------------------------------------------------------------- #
# Maps file text -> your CHOICES keys (read straight from the model fields)
# --------------------------------------------------------------------------- #
class ChoiceResolver:
    def __init__(self, model, field_name, aliases=None):
        self.field_name = field_name
        self.aliases = aliases or {}
        self.lookup = {}
        for key, label in model._meta.get_field(field_name).flatchoices:
            self.lookup.setdefault(_key(key), key)
            self.lookup.setdefault(_key(label), key)
        self.unmatched = Counter()

    def resolve(self, raw):
        raw = _s(raw)
        if not raw:
            return None
        for cand in [raw] + self.aliases.get(_key(raw), []):
            hit = self.lookup.get(_key(cand))
            if hit is not None:
                return hit
        self.unmatched[raw] += 1
        return None


def _get_model(name):
    found = [m for m in apps.get_models() if m.__name__ == name]
    if len(found) != 1:
        raise CommandError(f"Could not uniquely locate model {name!r} (found {len(found)}).")
    return found[0]


class Command(BaseCommand):
    help = "Load / sync BSE StAR MF scheme master file (SCHMSTRDET_*.txt) into MutualFundsScheme (idempotent)."

    REQUIRED_COLUMNS = [
        "UNIQUE NO", "SCHEME CODE", "ISIN", "AMC CODE", "SCHEME NAME",
    ]

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to SCHMSTRDET_*.txt (pipe separated)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Run everything inside a transaction and roll it back at the end.")
        parser.add_argument("--default-subcategory", type=int, default=None, metavar="ID",
                            help="FundSubCategory id used ONLY when a new MutualFundMaster has to be created "
                                 "for a scheme whose fund is not already in mutual_fund_master.")
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--encoding", default="utf-8-sig")
        parser.add_argument("--log-dir", default=None,
                            help="Where to write the log file (default: <BASE_DIR>/logs)")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        log_path = self._setup_logging(opts["log_dir"])
        started = time.time()
        try:
            self._run(opts, log_path)
        except CommandError:
            raise
        except Exception:
            logger.exception("Import failed - nothing was committed")
            raise
        finally:
            logger.info("Finished in %.1fs", time.time() - started)
            self._teardown_logging()

    # ------------------------------------------------------------------ #
    def _setup_logging(self, log_dir):
        log_dir = log_dir or os.path.join(str(getattr(settings, "BASE_DIR", ".")), "logs")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"bse_scheme_import_{datetime.now():%Y%m%d_%H%M%S}.log")
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(self.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.addHandler(fh)
        logger.addHandler(sh)
        self._handlers = (fh, sh)
        return path

    def _teardown_logging(self):
        for h in getattr(self, "_handlers", ()):
            h.close()
            logger.removeHandler(h)

    # ------------------------------------------------------------------ #
    def _run(self, opts, log_path):
        Scheme = _get_model("MutualFundsScheme")
        Master = _get_model("MutualFundMaster")
        AMC = _get_model("MutualFundAMC")
        SubCategory = _get_model("FundSubCategory")

        path = opts["file"]
        if not os.path.isfile(path):
            raise CommandError(f"File not found: {path}")

        dry_run = opts["dry_run"]
        logger.info("=== BSE scheme import | file=%s | dry_run=%s | log=%s", path, dry_run, log_path)

        default_sub = None
        if opts["default_subcategory"] is not None:
            default_sub = SubCategory.objects.filter(pk=opts["default_subcategory"]).first()
            if default_sub is None:
                raise CommandError(f"FundSubCategory id={opts['default_subcategory']} does not exist")

        resolvers = {
            "fund_type": ChoiceResolver(Scheme, "fund_type"),
            "option": ChoiceResolver(Scheme, "option", OPTION_ALIASES),
            "plans": ChoiceResolver(Scheme, "plans", PLAN_ALIASES),
            "register_agent": ChoiceResolver(Scheme, "register_agent", RTA_ALIASES),
        }

        # ---- 1. parse the file ------------------------------------------------
        records, stats = self._parse_file(path, opts["encoding"], resolvers)

        # ---- 2. AMC lookup (existing rows only) --------------------------------
        amc_by_code = {c.upper(): pk for pk, c in AMC.objects.exclude(bse_amc_code__isnull=True)
                       .values_list("pk", "bse_amc_code") if c}
        unknown_amc = Counter()
        usable = []
        for rec in records:
            amc_id = amc_by_code.get(rec["amc_code"].upper())
            if amc_id is None:
                unknown_amc[rec["amc_code"]] += 1
                continue
            rec["amc_id"] = amc_id
            usable.append(rec)
        stats["skipped_unknown_amc"] = sum(unknown_amc.values())
        for code, n in unknown_amc.most_common():
            logger.warning("AMC code %r not found in mutual_fund_amc.bse_amc_code - %d scheme(s) skipped", code, n)

        # ---- 3. write ------------------------------------------------------------
        with transaction.atomic():
            self._sync(Scheme, Master, usable, default_sub, opts["batch_size"], stats)
            if dry_run:
                transaction.set_rollback(True)
                logger.info("DRY RUN - all changes rolled back")

        # ---- 4. summary ----------------------------------------------------------
        for name, res in resolvers.items():
            for raw, n in res.unmatched.most_common():
                logger.warning("No %s choice matches file value %r (%d rows) - stored as empty. "
                               "Adjust *_ALIASES in this command or your choices.", name, raw, n)
        logger.info(
            "SUMMARY rows_read=%d invalid_rows=%d in_file_duplicates=%d unknown_amc=%d "
            "no_master=%d | masters_created=%d | schemes_created=%d updated=%d unchanged=%d",
            stats["rows_read"], stats["invalid"], stats["dupes"], stats["skipped_unknown_amc"],
            stats["skipped_no_master"], stats["masters_created"],
            stats["created"], stats["updated"], stats["unchanged"],
        )

    # ------------------------------------------------------------------ #
    def _parse_file(self, path, encoding, resolvers):
        stats = defaultdict(int)
        by_unique_no = {}

        with open(path, encoding=encoding, newline="") as fh:
            reader = csv.reader(fh, delimiter="|", quoting=csv.QUOTE_NONE)
            try:
                header = [_norm_header(h) for h in next(reader)]
            except StopIteration:
                raise CommandError("File is empty")

            missing = [c for c in self.REQUIRED_COLUMNS if c not in header]
            if missing:
                raise CommandError(f"Not a BSE scheme master file - missing columns: {missing}")

            for line_no, row in enumerate(reader, start=2):
                if not any(_s(x) for x in row):
                    continue
                stats["rows_read"] += 1
                data = dict(zip(header, row))
                try:
                    rec = self._build_record(data, resolvers)
                except ValueError as exc:
                    stats["invalid"] += 1
                    logger.error("line %d skipped: %s", line_no, exc)
                    continue
                if rec["unique_no"] in by_unique_no:
                    stats["dupes"] += 1
                    logger.warning("line %d: Unique No %s appears more than once in file - last one wins",
                                   line_no, rec["unique_no"])
                by_unique_no[rec["unique_no"]] = rec

        logger.info("Parsed %d rows -> %d unique schemes (%d invalid)",
                    stats["rows_read"], len(by_unique_no), stats["invalid"])
        return list(by_unique_no.values()), stats

    def _build_record(self, d, resolvers):
        g = lambda col: d.get(col, "")  # noqa: E731

        try:
            unique_no = int(_s(g("UNIQUE NO")))
        except ValueError:
            raise ValueError(f"invalid Unique No {g('UNIQUE NO')!r}")
        isin = _s(g("ISIN"))
        if len(isin) != 12:
            raise ValueError(f"Unique No {unique_no}: ISIN {isin!r} is not 12 characters")
        name = " ".join(_s(g("SCHEME NAME")).split())
        if not name:
            raise ValueError(f"Unique No {unique_no}: empty scheme name")
        amc_code = _s(g("AMC CODE"))
        if not amc_code:
            raise ValueError(f"Unique No {unique_no}: empty AMC code")

        master_name, tail = split_scheme_name(name)

        try:
            values = {
                "scheme_name": name,
                "fund_type": resolvers["fund_type"].resolve(derive_fund_type(name)) or "",
                "option": resolvers["option"].resolve(option_from_tail(tail)),
                "plans": resolvers["plans"].resolve(g("SCHEME PLAN")),
                "scheme_code": _s(g("SCHEME CODE")),
                "amc_scheme_code": _s(g("AMC SCHEME CODE")) or None,
                "isin_code": isin,
                "rta_code": _s(g("RTA AGENT CODE")) or None,
                "rta_scheme_code": _s(g("RTA SCHEME CODE")) or None,
                "register_agent": resolvers["register_agent"].resolve(g("RTA AGENT CODE")),

                "purchase_allowed": _flag(g("PURCHASE ALLOWED")),
                "purchase_transaction_mode": _s(g("PURCHASE TRANSACTION MODE")),
                "min_investment": _dec(g("MINIMUM PURCHASE AMOUNT"), "Minimum Purchase Amount"),
                "additional_investment": _dec(g("ADDITIONAL PURCHASE AMOUNT"), "Additional Purchase Amount"),
                "max_purchase_amount": _dec(g("MAXIMUM PURCHASE AMOUNT"), "Maximum Purchase Amount") or Decimal("0"),
                "purchase_amount_multiplier": _dec(g("PURCHASE AMOUNT MULTIPLIER"), "Purchase Amount Multiplier"),
                "purchase_cutoff_time": _time(g("PURCHASE CUTOFF TIME"), "Purchase Cutoff Time"),

                "redemption_allowed": _flag(g("REDEMPTION ALLOWED")),
                "redemption_transaction_mode": _s(g("REDEMPTION TRANSACTION MODE")) or None,
                "min_redemption_qty": _dec(g("MINIMUM REDEMPTION QTY"), "Minimum Redemption Qty"),
                "redemption_qty_multiplier": _dec(g("REDEMPTION QTY MULTIPLIER"), "Redemption Qty Multiplier"),
                "max_redemption_qty": _dec(g("MAXIMUM REDEMPTION QTY"), "Maximum Redemption Qty"),
                "min_redemption_amount": _dec(g("REDEMPTION AMOUNT MINIMUM"), "Redemption Amount - Minimum"),
                "max_redemption_amount": _dec(g("REDEMPTION AMOUNT MAXIMUM"), "Redemption Amount - Maximum"),
                "redemption_amount_multiple": _dec(g("REDEMPTION AMOUNT MULTIPLE"), "Redemption Amount Multiple"),
                "redemption_cutoff_time": _time(g("REDEMPTION CUT OFF TIME"), "Redemption Cut off Time"),

                "settlement_type": _s(g("SETTLEMENT TYPE")),
                "is_amc_active": _flag(g("AMC ACTIVE FLAG")),
                # BSE: Y = reinvestment, N = payout, Z = not applicable (growth)
                "is_dividend_reinvestment": _flag(g("DIVIDEND REINVESTMENT FLAG"), ("Y",)),
                "is_sip_allowed": _flag(g("SIP FLAG")),
                "is_stp_allowed": _flag(g("STP FLAG")),
                "is_swp_allowed": _flag(g("SWP FLAG")),
                "is_switch_allowed": _flag(g("SWITCH FLAG")),

                "start_date": _date(g("START DATE"), "Start Date"),
                "end_date": _date(g("END DATE"), "End Date"),
                "reopening_date": _date(g("REOPENING DATE"), "ReOpening Date"),

                "has_exit_load": _flag(g("EXIT LOAD FLAG")),
                "exit_load_value": _dec(g("EXIT LOAD"), "Exit Load") or Decimal("0"),
                "has_lock_in": _flag(g("LOCK IN PERIOD FLAG")),
                "lock_in_period_days": int(_dec(g("LOCK IN PERIOD"), "Lock-in Period") or 0),
                "channel_partner_code": _s(g("CHANNEL PARTNER CODE")) or None,
            }
        except ValueError as exc:
            raise ValueError(f"Unique No {unique_no}: {exc}")

        return {
            "unique_no": unique_no,
            "isin": isin,
            "amc_code": amc_code,
            "master_name": master_name,
            "master_key": master_name.upper(),
            "scheme_type": _s(g("SCHEME TYPE")).upper(),
            "values": values,
        }

    # ------------------------------------------------------------------ #
    def _sync(self, Scheme, Master, records, default_sub, batch_size, stats):
        existing = {s.bse_unique_no: s for s in Scheme.objects.all()}
        new_recs = [r for r in records if r["unique_no"] not in existing]

        # -- resolve fund_master for NEW schemes only --------------------------
        # 1) same ISIN already in DB  2) existing master with same AMC+name
        # 3) create a master (needs --default-subcategory)
        isin_master = dict(Scheme.objects.values_list("isin_code", "fund_master_id"))
        masters = {(fh, name.upper()): pk
                   for pk, fh, name in Master.objects.values_list("pk", "fund_house_id", "master_name")}

        first_key_for_isin = {}
        missing = {}  # key -> (amc_id, master_name)
        for rec in new_recs:
            if rec["isin"] in isin_master:
                rec["master_id"] = isin_master[rec["isin"]]
                continue
            key = first_key_for_isin.setdefault(rec["isin"], (rec["amc_id"], rec["master_key"]))
            rec["master_key_t"] = key
            if key in masters:
                rec["master_id"] = masters[key]
            else:
                missing.setdefault(key, (rec["amc_id"], rec["master_name"], rec["scheme_type"]))

        stats["masters_created"] = 0
        if missing and default_sub is None:
            logger.error("%d fund(s) are not in mutual_fund_master. Re-run with --default-subcategory <id> "
                         "to create them; schemes belonging to them are skipped for now.", len(missing))
            for _key_, (_, nm, _st) in list(missing.items())[:20]:
                logger.error("  missing master: %s", nm)
            if len(missing) > 20:
                logger.error("  ... and %d more", len(missing) - 20)
        elif missing:
            Master.objects.bulk_create(
                [Master(fund_house_id=amc_id, category=default_sub, master_name=nm, classification=(st or None))
                 for amc_id, nm, st in missing.values()],
                batch_size=batch_size,
            )
            stats["masters_created"] = len(missing)
            logger.info("Created %d new MutualFundMaster rows under sub-category id=%s", len(missing), default_sub.pk)
            masters = {(fh, name.upper()): pk
                       for pk, fh, name in Master.objects.values_list("pk", "fund_house_id", "master_name")}
            for rec in new_recs:
                if "master_id" not in rec:
                    rec["master_id"] = masters.get(rec["master_key_t"])

        # -- build create / update lists -------------------------------------------
        to_create, to_update = [], []
        stats["skipped_no_master"] = 0
        now = timezone.now()
        for rec in records:
            values = rec["values"]
            obj = existing.get(rec["unique_no"])
            if obj is None:
                if rec.get("master_id") is None:
                    stats["skipped_no_master"] += 1
                    continue
                to_create.append(Scheme(bse_unique_no=rec["unique_no"], fund_master_id=rec["master_id"], **values))
                continue
            changes = {f: (getattr(obj, f), v) for f, v in values.items()
                       if getattr(obj, f) != v and not (f == "fund_type" and getattr(obj, f))}
            if not changes:
                stats["unchanged"] += 1
                continue
            for f, (_old, new) in changes.items():
                setattr(obj, f, new)
            obj.updated = now
            to_update.append(obj)
            logger.debug("UPDATE unique_no=%s %s | %s", rec["unique_no"], values["scheme_name"],
                         "; ".join(f"{f}: {o!r} -> {n!r}" for f, (o, n) in changes.items()))

        if to_create:
            Scheme.objects.bulk_create(to_create, batch_size=batch_size)
        if to_update:
            fields = list(records[0]["values"].keys()) + ["updated"] if records else []
            Scheme.objects.bulk_update(to_update, fields, batch_size=batch_size)
        stats["created"] = len(to_create)
        stats["updated"] = len(to_update)