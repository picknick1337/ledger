"""
POST /api/debug
Runs each sync stage independently and returns detailed logs.
REMOVE THIS ENDPOINT before going to production.
"""
import os, sys, json, base64, httpx
import google.generativeai as genai
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(__file__))
from _utils import get_supabase, get_google_tokens_for_user

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
GMAIL_QUERY = (
    "newer_than:62d ("
    "subject:(debited OR spent OR \"transaction alert\" OR \"credit card\" OR "
    "\"Transaction alert\" OR \"amount\" OR \"INR\" OR \"Rs.\") "
    "OR from:(icicibank.com OR hdfcbank.com OR axisbank.com OR sbicard.com "
    "OR kotak.com OR yesbank.in OR sc.com)"
    ")"
)

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__(); self._parts = []
    def handle_data(self, d): self._parts.append(d)
    def get_text(self): return " ".join(p.strip() for p in self._parts if p.strip())[:2000]

def strip_html(html):
    s = _HTMLStripper(); s.feed(html); return s.get_text()

def refresh_token(refresh_token_val):
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": refresh_token_val,
        "grant_type": "refresh_token",
    }, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

def gmail_get(path, token, params=None):
    r = httpx.get(f"{GMAIL_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def get_body(msg):
    payload = msg.get("payload", {})
    hdrs = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = hdrs.get("Subject", "")
    def decode(part):
        data = part.get("body", {}).get("data", "")
        if not data: return ""
        dec = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        return strip_html(dec) if part.get("mimeType") == "text/html" else dec[:2000]
    def extract(part):
        if part.get("mimeType") in ("text/plain", "text/html"): return decode(part)
        for sub in part.get("parts", []):
            r = extract(sub)
            if r: return r
        return ""
    return subject, extract(payload) or msg.get("snippet", "")


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) if length else b"{}")
        user_id = body.get("user_id")
        stage   = body.get("stage", "all")  # "tokens"|"gmail"|"parse"|"supabase"|"all"
        logs    = []

        def log(msg, data=None):
            entry = {"msg": msg}
            if data is not None: entry["data"] = data
            logs.append(entry)

        try:
            # ── Stage 1: Check tokens ─────────────────────────────────────
            log("Checking user_tokens in Supabase...")
            token_row = get_google_tokens_for_user(user_id)
            if not token_row:
                self._json(200, {"ok": False, "logs": logs, "error": "No token row found for user_id. Gmail not connected."})
                return
            log("Token row found", {
                "has_access_token":  bool(token_row.get("access_token")),
                "has_refresh_token": bool(token_row.get("refresh_token")),
                "updated_at":        token_row.get("updated_at"),
            })

            if stage == "tokens":
                self._json(200, {"ok": True, "logs": logs}); return

            # ── Stage 2: Refresh access token ─────────────────────────────
            log("Refreshing Google access token...")
            try:
                access_token = refresh_token(token_row["refresh_token"])
                log("Access token refreshed OK")
            except Exception as e:
                log(f"Token refresh FAILED: {e}")
                self._json(200, {"ok": False, "logs": logs, "error": str(e)}); return

            # ── Stage 3: Gmail search ─────────────────────────────────────
            log("Searching Gmail...", {"query": GMAIL_QUERY})
            try:
                search = gmail_get("/users/me/messages", access_token,
                                   {"q": GMAIL_QUERY, "maxResults": 10})
                msgs = search.get("messages", [])
                log(f"Gmail returned {len(msgs)} messages (showing first 10)", {
                    "total_estimate": search.get("resultSizeEstimate"),
                    "ids": [m["id"] for m in msgs],
                })
            except Exception as e:
                log(f"Gmail search FAILED: {e}")
                self._json(200, {"ok": False, "logs": logs, "error": str(e)}); return

            if not msgs:
                log("No emails matched the query. Try a broader search.")
                self._json(200, {"ok": False, "logs": logs, "error": "Zero emails matched Gmail query"}); return

            if stage == "gmail":
                self._json(200, {"ok": True, "logs": logs}); return

            # ── Stage 4: Fetch + parse first 3 emails via Gemini ──────────
            log("Fetching and parsing first 3 emails via Gemini...")
            parse_results = []
            for m in msgs[:3]:
                mid = m["id"]
                try:
                    msg_data = gmail_get(f"/users/me/messages/{mid}", access_token, {"format": "full"})
                    subject, body_text = get_body(msg_data)
                    log(f"Email {mid}", {"subject": subject, "body_preview": body_text[:200]})

                    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
                    model = genai.GenerativeModel('models/gemini-2.5-flash')
                    
                    prompt = f"""Extract credit card transaction from email. Return JSON only:
{{"is_transaction":bool,"merchant":str|null,"amount":number|null,"currency":"INR","date":"YYYY-MM-DD"|null,"category":str|null}}

Subject: {subject}

Body:
{body_text[:2000]}"""
                    
                    resp = model.generate_content(
                        prompt,
                        generation_config=genai.types.GenerationConfig(
                            temperature=0.1,
                            max_output_tokens=400,
                        )
                    )
                    raw = resp.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                    parsed = json.loads(raw)
                    parse_results.append({"id": mid, "subject": subject, "parsed": parsed})
                    log(f"Gemini parsed email {mid}", parsed)
                except Exception as e:
                    parse_results.append({"id": mid, "error": str(e)})
                    log(f"Parse error for {mid}: {e}")

            if stage == "parse":
                self._json(200, {"ok": True, "logs": logs, "parse_results": parse_results}); return

            # ── Stage 5: Check Supabase transactions table ─────────────────
            log("Checking Supabase transactions table...")
            try:
                sb = get_supabase()
                result = sb.table("transactions").select("id,merchant,amount,date,currency").eq("user_id", user_id).limit(5).execute()
                log(f"transactions table has {len(result.data or [])} rows for this user", result.data)
            except Exception as e:
                log(f"Supabase query FAILED: {e}")
                self._json(200, {"ok": False, "logs": logs, "error": str(e)}); return

            self._json(200, {"ok": True, "logs": logs, "parse_results": parse_results})

        except Exception as e:
            logs.append({"msg": f"Unexpected error: {e}"})
            self._json(500, {"ok": False, "logs": logs, "error": str(e)})

    def _json(self, status, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args): pass
