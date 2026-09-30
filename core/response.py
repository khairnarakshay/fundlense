# mutual_fund/api/response.py
"""
One envelope for every API in this app:
    {"st": 200, "msg": "...", "data": {...}, "pagination": {...}}

"pagination" is included only when the caller passes one (list endpoints); a detail /
filter-options endpoint just omits it.
"""
from rest_framework.response import Response


def api_response(st, msg, data=None, pagination=None):
    body = {"st": st, "msg": msg, "data": data if data is not None else {}}
    if pagination is not None:
        body["pagination"] = pagination
    return Response(body, status=st)