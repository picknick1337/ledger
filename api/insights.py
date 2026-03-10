"""
GET /api/insights?user_id=<uid>&months=6
Aggregated analytics: categories, monthly totals, merchants, cashback opportunities.
Vercel Python runtime — BaseHTTPRequestHandler pattern.
"""
import os
import sys
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_supabase

CARD_RECOMMENDATIONS = {
    "Food & Dining":  [{"card":"Amex Gold","rate":4.0,"note":"4x points at restaurants"},{"card":"Chase Sapphire Reserve","rate":3.0,"note":"3x on dining"}],
    "Travel":         [{"card":"Chase Sapphire Reserve","rate":3.0,"note":"3x on travel"},{"card":"Amex Platinum","rate":5.0,"note":"5x on flights booked direct"}],
    "Shopping":       [{"card":"Amazon Prime Visa","rate":5.0,"note":"5% at Amazon"},{"card":"Citi Double Cash","rate":2.0,"note":"2% on everything"}],
    "Utilities":      [{"card":"Citi Custom Cash","rate":5.0,"note":"5% on top spend category"}],
    "Entertainment":  [{"card":"Capital One Savor","rate":4.0,"note":"4% on entertainment"}],
    "Health":         [{"card":"Citi Double Cash","rate":2.0,"note":"2% on everything"}],
    "Subscriptions":  [{"card":"Apple Card","rate":3.0,"note":"3% on Apple subscriptions"}],
    "Other":          [{"card":"Citi Double Cash","rate":2.0,"note":"2% on everything"}],
}


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed  = urlparse(self.path)
        params  = parse_qs(parsed.query)
        user_id = (params.get("user_id") or [""])[0]
        months  = int((params.get("months") or ["6"])[0])

        if not user_id:
            self._json(400, {"error": "Missing user_id"})
            return

        sb     = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).date().isoformat()

        result = (
            sb.table("transactions").select("*")
            .eq("user_id", user_id).gte("date", cutoff)
            .order("date", desc=True).execute()
        )
        txns = result.data or []

        if not txns:
            self._json(200, {
                "period_months": months, "total_spend": 0, "total_cashback": 0,
                "by_category": [], "by_month": [], "top_merchants": [],
                "opportunities": [], "recent_sync": None, "transaction_count": 0,
            })
            return

        cat_spend = defaultdict(float); cat_cb = defaultdict(float); cat_n = defaultdict(int)
        for t in txns:
            c = t.get("category") or "Other"
            cat_spend[c] += float(t.get("amount") or 0)
            cat_cb[c]    += float(t.get("cashback_earned") or 0)
            cat_n[c]     += 1

        total_spend = sum(cat_spend.values())
        total_cb    = sum(cat_cb.values())

        by_category = sorted([
            {"category": c, "total": round(cat_spend[c],2),
             "pct": round(cat_spend[c]/total_spend*100,1) if total_spend else 0,
             "cashback_earned": round(cat_cb[c],2), "count": cat_n[c]}
            for c in cat_spend
        ], key=lambda x: x["total"], reverse=True)

        month_spend = defaultdict(float); month_cats = defaultdict(lambda: defaultdict(float))
        for t in txns:
            if not t.get("date"): continue
            ym = t["date"][:7]
            c  = t.get("category") or "Other"
            month_spend[ym]      += float(t.get("amount") or 0)
            month_cats[ym][c]    += float(t.get("amount") or 0)

        by_month = sorted([
            {"month": ym,
             "label": datetime.strptime(ym, "%Y-%m").strftime("%b %Y"),
             "total": round(month_spend[ym], 2),
             "breakdown": {k: round(v,2) for k,v in month_cats[ym].items()}}
            for ym in month_spend
        ], key=lambda x: x["month"])

        merch_spend = defaultdict(float); merch_n = defaultdict(int); merch_cat = {}
        for t in txns:
            m = t.get("merchant") or "Unknown"
            merch_spend[m] += float(t.get("amount") or 0)
            merch_n[m]     += 1
            if m not in merch_cat:
                merch_cat[m] = t.get("category") or "Other"

        top_merchants = sorted([
            {"merchant": m, "total": round(merch_spend[m],2), "count": merch_n[m],
             "avg_txn": round(merch_spend[m]/merch_n[m],2), "category": merch_cat[m]}
            for m in merch_spend
        ], key=lambda x: x["total"], reverse=True)[:15]

        opportunities = []
        for cd in by_category:
            cat   = cd["category"]; spend = cd["total"]; cur_cb = cd["cashback_earned"]
            cur_r = (cur_cb / spend * 100) if spend > 0 else 1.0
            recs  = CARD_RECOMMENDATIONS.get(cat, [])
            if not recs: continue
            best  = max(recs, key=lambda r: r["rate"])
            if best["rate"] > cur_r + 0.5:
                gain = round((spend * best["rate"]/100 - cur_cb) / months * 12, 2)
                if gain >= 5:
                    opportunities.append({
                        "category": cat, "current_rate": round(cur_r,1),
                        "best_rate": best["rate"], "card": best["card"], "note": best["note"],
                        "annual_gain": gain,
                        "impact": "high" if gain > 60 else "medium" if gain > 20 else "low",
                    })
        opportunities.sort(key=lambda o: o["annual_gain"], reverse=True)

        sync_r = (
            sb.table("sync_log").select("synced_at,transactions_added,emails_processed")
            .eq("user_id", user_id).eq("status","success")
            .order("synced_at", desc=True).limit(1).execute()
        )
        recent_sync = (sync_r.data or [None])[0]

        self._json(200, {
            "period_months": months, "total_spend": round(total_spend,2),
            "total_cashback": round(total_cb,2), "by_category": by_category,
            "by_month": by_month, "top_merchants": top_merchants,
            "opportunities": opportunities, "recent_sync": recent_sync,
            "transaction_count": len(txns),
        })

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
