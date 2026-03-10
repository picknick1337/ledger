"""
GET /api/transactions?user_id=<uid>&limit=50&offset=0&category=Food&month=2025-01
Vercel Python runtime — BaseHTTPRequestHandler pattern.
"""
import os
import sys
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_supabase


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed   = urlparse(self.path)
        params   = parse_qs(parsed.query)
        user_id  = (params.get("user_id")  or [""])[0]
        limit    = min(int((params.get("limit")    or ["50"])[0]), 200)
        offset   = int((params.get("offset")   or ["0"])[0])
        category = (params.get("category") or [""])[0]
        month    = (params.get("month")    or [""])[0]

        if not user_id:
            self._json(400, {"error": "Missing user_id"})
            return

        sb    = get_supabase()
        query = (
            sb.table("transactions").select("*")
            .eq("user_id", user_id)
            .order("date", desc=True)
            .range(offset, offset + limit - 1)
        )
        if category:
            query = query.eq("category", category)
        if month:
            query = query.gte("date", f"{month}-01").lte("date", f"{month}-31")

        result = query.execute()
        self._json(200, {
            "transactions": result.data or [],
            "count":  len(result.data or []),
            "offset": offset,
            "limit":  limit,
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
