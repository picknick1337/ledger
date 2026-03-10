"""
GET /api/auth/callback?code=<code>&state=<user_id>
Exchanges the Google auth code for tokens, stores in Supabase, redirects to dashboard.
"""
import os
import sys
import json
import httpx
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from _utils import get_supabase


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed  = urlparse(self.path)
        params  = parse_qs(parsed.query)
        app_url = os.environ.get("APP_URL", "http://localhost:5173")

        code  = (params.get("code")  or [""])[0]
        state = (params.get("state") or [""])[0]   # user_id
        error = (params.get("error") or [""])[0]

        if error:
            self._redirect(f"{app_url}?error=google_denied")
            return

        if not code or not state:
            self._redirect(f"{app_url}?error=missing_params")
            return

        # ── 1. Exchange code for tokens ───────────────────────────────────
        try:
            token_resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code":          code,
                    "client_id":     os.environ["GOOGLE_CLIENT_ID"],
                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                    "redirect_uri":  os.environ["GOOGLE_REDIRECT_URI"],
                    "grant_type":    "authorization_code",
                },
                timeout=10,
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
        except Exception as e:
            self._redirect(f"{app_url}?error=token_exchange_failed&detail={str(e)[:100]}")
            return

        # ── 2. Upsert tokens into Supabase ────────────────────────────────
        try:
            sb = get_supabase()
            sb.table("user_tokens").upsert({
                "user_id":       state,
                "access_token":  tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_at":    tokens.get("expires_in", 3600),
                "scope":         tokens.get("scope", ""),
                "updated_at":    datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as e:
            # Pass the real error back so it shows in the URL for debugging
            detail = str(e)[:120]
            self._redirect(f"{app_url}?error=token_storage_failed&detail={detail}")
            return

        self._redirect(f"{app_url}?gmail_connected=true&user_id={state}")

    def _redirect(self, url: str):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def log_message(self, *args):
        pass
