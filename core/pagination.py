# mutual_fund/api/pagination.py
"""
Reusable pagination for every list API in this app.

Works on a Django QuerySet (model instances OR .values()/.values_list() rows) or a
plain Python list, so the same function powers the scheme-list API and the NAV-history
API without either view re-implementing count/page math.
"""
from django.core.paginator import EmptyPage, Paginator

ALLOWED_PAGE_SIZES = (10, 20, 50, 100)
DEFAULT_PAGE_SIZE = 20


def get_pagination_params(data):
    """
    data: request.query_params (GET) or request.data (POST) - anything dict-like.
    page_size is snapped to the nearest ALLOWED_PAGE_SIZES value so a client can't
    request page_size=100000 and force the DB to return everything at once.
    """
    try:
        page_no = int(data.get("page_no", data.get("page", 1)))
    except (TypeError, ValueError):
        page_no = 1
    try:
        page_size = int(data.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    if page_size not in ALLOWED_PAGE_SIZES:
        page_size = min(ALLOWED_PAGE_SIZES, key=lambda allowed: abs(allowed - page_size))
    return max(page_no, 1), page_size


def paginate(queryset, data, serializer_class=None, context=None):
    """
    Returns: (results, pagination_dict)
        pagination_dict = {"page_no": .., "per_page": .., "total_page": .., "total": ..}

    serializer_class:
      - pass a ModelSerializer when `queryset` holds model instances (scheme list API)
      - leave as None when `queryset` is already .values_list()/.values() rows - faster,
        because DRF never has to build a model instance per row (NAV history API)
    """
    page_no, page_size = get_pagination_params(data)
    paginator = Paginator(queryset, page_size)

    if paginator.count == 0:
        items = []
    else:
        try:
            page_obj = paginator.page(page_no)
        except EmptyPage:
            # Past the last page -> empty result instead of a 404/500. Simpler for
            # frontend infinite-scroll / chart chunk-loaders that don't pre-check total_page.
            items = []
        else:
            items = list(page_obj.object_list)

    if serializer_class is not None:
        items = serializer_class(items, many=True, context=context or {}).data

    pagination = {
        "page_no": page_no,
        "per_page": page_size,
        "total_page": paginator.num_pages,
        "total": paginator.count,
    }
    return items, pagination