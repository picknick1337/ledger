"""
GET /api/auth/callback
Exchanges the Google authorization code for access + refresh tokens,
stores them in Supabase, then redirects to the dashboard.
"""
import os
import httpx
from datetime import datetime, timezone
from api._utils import get_supabase, redirect_response, error_response


def handler(request, response):
    code  = request.args.get("code")
    state = request.args.get("state")   # contains user_id set during login
    error = request.args.get("error")

    app_url = os.environ.get("APP_URL", "http://localhost:3000")

    if error:
        return redirect_response(f"{app_url}?error=google_denied")

    if not code or not state:
        return error_response("Missing code or state", 400)

    user_id = state

    # ── Exchange code for tokens ───────────────────────────────────────────
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
        return redirect_response(f"{app_url}?error=token_exchange_failed")

    # ── Upsert tokens into Supabase ────────────────────────────────────────
    # We store access_token, refresh_token, and expiry so we can refresh later.
    try:
        sb = get_supabase()
        sb.table("user_tokens").upsert({
            "user_id":      user_id,
            "access_token":  tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),   # only present on first auth
            "expires_at":    tokens.get("expires_in", 3600),
            "scope":         tokens.get("scope", ""),
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id").execute()
    except Exception as e:
        return redirect_response(f"{app_url}?error=token_storage_failed")

    # Redirect to dashboard with success flag so the UI can trigger first sync
    return redirect_response(f"{app_url}?gmail_connected=true&user_id={user_id}")
