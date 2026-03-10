"""
Shared utilities for Ledger API functions.
Handles Supabase client, Google OAuth, response helpers.
"""
import os
import json
from typing import Any, Optional
from supabase import create_client, Client


# ── Supabase ───────────────────────────────────────────────────────────────

def get_supabase() -> Client:
    """Return a Supabase client using the service role key (server-side only)."""
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_supabase_anon() -> Client:
    """Return a Supabase client using the anon key (for user-scoped operations)."""
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    key = os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
    return create_client(url, key)


# ── Auth helpers ───────────────────────────────────────────────────────────

def get_user_id_from_request(headers: dict) -> Optional[str]:
    """
    Extract and verify the Supabase JWT from the Authorization header.
    Returns the user_id (sub claim) or None if invalid.
    """
    auth_header = headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    try:
        from jose import jwt
        secret = os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
        # Supabase JWTs are HS256 signed with the anon key
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


def get_google_tokens_for_user(user_id: str) -> Optional[dict]:
    """Fetch stored Google OAuth tokens from Supabase for a given user."""
    sb = get_supabase()
    result = sb.table("user_tokens").select("*").eq("user_id", user_id).single().execute()
    if result.data:
        return result.data
    return None


# ── HTTP response helpers ──────────────────────────────────────────────────

def json_response(data: Any, status: int = 200) -> dict:
    """Return a Vercel-compatible response dict."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get("APP_URL", "*"),
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        },
        "body": json.dumps(data),
    }


def error_response(message: str, status: int = 400) -> dict:
    return json_response({"error": message}, status)


def redirect_response(url: str) -> dict:
    return {
        "statusCode": 302,
        "headers": {"Location": url},
        "body": "",
    }


# ── Category rules ─────────────────────────────────────────────────────────

DEFAULT_CASHBACK_RULES = {
    "Food & Dining":    1.5,
    "Travel":           1.0,
    "Shopping":         1.0,
    "Utilities":        1.0,
    "Entertainment":    1.0,
    "Health":           1.0,
    "Subscriptions":    1.0,
    "Other":            1.0,
}

def get_cashback_rate(user_id: str, category: str) -> float:
    """Look up the cashback rate for a category, falling back to defaults."""
    try:
        sb = get_supabase()
        result = (
            sb.table("cashback_rules")
            .select("rate")
            .eq("user_id", user_id)
            .eq("category", category)
            .single()
            .execute()
        )
        if result.data:
            return float(result.data["rate"])
    except Exception:
        pass
    return DEFAULT_CASHBACK_RULES.get(category, 1.0)
