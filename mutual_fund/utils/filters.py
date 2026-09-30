# mutual_fund/api/filters.py
"""
Reusable, data-driven filtering for scheme APIs.

SCHEME_FILTER_MAP declares "request key -> ORM lookup" in one place. Adding a new
filter later means adding one line here, not another `if` branch in the view - and
the frontend never hardcodes filter options because SchemeFilterOptionsAPIView
(views.py) reads its choices from these same models.

Every list-type key accepts EITHER db ids (fund_house, category, sub_category) OR
raw choice values (fund_type, risk_level, ...) - whichever SchemeFilterOptionsAPIView
handed the frontend for that dropdown, the frontend sends straight back here.
"""
from django.db.models import Q

SCHEME_FILTER_MAP = {
    # request key      : ORM lookup
    "fund_type": "fund_type__in",
    "option": "option__in",
    "plans": "plans__in",
    "risk_level": "risk_level__in",
    "fund_house": "fund_master__fund_house_id__in",             # AMC ids
    # ASSUMPTION: FundSubCategory has an FK to a parent "FundCategory" model.
    # Rename `category__category_id` below to match your actual FK field name
    # (e.g. `category__parent_category_id`, `category__main_category_id`, etc).
    "category": "fund_master__category__category_id__in",       # main category ids
    "sub_category": "fund_master__category_id__in",             # sub-category ids (existing FK)
    "nav_closed": "nav_closed",             # boolean - single value, not a list
    "is_sip_allowed": "is_sip_allowed",
    "show_on_site": "show_on_site",
}


def apply_filters(queryset, data, filter_map=None):
    """
    data: request.data, e.g. {"fund_type": ["equity"], "fund_house": [1, 2], "risk_level": ["high"]}
    List-type filters (__in) are applied only for a non-empty list; missing/empty keys
    are silently skipped so an empty body returns everything, unfiltered.
    """
    filter_map = filter_map or SCHEME_FILTER_MAP
    filters = {}
    for key, lookup in filter_map.items():
        if key not in data:
            continue
        value = data.get(key)
        if lookup.endswith("__in"):
            if isinstance(value, (list, tuple)) and value:
                filters[lookup] = value
        elif value is not None:
            filters[lookup] = value
    return queryset.filter(**filters) if filters else queryset


def apply_search(queryset, search_term, fields=("scheme_name", "scheme_code", "amfi_code")):
    """Case-insensitive OR search across the given fields. No-op for a blank/missing term."""
    search_term = (search_term or "").strip()
    if not search_term:
        return queryset
    q = Q()
    for field in fields:
        q |= Q(**{f"{field}__icontains": search_term})
    return queryset.filter(q)