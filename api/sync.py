"""
POST /api/sync
Main sync pipeline:
  1. Refresh Google access token if needed
  2. Search Gmail for transaction emails (last 90 days)
  3. For each new email → send to Claude for structured parsing
  4. Upsert parsed transactions into Supabase
  5. Write a sync_log entry

Body: { "user_id": "<supabase_user_id>" }
"""
import os
import json
import base64
import httpx
import anthropic
from datetime import datetime, timezone, timedelta
from email import message_from_bytes
from html.parser import HTMLParser

from api._utils import (
    get_supabase,
    get_google_tokens_for_user,
    get_cashback_rate,
    json_response,
    error_response,
)


# ── HTML stripper ──────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(p.strip() for p in self._parts if p.strip())


def strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()[:4000]   # cap at 4k chars for Claude


# ── Google token refresh ───────────────────────────────────────────────────

def refresh_access_token(refresh_token: str) -> str:
    """Exchange a refresh token for a new access token."""
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ── Gmail helpers ──────────────────────────────────────────────────────────

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"

# Search query — catches most bank/card transaction notification emails
GMAIL_QUERY = (
    "subject:(transaction OR charge OR purchase OR payment OR receipt OR "
    "\"you spent\" OR \"your purchase\" OR \"order confirmation\") "
    "newer_than:90d"
)

def gmail_get(path: str, access_token: str, params: dict = None) -> dict:
    resp = httpx.get(
        f"{GMAIL_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_email_body(msg_data: dict) -> tuple[str, str]:
    """
    Extract (subject, plain_text_body) from a full Gmail message resource.
    Falls back to snippet if no body parts found.
    """
    payload = msg_data.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = headers.get("Subject", "")

    def decode_part(part: dict) -> str:
        data = part.get("body", {}).get("data", "")
        if not data:
            return ""
        decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if part.get("mimeType") == "text/html":
            return strip_html(decoded)
        return decoded[:4000]

    def extract_parts(part: dict) -> str:
        mime = part.get("mimeType", "")
        if mime in ("text/plain", "text/html"):
            return decode_part(part)
        for sub in part.get("parts", []):
            result = extract_parts(sub)
            if result:
                return result
        return ""

    body = extract_parts(payload) or msg_data.get("snippet", "")
    return subject, body


# ── Claude parser ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a financial data extraction assistant.
Given an email subject and body, extract credit card transaction details.
Return ONLY a JSON object with these exact keys:
{
  "is_transaction": true/false,
  "merchant": "string or null",
  "amount": number or null,
  "currency": "USD" (or ISO code),
  "date": "YYYY-MM-DD" or null,
  "category": one of ["Food & Dining","Travel","Shopping","Utilities","Entertainment","Health","Subscriptions","Other"] or null
}
If the email is NOT a transaction notification, set is_transaction to false and all other fields to null.
Do not include any explanation, markdown, or extra text — only the JSON object."""


def parse_email_with_claude(subject: str, body: str) -> dict | None:
    """
    Send email content to Claude and get back a structured transaction dict.
    Returns None if Claude can't parse it or it's not a transaction.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Subject: {subject}\n\nBody:\n{body}"
        }],
    )

    raw = message.content[0].text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    if not data.get("is_transaction"):
        return None
    return data


# ── Main handler ───────────────────────────────────────────────────────────

def handler(request, response):
    if request.method == "OPTIONS":
        return json_response({})

    try:
        body = request.get_json(force=True) or {}
        user_id = body.get("user_id")
        if not user_id:
            return error_response("Missing user_id", 400)
    except Exception:
        return error_response("Invalid request body", 400)

    sb = get_supabase()
    sync_start = datetime.now(timezone.utc)
    emails_processed = 0
    transactions_added = 0

    try:
        # ── 1. Get Google tokens ───────────────────────────────────────────
        token_row = get_google_tokens_for_user(user_id)
        if not token_row:
            return error_response("Gmail not connected. Please authenticate first.", 401)

        access_token = refresh_access_token(token_row["refresh_token"])

        # Update stored access token
        sb.table("user_tokens").update({
            "access_token": access_token,
            "updated_at": sync_start.isoformat(),
        }).eq("user_id", user_id).execute()

        # ── 2. Fetch existing message IDs to avoid re-processing ──────────
        existing = sb.table("transactions").select("gmail_message_id").eq("user_id", user_id).execute()
        seen_ids = {row["gmail_message_id"] for row in (existing.data or [])}

        # ── 3. Search Gmail ────────────────────────────────────────────────
        search_result = gmail_get(
            "/users/me/messages",
            access_token,
            params={"q": GMAIL_QUERY, "maxResults": 100},
        )
        messages = search_result.get("messages", [])

        # ── 4. Process each email ──────────────────────────────────────────
        new_transactions = []

        for msg_stub in messages:
            msg_id = msg_stub["id"]
            if msg_id in seen_ids:
                continue

            try:
                msg_data = gmail_get(f"/users/me/messages/{msg_id}", access_token,
                                     params={"format": "full"})
                subject, body_text = get_email_body(msg_data)
                emails_processed += 1

                parsed = parse_email_with_claude(subject, body_text)
                if not parsed:
                    continue

                category = parsed.get("category") or "Other"
                amount   = parsed.get("amount")
                cashback_rate   = get_cashback_rate(user_id, category)
                cashback_earned = round((amount or 0) * cashback_rate / 100, 2)

                new_transactions.append({
                    "user_id":           user_id,
                    "gmail_message_id":  msg_id,
                    "merchant":          parsed.get("merchant"),
                    "amount":            amount,
                    "currency":          parsed.get("currency", "USD"),
                    "date":              parsed.get("date"),
                    "category":          category,
                    "cashback_rate":     cashback_rate,
                    "cashback_earned":   cashback_earned,
                    "raw_subject":       subject[:255],
                    "raw_snippet":       msg_data.get("snippet", "")[:500],
                })

            except Exception as parse_err:
                # Don't fail the whole sync for one bad email
                continue

        # ── 5. Batch upsert to Supabase ────────────────────────────────────
        if new_transactions:
            sb.table("transactions").upsert(
                new_transactions,
                on_conflict="gmail_message_id"
            ).execute()
            transactions_added = len(new_transactions)

        # ── 6. Write sync log ──────────────────────────────────────────────
        sb.table("sync_log").insert({
            "user_id":             user_id,
            "synced_at":           sync_start.isoformat(),
            "emails_processed":    emails_processed,
            "transactions_added":  transactions_added,
            "status":              "success",
        }).execute()

        return json_response({
            "ok":                  True,
            "emails_processed":    emails_processed,
            "transactions_added":  transactions_added,
            "synced_at":           sync_start.isoformat(),
        })

    except Exception as e:
        # Write failed sync log
        try:
            sb.table("sync_log").insert({
                "user_id": user_id,
                "synced_at": sync_start.isoformat(),
                "emails_processed": emails_processed,
                "transactions_added": 0,
                "status": "error",
                "error": str(e)[:500],
            }).execute()
        except Exception:
            pass

        return error_response(f"Sync failed: {str(e)}", 500)
