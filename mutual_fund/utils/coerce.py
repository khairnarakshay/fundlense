"""
Type-coercion helpers.

Given a Django model field + a raw API value, return the exact Python type
required by that field. Handles common API quirks:
    "₹1,23,456 Cr"  -> Decimal('123456')  or '123456' for CharField
    "45.67 %"        -> Decimal('45.67')  or '45.67'
    "N/A" / "-" / "" -> None
    "Y" / "N"        -> True / False
"""
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import models as dj_models


# ---------------------------------------------------------------------------
# Text sanitisers
# ---------------------------------------------------------------------------
_STRIP          = re.compile(r"[₹$,\s%]")
_LEADING_UNITS  = re.compile(r"^(?:rs\.?|inr|usd|cr|crore|lakh|lac|bn|mn|k)\s*", re.I)
_TRAILING_UNITS = re.compile(r"\s*(?:cr|crore|lakh|lac|bn|mn|k|%|yrs?|years?|days?)$", re.I)
_NUMBER_RE      = re.compile(r"^-?\d+(?:\.\d+)?$")

_EMPTY = (None, "", "-", "N/A", "NA", "null", "None", "nan")


def _clean_number_string(raw: str) -> str:
    s = str(raw).strip()
    s = _LEADING_UNITS.sub("", s)
    s = _TRAILING_UNITS.sub("", s)
    s = _STRIP.sub("", s)
    return s


def _to_decimal(value):
    if value in _EMPTY:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    s = _clean_number_string(value)
    if not _NUMBER_RE.match(s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _is_numeric_text(value) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_NUMBER_RE.match(_clean_number_string(value)))


def _normalise_numeric_string(value: str) -> str:
    d = _to_decimal(value)
    if d is None:
        return value
    # 45.670 → "45.67" ;  100.00 → "100"
    return format(d.normalize(), "f")


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------
def coerce_for_field(field, value, *, log=None):
    """
    Convert `value` to a Python type compatible with Django `field`.
    Returns None when the value is empty or cannot be coerced.
    """
    if value in _EMPTY:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    # -------- DecimalField -------------------------------------------------
    if isinstance(field, dj_models.DecimalField):
        d = _to_decimal(value)
        if d is None:
            if log:
                log(f"  decimal-coercion failed for {field.name!r}: {value!r}")
            return None
        q = Decimal(1).scaleb(-field.decimal_places)
        try:
            return d.quantize(q)
        except InvalidOperation:
            return d

    # -------- Integer fields ----------------------------------------------
    if isinstance(
        field,
        (
            dj_models.IntegerField,
            dj_models.BigIntegerField,
            dj_models.SmallIntegerField,
            dj_models.PositiveIntegerField,
            dj_models.PositiveSmallIntegerField,
            dj_models.PositiveBigIntegerField,
        ),
    ):
        d = _to_decimal(value)
        if d is None:
            if log:
                log(f"  int-coercion failed for {field.name!r}: {value!r}")
            return None
        try:
            return int(d)
        except (TypeError, ValueError):
            return None

    # -------- FloatField ---------------------------------------------------
    if isinstance(field, dj_models.FloatField):
        d = _to_decimal(value)
        return float(d) if d is not None else None

    # -------- BooleanField -------------------------------------------------
    if isinstance(field, dj_models.BooleanField):
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in {"true", "1", "y", "yes", "t"}:
            return True
        if s in {"false", "0", "n", "no", "f"}:
            return False
        return None

    # -------- JSONField ----------------------------------------------------
    if isinstance(field, dj_models.JSONField):
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return value
        return value

    # -------- DateField / DateTimeField ------------------------------------
    if isinstance(field, dj_models.DateTimeField):
        return _to_datetime(value)
    if isinstance(field, dj_models.DateField):
        dt = _to_datetime(value)
        return dt.date() if dt else None

    # -------- TimeField ----------------------------------------------------
    if isinstance(field, dj_models.TimeField):
        return _to_time(value)

    # -------- CharField / TextField ----------------------------------------
    if isinstance(field, (dj_models.CharField, dj_models.TextField)):
        s = value if isinstance(value, str) else str(value)
        s = s.strip()
        if not s:
            return None
        # Force numeric strings to be clean numeric text
        if _is_numeric_text(s):
            return _normalise_numeric_string(s)
        return s

    return value


# ---------------------------------------------------------------------------
# Date/Time parsers
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y",
    "%b %d %Y", "%b %d, %Y", "%d %b %Y", "%Y/%m/%d",
)
_TIME_FORMATS = ("%H:%M:%S", "%H:%M")


def _to_datetime(value):
    if value in _EMPTY:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_time(value):
    if value in _EMPTY:
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value
    s = str(value).strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Dict-level helper
# ---------------------------------------------------------------------------
def coerce_dict_for_model(model_cls, raw: dict, *, log=None) -> dict:
    """
    Given {field_name: raw_value}, return {field_name: coerced_value}
    using the model's own field definitions. Keys that don't map to a
    model field are silently dropped.
    """
    out = {}
    for fname, value in raw.items():
        try:
            field = model_cls._meta.get_field(fname)
        except Exception:
            continue
        coerced = coerce_for_field(field, value, log=log)
        if coerced is not None:
            out[fname] = coerced
    return out


# ---------------------------------------------------------------------------
# SQL cast suffix (used by bulk CASE-WHEN updates)
# ---------------------------------------------------------------------------
def sql_cast_for_field(field) -> str:
    if isinstance(field, dj_models.JSONField):
        return "::jsonb"
    if isinstance(field, dj_models.DecimalField):
        return "::numeric"
    if isinstance(field, dj_models.BooleanField):
        return "::boolean"
    if isinstance(field, dj_models.DateTimeField):
        return "::timestamptz"
    if isinstance(field, dj_models.DateField):
        return "::date"
    if isinstance(field, dj_models.TimeField):
        return "::time"
    if isinstance(
        field,
        (
            dj_models.IntegerField,
            dj_models.BigIntegerField,
            dj_models.SmallIntegerField,
            dj_models.PositiveIntegerField,
            dj_models.PositiveSmallIntegerField,
        ),
    ):
        return "::bigint"
    return ""