"""
GET /api/insights?user_id=<uid>&months=6
Returns aggregated analytics:
  - spending by category
  - monthly totals
  - top merchants
  - cashback summary
  - optimization opportunities
"""
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from api._utils import get_supabase, json_response, error_response


# ── Cashback optimization rules ────────────────────────────────────────────
# Maps category → list of card recommendations
CARD_RECOMMENDATIONS = {
    "Food & Dining": [
        {"card": "Amex Gold", "rate": 4.0, "note": "4x points at restaurants"},
        {"card": "Chase Sapphire Reserve", "rate": 3.0, "note": "3x on dining"},
    ],
    "Travel": [
        {"card": "Chase Sapphire Reserve", "rate": 3.0, "note": "3x on travel"},
        {"card": "Amex Platinum", "rate": 5.0, "note": "5x on flights booked direct"},
    ],
    "Shopping": [
        {"card": "Amazon Prime Visa", "rate": 5.0, "note": "5% at Amazon"},
        {"card": "Citi Double Cash", "rate": 2.0, "note": "2% on everything"},
    ],
    "Utilities": [
        {"card": "Citi Custom Cash", "rate": 5.0, "note": "5% on top spend category"},
    ],
    "Entertainment": [
        {"card": "Capital One Savor", "rate": 4.0, "note": "4% on entertainment"},
    ],
    "Health": [
        {"card": "Citi Double Cash", "rate": 2.0, "note": "2% on everything"},
    ],
    "Subscriptions": [
        {"card": "Apple Card", "rate": 3.0, "note": "3% on Apple subscriptions"},
        {"card": "Citi Double Cash", "rate": 2.0, "note": "2% on everything"},
    ],
    "Other": [
        {"card": "Citi Double Cash", "rate": 2.0, "note": "2% on everything"},
    ],
}


def handler(request, response):
    user_id = request.args.get("user_id")
    months  = int(request.args.get("months", 6))

    if not user_id:
        return error_response("Missing user_id", 400)

    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).date().isoformat()

    # ── Fetch transactions ─────────────────────────────────────────────────
    result = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .gte("date", cutoff)
        .order("date", desc=True)
        .execute()
    )
    txns = result.data or []

    if not txns:
        return json_response({
            "period_months":     months,
            "total_spend":       0,
            "total_cashback":    0,
            "by_category":       [],
            "by_month":          [],
            "top_merchants":     [],
            "opportunities":     [],
            "recent_sync":       None,
        })

    # ── Aggregate by category ──────────────────────────────────────────────
    cat_spend    = defaultdict(float)
    cat_cashback = defaultdict(float)
    cat_count    = defaultdict(int)

    for t in txns:
        cat = t.get("category") or "Other"
        amt = float(t.get("amount") or 0)
        cb  = float(t.get("cashback_earned") or 0)
        cat_spend[cat]    += amt
        cat_cashback[cat] += cb
        cat_count[cat]    += 1

    total_spend    = sum(cat_spend.values())
    total_cashback = sum(cat_cashback.values())

    by_category = sorted([
        {
            "category":        cat,
            "total":           round(cat_spend[cat], 2),
            "pct":             round(cat_spend[cat] / total_spend * 100, 1) if total_spend else 0,
            "cashback_earned": round(cat_cashback[cat], 2),
            "count":           cat_count[cat],
        }
        for cat in cat_spend
    ], key=lambda x: x["total"], reverse=True)

    # ── Aggregate by month ─────────────────────────────────────────────────
    month_spend = defaultdict(float)
    month_cats  = defaultdict(lambda: defaultdict(float))

    for t in txns:
        if not t.get("date"):
            continue
        ym  = t["date"][:7]   # "YYYY-MM"
        cat = t.get("category") or "Other"
        amt = float(t.get("amount") or 0)
        month_spend[ym]         += amt
        month_cats[ym][cat]     += amt

    by_month = sorted([
        {
            "month":      ym,
            "label":      datetime.strptime(ym, "%Y-%m").strftime("%b %Y"),
            "total":      round(month_spend[ym], 2),
            "breakdown":  {k: round(v, 2) for k, v in month_cats[ym].items()},
        }
        for ym in month_spend
    ], key=lambda x: x["month"])

    # ── Top merchants ──────────────────────────────────────────────────────
    merch_spend = defaultdict(float)
    merch_count = defaultdict(int)
    merch_cat   = {}

    for t in txns:
        m = t.get("merchant") or "Unknown"
        merch_spend[m] += float(t.get("amount") or 0)
        merch_count[m] += 1
        if m not in merch_cat:
            merch_cat[m] = t.get("category") or "Other"

    top_merchants = sorted([
        {
            "merchant":  m,
            "total":     round(merch_spend[m], 2),
            "count":     merch_count[m],
            "avg_txn":   round(merch_spend[m] / merch_count[m], 2),
            "category":  merch_cat[m],
        }
        for m in merch_spend
    ], key=lambda x: x["total"], reverse=True)[:15]

    # ── Cashback optimization opportunities ────────────────────────────────
    opportunities = []

    for cat_data in by_category:
        cat          = cat_data["category"]
        spend        = cat_data["total"]
        current_cb   = cat_data["cashback_earned"]
        current_rate = (current_cb / spend * 100) if spend > 0 else 1.0
        recs         = CARD_RECOMMENDATIONS.get(cat, [])

        if not recs:
            continue

        best = max(recs, key=lambda r: r["rate"])
        if best["rate"] > current_rate + 0.5:   # only flag meaningful gaps
            potential_cb  = spend * best["rate"] / 100
            annual_gain   = round((potential_cb - current_cb) / months * 12, 2)
            if annual_gain >= 5:                 # skip trivial gains
                opportunities.append({
                    "category":      cat,
                    "current_rate":  round(current_rate, 1),
                    "best_rate":     best["rate"],
                    "card":          best["card"],
                    "note":          best["note"],
                    "annual_gain":   annual_gain,
                    "impact":        "high" if annual_gain > 60 else "medium" if annual_gain > 20 else "low",
                })

    opportunities.sort(key=lambda o: o["annual_gain"], reverse=True)

    # ── Last sync time ─────────────────────────────────────────────────────
    sync_result = (
        sb.table("sync_log")
        .select("synced_at, transactions_added, emails_processed")
        .eq("user_id", user_id)
        .eq("status", "success")
        .order("synced_at", desc=True)
        .limit(1)
        .execute()
    )
    recent_sync = (sync_result.data or [None])[0]

    return json_response({
        "period_months":  months,
        "total_spend":    round(total_spend, 2),
        "total_cashback": round(total_cashback, 2),
        "by_category":    by_category,
        "by_month":       by_month,
        "top_merchants":  top_merchants,
        "opportunities":  opportunities,
        "recent_sync":    recent_sync,
        "transaction_count": len(txns),
    })
