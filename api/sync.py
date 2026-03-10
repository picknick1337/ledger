"""
POST /api/sync
Gmail fetch -> Claude parsing -> Supabase upsert.
Tuned for ICICI Bank credit card email formats:
  1. "Rs.803.00 debited via Credit Card **2137"
  2. "Transaction alert for your ICICI Bank Credit Card"
  3. "INR 1372.83 spent on credit card no. XX6714"
"""
import os
import sys
import json
import base64
import httpx
import anthropic
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_supabase, get_google_tokens_for_user, get_cashback_rate

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"

# Targets all three ICICI subject patterns plus generic fallbacks.
# newer_than:62d  ≈ 2 months.
GMAIL_QUERY = (
    "newer_than:62d ("
    "subject:(debited OR spent OR \"transaction alert\" OR \"credit card\" OR "
    "\"Transaction alert\" OR \"amount\" OR \"INR\" OR \"Rs.\") "
    "OR from:(icicibank.com OR hdfcbank.com OR axisbank.com OR sbicard.com "
    "OR kotak.com OR yesbank.in OR sc.com)"
    ")"
)

SYSTEM_PROMPT = """You are a financial data extraction assistant specialising in Indian bank credit card alert emails.

Common subject line formats you will see:
- "Rs.803.00 debited via Credit Card **2137"
- "Transaction alert for your ICICI Bank Credit Card"
- "INR 1372.83 spent on credit card no. XX6714"

Given an email subject and body, extract the transaction details.
Return ONLY a valid JSON object with exactly these keys — no markdown, no explanation:
{
  "is_transaction": true or false,
  "merchant": "merchant name string, or null if not found",
  "amount": numeric value only (no currency symbols), or null,
  "currency": "INR" (default for Indian cards, or the ISO code if different),
  "date": "YYYY-MM-DD" or null,
  "category": one of ["Food & Dining","Travel","Shopping","Utilities","Entertainment","Health","Subscriptions","Other"] or null
}

Rules:
- Set is_transaction to false for OTP emails, statements, offers, or any non-transaction email.
- Extract amount from subject line if present (e.g. "Rs.803.00", "INR 1372.83").
- Merchant is usually in the email body — look for "at <merchant>", "to <merchant>", or similar.
- If you cannot determine the merchant from subject or body, set it to null.
- Never include currency symbols in the amount field."""


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(p.strip() for p in self._parts if p.strip())[:5000]


def strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


def refresh_access_token(refresh_token: str) -> str:
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


def gmail_get(path, access_token, params=None):
    resp = httpx.get(
        f"{GMAIL_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_email_body(msg_data):
    """Return (subject, body_text) from a full Gmail message resource."""
    payload = msg_data.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = headers.get("Subject", "")

    def decode_part(part):
        data = part.get("body", {}).get("data", "")
        if not data:
            return ""
        decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        return strip_html(decoded) if part.get("mimeType") == "text/html" else decoded[:5000]

    def extract(part):
        mime = part.get("mimeType", "")
        # Prefer plain text; fall back to HTML
        if mime == "text/plain":
            return decode_part(part)
        if mime == "text/html":
            return decode_part(part)
        for sub in part.get("parts", []):
            r = extract(sub)
            if r:
                return r
        return ""

    body = extract(payload) or msg_data.get("snippet", "")
    return subject, body


def fetch_all_message_ids(access_token: str) -> list[str]:
    """
    Page through Gmail search results to collect all matching message IDs.
    Gmail returns max 500/page; we handle pagination automatically.
    """
    ids        = []
    page_token = None
    while True:
        params = {"q": GMAIL_QUERY, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        data       = gmail_get("/users/me/messages", access_token, params)
        ids       += [m["id"] for m in data.get("messages", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids


def parse_with_claude(subject: str, body: str) -> dict | None:
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Subject: {subject}\n\nBody:\n{body[:3000]}"
        }],
    )
    raw = message.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if data.get("is_transaction") else None


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors(200)

    def do_POST(self):
        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            body    = json.loads(raw_body)
            user_id = body.get("user_id")
        except Exception:
            self._json(400, {"error": "Invalid JSON"})
            return

        if not user_id:
            self._json(400, {"error": "Missing user_id"})
            return

        sb         = get_supabase()
        sync_start = datetime.now(timezone.utc)
        processed  = 0
        added      = 0

        try:
            # ── 1. Get & refresh Google tokens ────────────────────────────
            token_row = get_google_tokens_for_user(user_id)
            if not token_row:
                self._json(401, {"error": "Gmail not connected"})
                return

            access_token = refresh_access_token(token_row["refresh_token"])
            sb.table("user_tokens").update({
                "access_token": access_token,
                "updated_at":   sync_start.isoformat(),
            }).eq("user_id", user_id).execute()

            # ── 2. Load already-seen message IDs ──────────────────────────
            existing = (
                sb.table("transactions")
                .select("gmail_message_id")
                .eq("user_id", user_id)
                .execute()
            )
            seen = {r["gmail_message_id"] for r in (existing.data or [])}

            # ── 3. Fetch all matching message IDs (paginated) ─────────────
            all_ids  = fetch_all_message_ids(access_token)
            new_ids  = [mid for mid in all_ids if mid not in seen]
            new_txns = []

            # ── 4. Parse each new email via Claude ────────────────────────
            for mid in new_ids:
                try:
                    msg_data        = gmail_get(f"/users/me/messages/{mid}", access_token, {"format": "full"})
                    subject, body_t = get_email_body(msg_data)
                    processed      += 1

                    parsed = parse_with_claude(subject, body_t)
                    if not parsed:
                        continue

                    cat     = parsed.get("category") or "Other"
                    amount  = parsed.get("amount")
                    currency = parsed.get("currency") or "INR"
                    cb_rate = get_cashback_rate(user_id, cat)
                    cb_earn = round((amount or 0) * cb_rate / 100, 2)

                    new_txns.append({
                        "user_id":          user_id,
                        "gmail_message_id": mid,
                        "merchant":         parsed.get("merchant"),
                        "amount":           amount,
                        "currency":         currency,
                        "date":             parsed.get("date"),
                        "category":         cat,
                        "cashback_rate":    cb_rate,
                        "cashback_earned":  cb_earn,
                        "raw_subject":      subject[:255],
                        "raw_snippet":      msg_data.get("snippet", "")[:500],
                    })
                except Exception:
                    # Don't abort the whole sync for one bad email
                    continue

            # ── 5. Batch upsert ───────────────────────────────────────────
            if new_txns:
                sb.table("transactions").upsert(
                    new_txns, on_conflict="gmail_message_id"
                ).execute()
                added = len(new_txns)

            # ── 6. Write sync log ─────────────────────────────────────────
            sb.table("sync_log").insert({
                "user_id":            user_id,
                "synced_at":          sync_start.isoformat(),
                "emails_processed":   processed,
                "transactions_added": added,
                "status":             "success",
            }).execute()

            self._json(200, {
                "ok":                 True,
                "emails_found":       len(all_ids),
                "emails_processed":   processed,
                "transactions_added": added,
            })

        except Exception as e:
            try:
                sb.table("sync_log").insert({
                    "user_id": user_id, "synced_at": sync_start.isoformat(),
                    "emails_processed": processed, "transactions_added": 0,
                    "status": "error", "error": str(e)[:500],
                }).execute()
            except Exception:
                pass
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _cors(self, status):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, *args):
        pass
