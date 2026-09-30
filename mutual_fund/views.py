# mutual_fund/api/views.py
import logging

from rest_framework.views import APIView

from mutual_fund.utils.filters import apply_filters, apply_search
from core.pagination import paginate
from core.response import api_response
from mutual_fund.serializers import SchemeListSerializer
from mutual_fund.models import MutualFundAMC, MutualFundNAV, MutualFundsScheme

logger = logging.getLogger(__name__)

# Placeholder until a real "horizon" field/model exists on the scheme/category side.
# Wire this into SCHEME_FILTER_MAP + this list together once that field is added.
HORIZON_CHOICES = [
    {"value": "short", "label": "Short Term (< 1 Year)"},
    {"value": "medium", "label": "Medium Term (1 - 3 Years)"},
    {"value": "long", "label": "Long Term (3+ Years)"},
]


def _choices(model, field_name):
    """Read a field's `choices` straight off the model, so filter options can never
    drift out of sync with FUND_TYPE_CHOICES / SCHEME_RISK_CHOICES etc. in models.py."""
    field = model._meta.get_field(field_name)
    return [{"value": value, "label": label} for value, label in (field.choices or [])]


class NavHistoryAPIView(APIView):
    """
    POST /api/mf/nav-history/
    body: {
        "amfi_code": "119551",        # required
        "from_date": "2023-01-01",    # optional, YYYY-MM-DD
        "to_date": "2024-01-01",      # optional, YYYY-MM-DD
        "order": "asc" | "desc"       # optional, default "asc" (chart-friendly)
    }

    NOT paginated on purpose: a chart needs the full series in one response, not a page
    of it. A scheme has at most ~3,650 rows even over 10 years, so returning everything
    is still fast - the cost that matters here is per-row overhead, not row count, so:
      - .values_list("nav_date", "nav") pulls two columns only, no model instantiation,
        no serializer per row.
      - filtered on scheme_id (resolved once from amfi_code) + nav_date, which the
        existing UniqueConstraint(scheme, nav_date) already indexes - no new index needed.
      - carry-forward (weekend/holiday duplicate) rows are excluded by default.
      - the DB cursor is consumed in one list() call - no extra round trips.
    """

    def post(self, request):
        amfi_code = (request.data.get("amfi_code") or "").strip()
        if not amfi_code:
            return api_response(400, "amfi_code is required")

        try:
            scheme_id = (MutualFundsScheme.objects
                         .filter(amfi_code=amfi_code)
                         .values_list("id", flat=True).first())
        except Exception:  # noqa: BLE001
            logger.exception("scheme lookup failed for amfi_code=%s", amfi_code)
            return api_response(500, "Something went wrong while looking up the scheme")

        if scheme_id is None:
            return api_response(404, f"No scheme found for amfi_code={amfi_code}")

        try:
            qs = MutualFundNAV.objects.filter(scheme_id=scheme_id, is_carry_forward=False)
            from_date, to_date = request.data.get("from_date"), request.data.get("to_date")
            if from_date:
                qs = qs.filter(nav_date__gte=from_date)
            if to_date:
                qs = qs.filter(nav_date__lte=to_date)

            order = "-nav_date" if request.data.get("order") == "desc" else "nav_date"
            rows = list(qs.order_by(order).values_list("nav_date", "nav"))
        except (ValueError, TypeError) as exc:  # bad date format
            return api_response(400, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("nav history query failed for amfi_code=%s", amfi_code)
            return api_response(500, "Something went wrong while fetching NAV history")

        data = {
            "amfi_code": amfi_code,
            "count": len(rows),
            # float, not Decimal/str: smaller payload, and charting libraries consume
            # numbers directly without a parse step.
            "results": [{"date": d, "nav": float(n)} for d, n in rows],
        }
        return api_response(200, "Data fetched successfully", data=data)


class SchemeListAPIView(APIView):
    """
    POST /api/mf/schemes/
    body: {
        "search": "HDFC Flexi",                             # matches scheme_name / scheme_code / amfi_code
        "fund_type": ["equity"],                             # value from filter-options
        "fund_house": [1, 2],                                # AMC ids from filter-options
        "risk_level": ["high"],                              # value from filter-options
        "category": [3], "sub_category": [10, 11],           # ids from filter-options
        "nav_closed": false,
        "page_no": 1, "page_size": 20
    }
    All fields are optional - an empty body returns every scheme, paginated, 20 per page.
    POST (not GET) so multi-select filter arrays don't have to be squeezed into a query string.
    """

    def post(self, request):
        try:
            qs = (MutualFundsScheme.objects
                  .select_related("fund_master", "fund_master__fund_house",
                                  "fund_master__category", "return_stat"))
            qs = apply_search(qs, request.data.get("search"))
            qs = apply_filters(qs, request.data)
            qs = qs.order_by("scheme_name")

            results, pagination = paginate(qs, request.data, serializer_class=SchemeListSerializer,
                                           context={"request": request})
        except (ValueError, TypeError) as exc:               # bad filter id type, bad page_no/page_size
            return api_response(400, str(exc))
        except Exception:                                    # noqa: BLE001
            logger.exception("scheme list query failed")
            return api_response(500, "Something went wrong while fetching schemes")

        return api_response(200, "Data fetched successfully", data=results, pagination=pagination)


class SchemeFilterOptionsAPIView(APIView):
    """
    GET /api/mf/schemes/filter-options/

    Returns the choices the frontend needs to build every filter dropdown dynamically -
    Fund House, Horizon, Risk, and Category (each with its sub-categories nested under
    it) - so the frontend never hardcodes an option list. IDs/values returned here are
    exactly what SchemeListAPIView expects back in its filter fields of the same name.
    """

    def get(self, request):
        from mutual_fund.models import FundCategory, FundSubCategory

        try:
            # <-- CHANGE HERE: "category" must be the actual FK field name on FundSubCategory
            # that points to FundCategory (e.g. sub.category_id / sub.main_category_id / ...).
            sub_qs = (FundSubCategory.objects
                      .select_related("category")
                      .order_by("category__name", "name")
                      .values("id", "name", "category_id"))

            categories = {c.id: {"id": c.id, "name": c.name, "sub_categories": []}
                          for c in FundCategory.objects.order_by("name")}
            for sub in sub_qs:
                if sub["category_id"] in categories:
                    categories[sub["category_id"]]["sub_categories"].append(
                        {"id": sub["id"], "name": sub["name"]})
            category_data = list(categories.values())

            data = {
                "fund_house": list(MutualFundAMC.objects.filter(is_active=True)
                                   .order_by("name").values("id", "name")),
                "horizon": HORIZON_CHOICES,  # placeholder - see note above
                "risk_level": _choices(MutualFundsScheme, "risk_level"),
                "category": category_data,
                # extra, not in the 4 dropdowns but handy for the same screener:
                "fund_type": _choices(MutualFundsScheme, "fund_type"),
                "option": _choices(MutualFundsScheme, "option"),
                "plans": _choices(MutualFundsScheme, "plans"),
            }
        except Exception:  # noqa: BLE001
            logger.exception("filter options query failed")
            return api_response(500, "Something went wrong while fetching filter options")

        return api_response(200, "Data fetched successfully", data=data)