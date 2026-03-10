"""
Shared utilities for Ledger API functions.
NOTE: VITE_ prefixed vars are frontend-only. Python functions use plain names.
"""
import os
from typing import Optional
from supabase import create_client, Client


def get_supabase() -> Client:
    """Server-side Supabase client using service role key (bypasses RLS)."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_google_tokens_for_user(user_id: str) -> Optional[dict]:
    """Fetch stored Google OAuth tokens from Supabase for a given user."""
    sb = get_supabase()
    result = sb.table("user_tokens").select("*").eq("user_id", user_id).single().execute()
    return result.data if result.data else None


DEFAULT_CASHBACK_RULES = {
    "Food & Dining":  1.5,
    "Travel":         1.0,
    "Shopping":       1.0,
    "Utilities":      1.0,
    "Entertainment":  1.0,
    "Health":         1.0,
    "Subscriptions":  1.0,
    "Other":          1.0,
}

def get_cashback_rate(user_id: str, category: str) -> float:
    try:
        sb = get_supabase()
        result = (
            sb.table("cashback_rules").select("rate")
            .eq("user_id", user_id).eq("category", category)
            .single().execute()
        )
        if result.data:
            return float(result.data["rate"])
    except Exception:
        pass
    return DEFAULT_CASHBACK_RULES.get(category, 1.0)
