# cas_parser/services/dates.py
"""
Tolerant date parsing for casparser's output.

ASSUMPTION: casparser's JSON output uses ISO "YYYY-MM-DD" for every date field, which
matches its public dataclasses as of recent versions. The two extra formats below are
a safety net for older casparser versions / CDSL-CAS variants that sometimes report
"DD-MMM-YYYY". If you see a real value this still fails on, add its format here - this
is the ONLY place date parsing happens, so there's one place to fix.
"""
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y")


def parse_date(value):
    """Returns a date, or None (never raises) - a single unparseable date in a 10-year
    statement should not fail the whole import."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    value = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    logger.warning("Unparseable CAS date value: %r", value)
    return None
