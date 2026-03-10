"""
GET /api/transactions?user_id=<uid>&limit=50&offset=0&category=Food&month=2025-01
Returns paginated transactions from Supabase.
"""
from api._utils import get_supabase, json_response, error_response


def handler(request, response):
    user_id  = request.args.get("user_id")
    limit    = min(int(request.args.get("limit", 50)), 200)
    offset   = int(request.args.get("offset", 0))
    category = request.args.get("category")     # optional filter
    month    = request.args.get("month")         # "YYYY-MM" optional filter

    if not user_id:
        return error_response("Missing user_id", 400)

    sb = get_supabase()

    query = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("date", desc=True)
        .range(offset, offset + limit - 1)
    )

    if category:
        query = query.eq("category", category)

    if month:
        # month = "YYYY-MM"  →  filter date between YYYY-MM-01 and YYYY-MM-31
        query = query.gte("date", f"{month}-01").lte("date", f"{month}-31")

    result = query.execute()

    return json_response({
        "transactions": result.data or [],
        "count":        len(result.data or []),
        "offset":       offset,
        "limit":        limit,
    })
